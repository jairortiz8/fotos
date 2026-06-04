# ADR 0009 — Headers de seguridad y Content Security Policy

- **Estado**: Aceptado
- **Fecha**: Fase 6
- **Decisión de**: Jair + Claude

## Contexto

Hasta Fase 5 sólo teníamos lo básico de transporte seguro: redirect HTTP→HTTPS y
HSTS sin ajustar. Al ir a producción real necesitamos un set completo de headers
de seguridad y una **Content Security Policy (CSP)** que limite de dónde puede
cargar recursos el sitio.

La idea es defensa en profundidad: aunque el sitio es 100% gratuito y no maneja
pagos, sí procesa datos sensibles (fotos, selfies, embeddings faciales). Un sitio
mal configurado puede ser víctima de clickjacking, sniffing de tipos MIME, o
inyección de scripts de terceros. Estos headers cierran esas puertas a nivel del
browser, gratis y sin tocar la lógica de la app.

## Decisión

Configuramos los siguientes headers. El detalle de cada uno y el porqué en
términos simples:

### Transporte (HTTPS forzado)

- **HSTS a 1 año** (`SECURE_HSTS_SECONDS=31536000`) + `includeSubDomains` +
  `preload`. Le dice al browser "este sitio SIEMPRE es HTTPS, ni se te ocurra
  entrar por HTTP durante el próximo año". Una vez que el browser lo vio, ya no
  hay ventana para un ataque de intercepción en la primera conexión. `preload`
  permite (a futuro) que el dominio venga marcado como HTTPS-only de fábrica en
  los browsers.
- **`SECURE_SSL_REDIRECT=True`**: cualquier request HTTP se redirige a HTTPS.
  Con **`SECURE_REDIRECT_EXEMPT` para `^healthz`**: el probe interno de salud de
  Railway pega por HTTP a `/healthz` y no debe ser redirigido (si no, el health
  check fallaría y Railway pensaría que el servicio está caído).

### Headers anti-ataque

- **`X-Frame-Options=DENY`**: nadie puede meter nuestro sitio dentro de un
  `<iframe>`. Previene **clickjacking** (que un sitio malicioso superponga
  nuestra UI y engañe al usuario para que haga clicks que no quería).
- **`SECURE_CONTENT_TYPE_NOSNIFF`**: el browser respeta el tipo MIME que
  declaramos y no "adivina". Evita que un archivo subido como imagen se
  interprete como script.
- **`SECURE_BROWSER_XSS_FILTER`**: activa el filtro anti-XSS del browser (legacy,
  pero suma).
- **`Referrer-Policy=strict-origin-when-cross-origin`**: al navegar a otro sitio,
  no filtramos la URL completa (que podría tener info sensible), sólo el origen.

### Cookies (en producción)

- Cookies de **sesión y CSRF** con `Secure` (sólo viajan por HTTPS) + `HttpOnly`
  (JavaScript no las puede leer, mitiga robo de sesión vía XSS) + `SameSite=Strict`
  (no se mandan en requests que vengan de otro sitio, mitiga CSRF).

### Content Security Policy

CSP con **django-csp 4.x**, definida en `base.py` (aplica **tanto en dev como en
prod** — así detectamos violaciones temprano, no recién en producción).
Directivas:

- `default-src 'self'` — por defecto, sólo recursos de nuestro propio dominio.
- `script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com` — HTMX y
  Alpine.js vienen de unpkg. Dos permisos especiales y por qué:
  - **`'unsafe-eval'` (obligatorio para Alpine)**: el build estándar de Alpine
    (`cdn.min.js`) evalúa las expresiones de sus directivas (`x-data`, `x-show`,
    `@click`, ...) con `new Function()`. El navegador real **bloquea** eso sin
    `'unsafe-eval'`, y entonces se rompe TODA la interactividad de Alpine
    (selección múltiple, bottom sheet de descarga, menú y drawer del dashboard,
    navegación del lightbox). Lo verificamos en navegador en Fase 6 (sin el
    permiso, la consola se llena de `Alpine Expression Error: ... 'unsafe-eval'`).
  - **`'unsafe-inline'`**: cubre los pocos `<script>` inline (p. ej. la función
    `photoSelection()` de la galería) y los handlers inline. (Aclaración: las
    directivas de Alpine NO son "scripts inline" para el navegador — eso es lo
    que cubre `'unsafe-eval'`; la versión anterior de este ADR lo explicaba mal.)
- `style-src 'self' 'unsafe-inline'` — estilos propios + algún estilo inline.
- `font-src 'self'` — **auto-hospedamos las fuentes** (Space Grotesk, Inter,
  JetBrains Mono). NO usamos Google Fonts, así que ningún tercero recibe los
  requests de fuentes (mejor privacidad y una dependencia externa menos).
- `img-src 'self' data: https://*.r2.cloudflarestorage.com` — imágenes propias,
  imágenes embebidas en `data:` (el QR de los links de upload se genera así) y
  previews/thumbnails servidos desde Cloudflare R2.
- `connect-src 'self'` + el endpoint de **Sentry** — las llamadas fetch/XHR van a
  nuestro dominio; Sentry necesita su endpoint para reportar errores.
- `frame-ancestors 'none'` — refuerza el anti-clickjacking a nivel CSP (la versión
  moderna de `X-Frame-Options`).
- `object-src 'none'` — nada de `<object>`/`<embed>` (vector clásico de ataques).
- `base-uri 'self'` — nadie puede reescribir la URL base de la página.
- `form-action 'self'` — los forms sólo pueden enviar datos a nuestro dominio.

### Subresource Integrity (SRI) — bug encontrado en Fase 6

HTMX y Alpine se cargan desde unpkg con un atributo `integrity="sha384-..."`
(SRI): el navegador descarga el archivo, calcula su hash y **se niega a
ejecutarlo si no coincide** — protege contra que el CDN sea comprometido y nos
sirva un script alterado.

Durante la verificación de CSP de Fase 6 descubrimos que **el hash SRI de Alpine
estaba mal** desde que se escribió `base.html`. Como el contenido de un paquete
npm publicado es inmutable, el hash nunca coincidió → **Alpine jamás se ejecutó
en ningún navegador real**, dejando silenciosamente rota toda la interactividad
(selección múltiple, lightbox, sheet de descarga, menú/drawer del dashboard). No
se había notado porque las verificaciones previas (Fases 3 y 5) fueron con
*screenshots* (render estático), que no prueban la interactividad. Corregido al
hash correcto y verificado en navegador que Alpine inicializa y reacciona.

**Recomendación a futuro (hardening)**: auto-hospedar HTMX y Alpine en `static/`
(igual que ya hacemos con las fuentes). Elimina la dependencia de unpkg (si unpkg
cae, el sitio se rompe), elimina el mantenimiento manual de hashes SRI (origen de
este bug), permite sacar `https://unpkg.com` del `script-src` (CSP más estricta)
y es más rápido (mismo origen). Queda anotado como tarea separada.

## Consecuencias

- (+) Protección estándar de la industria contra clickjacking, sniffing, XSS y
  carga de recursos no autorizados, todo aplicado por el browser.
- (+) Mejor score en herramientas como securityheaders.com (señal de seriedad).
- (+) Sin Google Fonts: un tercero menos viendo a nuestros visitantes.
- (−) `'unsafe-eval'` + `'unsafe-inline'` en `script-src` es un compromiso: los
  exige el build estándar de Alpine.js. Está **mitigado** por el resto de la CSP
  (origen restringido a `'self'` + unpkg, `object-src 'none'`, `base-uri 'self'`,
  `frame-ancestors 'none'`, etc.), pero no es el ideal teórico. Es el perfil
  habitual de un sitio HTMX + Alpine + Tailwind.
- **Nota a futuro (CSP más estricta)**: migrar al build **`@alpinejs/csp`** (que
  no usa `eval`) permitiría quitar `'unsafe-eval'`; reescribiendo las expresiones
  inline como componentes `Alpine.data(...)` y usando **nonces** se podría quitar
  también `'unsafe-inline'`. Es bastante trabajo de frontend y se deja para
  después; hoy la prioridad fue que la interactividad funcione en producción.
- **Aprendizaje de proceso**: verificar la interactividad en un navegador real
  (no sólo screenshots) tras tocar CSP/SRI. El bug del hash de Alpine vivía desde
  Fase 3 sin detectarse.
