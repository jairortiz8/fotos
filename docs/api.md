# Endpoints públicos de RunFoto

> **Importante**: RunFoto **no es una API JSON tradicional**. Es una aplicación
> renderizada en el servidor (SSR) con Django + HTMX + Alpine. La mayoría de los
> endpoints devuelven **HTML** (páginas completas o fragmentos parciales para
> HTMX), no JSON. Sólo unos pocos endpoints técnicos (health checks, estado del
> ZIP) responden JSON. Este documento describe los endpoints **públicos** (sin
> login) que un corredor, un fotógrafo o un monitor podrían tocar.

El **dashboard admin** (`/dashboard/...`) y el Django admin (`/admin/django/...`)
**no se documentan acá**: son interfaz de usuario con login, no una API. Ver
`docs/runbook.md` → "Usar el dashboard admin".

## Convenciones

- **Base URL**: el dominio del sitio (`https://<tu-dominio>/`).
- **`<slug>`**: el slug único de un evento (ej. `maraton-antigua-2026`).
- **CSRF**: los formularios HTML que hacen POST usan el token CSRF de Django
  (Django lo maneja solo en los templates). La **excepción** es el upload del
  fotógrafo, que es `csrf_exempt` (la autenticación es el token de la URL).
- **Rate limits**: viven en Redis, identificados por IP (o por token, en el caso
  del fotógrafo). Al excederse devuelven `429`. Detalle en ADR 0005 y `CLAUDE.md`
  §3. No se expone cuánto falta para resetear (no le damos pistas a un atacante).

---

## Público (corredores)

### `GET /` — Landing

- **Qué hace**: home pública. Lista los eventos públicos y ofrece un buscador de
  dorsal de entrada.
- **Devuelve**: HTML (página completa).
- **Auth**: no.

### `GET /eventos/<slug>/` — Galería del evento + búsqueda por dorsal

- **Qué hace**: galería paginada del evento. Es la **pantalla principal**.
  Si se pasa el parámetro `bib`, filtra a las fotos donde el OCR detectó ese
  dorsal (con cache de 5 min); si no hay resultados, muestra un empty state con
  **sugerencias de dorsales** con lectura OCR parecida que sí existen.
- **Método**: `GET`.
- **Parámetros (query string)**:
  - `bib` (opcional): número de dorsal a buscar (ej. `1042`; puede ser
    alfanumérico tipo `A123`).
  - `page` (opcional): número de página (paginación de 60 fotos, HTMX infinite
    scroll). Default `1`.
- **Devuelve**: HTML. Página completa en una carga normal; fragmento parcial si
  la pide HTMX (scroll/paginación).
- **Comportamiento según estado del evento** (política de retención, ADR 0003):
  - `public` / `live` / `upcoming` → galería completa + búsqueda + descargas.
  - `public_closed` / `searchable_only` → galería oculta, **sólo búsqueda por
    dorsal** (página "evento cerrado").
  - `archived` / `pending_deletion` → `404` amigable.
  - `private` / `draft` / `deleted` → `404`.
- **Rate limits** (sólo cuando hay búsqueda real, no por ver la galería):
  - **60 búsquedas / hora** por IP (general).
  - **10 búsquedas / día** por la combinación (IP, evento, dorsal).
  - Al excederse: `429` con página amable (`public/rate_limited.html`).
- **Auth**: no.

### `GET /eventos/<slug>/foto/<photo_id>/` — Lightbox de una foto

- **Qué hace**: vista ampliada (lightbox) de una foto, con el **preview marcado
  con watermark**. Permite navegar a la anterior/siguiente.
- **Método**: `GET`.
- **Parámetros (path)**: `slug` del evento, `photo_id` (entero).
- **Devuelve**: HTML (o fragmento parcial para HTMX).
- **Auth**: no. (El original sin watermark **nunca** se sirve acá; sólo se baja
  vía el ZIP firmado.)

### `GET /eventos/<slug>/buscar-selfie/` — Pantalla de búsqueda por selfie

- **Qué hace**: muestra el formulario para subir un selfie y buscar tus fotos por
  reconocimiento facial, con el banner de privacidad.
- **Método**: `GET`.
- **Devuelve**: HTML. **Si `FACE_SEARCH_ENABLED=false`** (el caso en prod hoy),
  devuelve una página "no disponible" con `503` y el tab se oculta.
- **Auth**: no.

### `POST /eventos/<slug>/buscar-selfie/` — Buscar por selfie

- **Qué hace**: recibe un selfie, **extrae el embedding en memoria** y busca caras
  similares en el evento por distancia coseno (threshold 0.55), agrupando por
  confianza. **El selfie y su embedding nunca se persisten** ni pasan por
  Celery/Redis (ADR 0006) — viven en RAM durante el request y se descartan.
- **Método**: `POST` (multipart/form-data).
- **Parámetros (form)**:
  - `selfie` (archivo, obligatorio): imagen con tu cara.
- **Devuelve**: HTML con los resultados (o fragmento HTMX). `503` si
  `FACE_SEARCH_ENABLED=false`.
- **Rate limit**: **20 búsquedas / hora** por IP (es más caro que el dorsal). Al
  excederse: `429`.
- **Privacidad**: la IP se hashea (con salt diaria) antes de cualquier log; el
  selfie no se guarda.
- **Auth**: no.

### `POST /descargas/crear/` — Crear un ZIP de descarga

- **Qué hace**: arma un ZIP con los **originales en alta resolución, sin
  watermark**, de las fotos seleccionadas. Crea un registro `ZipDownload` y
  dispara la task `generate_zip` (baja los originales de R2 → comprime → sube el
  ZIP a R2 → genera una signed URL de 1 hora).
- **Método**: `POST`.
- **Parámetros (form)**:
  - `photo_ids` (lista, repetida): IDs de las fotos a incluir, **o**
  - `ids` (string CSV): los mismos IDs separados por coma (alternativa).
- **Devuelve**: respuesta para que el frontend haga polling del estado (ver
  siguiente endpoint). En caso de rate limit, `429` con JSON
  `{"error": "rate_limited"}`.
- **Rate limit**: **5 ZIPs / hora** por IP.
- **Depende de**: el `worker` de Celery (en prod hoy pendiente de crear; sin él el
  ZIP queda en estado inicial sin generarse).
- **Auth**: no.

### `GET /descargas/estado/<download_id>/` — Estado del ZIP (polling)

- **Qué hace**: el frontend pollea este endpoint para saber si el ZIP ya está
  listo y obtener el link de descarga (signed URL, válido 1 hora).
- **Método**: `GET`.
- **Parámetros (path)**: `download_id` (entero, el del `ZipDownload`).
- **Devuelve**: el estado del ZIP (pendiente / listo / error) para que el bottom
  sheet de descarga lo muestre.
- **Auth**: no (el `download_id` es la referencia; el archivo real está detrás de
  una signed URL con expiración).

---

## Privacidad (corredores)

### `GET /privacidad/` — Política de privacidad

- **Qué hace**: página de política de privacidad (qué datos se procesan,
  retención, etc.).
- **Método**: `GET`. **Devuelve**: HTML. **Auth**: no.

### `GET /privacidad/borrar-mis-datos/` — Pantalla de borrado

- **Qué hace**: formulario para subir un selfie y solicitar el borrado de **todas
  tus fotos y embeddings** de **todos los eventos**, con la confirmación y el
  banner de privacidad.
- **Método**: `GET`. **Devuelve**: HTML. **Auth**: no.

### `POST /privacidad/borrar-mis-datos/` — Borrar mis datos

- **Qué hace**: extrae el embedding del selfie **en memoria**, busca coincidencias
  en TODOS los eventos (threshold 0.62, estricto) y borra: embeddings + bibs + los
  objetos en R2 (original/preview/thumbnail) + el `Photo` + el rastro asociado.
  A la task de borrado se le pasan **sólo los `photo_ids`**, nunca la biometría.
- **Método**: `POST` (multipart/form-data).
- **Parámetros (form)**:
  - `selfie` (archivo, obligatorio): imagen con tu cara.
  - `confirmed` (string, obligatorio): debe ser `yes` para confirmar.
- **Devuelve**: HTML con el resultado (cantidad de fotos encontradas/borradas).
- **Rate limit**: **5 solicitudes / hora** por IP (operación seria).
- **Privacidad**: el selfie/embedding no se persiste; la IP se hashea.
- **Depende de**: el `worker` para el borrado efectivo de los archivos en R2 (en
  prod pendiente). El match es síncrono.
- **Auth**: no.

---

## Fotógrafos (acceso por token, sin cuenta)

El fotógrafo no tiene cuenta. El admin le genera un **link único** del tipo
`/u/<token>/`. El token se valida por su hash sha256 en **cada** request (no se
confía en sesiones).

### `GET /u/<token>/` — Portal de subida

- **Qué hace**: muestra el portal de drag-and-drop para subir fotos del evento
  asociado al token.
- **Método**: `GET`.
- **Parámetros (path)**: `token` (string URL-safe de ~32 chars).
- **Devuelve**: HTML (el portal). Si el token está vencido o revocado → mensaje
  claro de que el link ya no es válido (`410`).
- **Rate limit**: **60 requests / minuto** por IP (carga del portal).
- **Auth**: el token de la URL.

### `POST /u/<token>/upload/` — Subir una foto

- **Qué hace**: recibe **una** foto, valida que sea un JPEG real (magic bytes), la
  sube a R2 (`events/<slug>/originals/<uuid>.jpg`), crea el `Photo` en
  `status=processing` y dispara la task `process_photo` (EXIF + preview con
  watermark + thumbnail → encadena OCR).
- **Método**: `POST` (multipart/form-data). **`csrf_exempt`**: la autenticación es
  el token de la URL + el rate limit por token + el hash sha256 (no hay sesión que
  CSRF defienda).
- **Parámetros (form)**:
  - `file` (archivo, obligatorio): la imagen JPEG (máximo `PHOTO_UPLOAD_MAX_MB`,
    default 15 MB).
- **Devuelve**: JSON con el resultado del upload.
  - `410` `{"error": "invalid_link"}` si el token está muerto/revocado.
  - `403` `{"error": "photo_limit_reached"}` si se alcanzó el `photo_limit` del
    link (distinto del 410 a propósito).
- **Rate limit**: **100 fotos / minuto** por token (anti-flood, pero permite
  ráfagas).
- **Depende de**: el `worker` para el procesamiento (en prod pendiente; sin él la
  foto sube pero queda en `processing`).
- **Auth**: el token de la URL.

---

## Endpoints técnicos / operación

### `GET /healthz/lite` — Health check liviano (probe de Railway)

- **Qué hace**: chequea **sólo la base de datos**. Es barato y no depende de R2 ni
  de los workers. Es el probe que usa Railway (`railway.toml`).
- **Método**: `GET`.
- **Devuelve**: JSON.
  - `200` `{"status": "ok"}` si la DB responde.
  - `503` `{"status": "degraded"}` si la DB no responde.
- **Auth**: no. (Exento del redirect HTTPS para que el probe interno por HTTP
  funcione.)

### `GET /healthz` — Health check profundo (monitoreo manual)

- **Qué hace**: chequea DB, Redis, R2, workers de Celery y la existencia del
  schedule de beat. Pensado para diagnóstico manual, **no** como probe de Railway.
- **Método**: `GET`.
- **Devuelve**: JSON con esta forma:

  ```json
  {
    "status": "ok",
    "checks": {
      "db": {"ok": true},
      "redis": {"ok": true},
      "r2": {"ok": true, "configured": true},
      "celery_workers": {"ok": true, "workers": 1},
      "celery_beat": {"ok": true, "scheduled_tasks": 8}
    },
    "version": "<GIT_SHA>",
    "timestamp": "<ISO-8601>"
  }
  ```

  - `status` = `"ok"` si todo pasa; `"degraded"` si DB+Redis están bien pero algún
    check informativo falla (típicamente `celery_workers.workers: 0` cuando no hay
    worker — **esperable en prod hoy**); `"down"` si falla DB o Redis.
  - HTTP `200` si DB y Redis están OK (incluso si está `degraded`); `503` sólo si
    falla DB o Redis.
- **Auth**: no.

### `GET /sitemap.xml` — Sitemap

- **Qué hace**: sitemap XML con los eventos públicos + algunas vistas estáticas
  (para SEO).
- **Método**: `GET`. **Devuelve**: XML. **Auth**: no.

### `GET /robots.txt` — robots.txt

- **Qué hace**: robots permisivo para el contenido público, pero **bloquea**
  `/admin/`, `/dashboard/`, `/u/`, `/descargas/` y `/__debug__/`. Incluye el link
  al `sitemap.xml`.
- **Método**: `GET`. **Devuelve**: texto plano. **Auth**: no.

---

## Páginas informativas (HTML, sin lógica de API)

| Ruta          | Qué es                                                            |
| ------------- | ---------------------------------------------------------------- |
| `/terminos/`  | Términos de uso.                                                  |
| `/cookies/`   | Política de cookies.                                              |
| `/contacto/`  | Página de contacto **informativa** (sin formulario de email, por la política "nada de email"). |

Todas: `GET`, devuelven HTML, sin auth.

---

## Lo que RunFoto **no** expone

- **No hay e-commerce, cart ni pricing** (las fotos son gratis).
- **No hay cuentas de corredor ni de fotógrafo** (sólo la del super admin).
- **No hay API JSON pública** para integraciones de terceros (es un sitio SSR).
- **Los originales sin watermark nunca se sirven por un endpoint directo** — sólo
  vía la signed URL temporal (1 hora) del ZIP de descarga.
