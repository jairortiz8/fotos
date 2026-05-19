# ADR 0001 — Selección de stack

- **Fecha**: 2026-05-19
- **Estado**: Aceptado
- **Decisores**: Jair (super admin / único stakeholder)

## Contexto

RunFoto es una plataforma web gratuita de fotos de carreras deportivas para
el mercado centroamericano (arranque Guatemala / El Salvador). Año 1 se
proyectan 15-20 eventos y un máximo de 4.000 fotos por evento, con JPGs de
3-5 MB. El presupuesto operativo inicial es de ~USD 20/mes.

El proyecto tiene un único usuario administrador (el dueño del producto).
Los corredores acceden sin cuenta. Los fotógrafos suben fotos vía un token
URL único, también sin cuenta. La interfaz es server-side rendered, con
interactividad ligera (multi-select de fotos, modales, infinite scroll).

Hay dos cargas de trabajo de ML:
1. OCR de dorsales en upload (no bloqueante).
2. Reconocimiento facial con embeddings de 512 dimensiones para búsqueda
   por selfie.

## Decisión

| Capa            | Tecnología                                  |
| --------------- | ------------------------------------------- |
| Lenguaje        | Python 3.12                                 |
| Framework web   | Django 5 (+ DRF donde haga falta JSON)      |
| Frontend        | HTMX + Alpine.js + Tailwind CSS (SSR)       |
| Base de datos   | PostgreSQL 16 + extensión pgvector          |
| Cola async      | Celery + Redis                              |
| ML — OCR        | PaddleOCR (primario) + EasyOCR (fallback)   |
| ML — Caras      | InsightFace `buffalo_l` (vectores 512-d)    |
| Storage         | Cloudflare R2 (vía boto3, S3-compat)        |
| Hosting         | Railway (web + workers + Postgres + Redis)  |
| Monitoring      | Sentry (free tier)                          |
| Notificaciones  | Interfaz abstracta `Notifier`; hoy WhatsApp manual |

## Razones

### Por qué Django (y no FastAPI / Flask / Node)

- La aplicación es ~80% CRUD con SSR. Django trae ORM maduro, sistema de
  migrations probado, admin generable, auth, i18n, sesiones, CSRF, y un
  ecosistema enorme. Reducimos código a escribir y deuda técnica.
- Jair no es desarrollador full-time. Django tiene la curva de aprendizaje
  más predecible y la documentación más completa del ecosistema.
- DRF se reserva sólo para endpoints JSON puntuales (ej. autocompletar de
  eventos), evitando overhead innecesario.

### Por qué HTMX (y no React / Vue / SPA)

- No hay flujos genuinamente interactivos que requieran estado client-side
  rico. La galería, filtros y multi-select se modelan limpiamente con
  intercambios HTML parciales.
- Bundle de JS final ~14 KB (HTMX) + ~17 KB (Alpine). Página rápida sin
  hidratación.
- Sin build pipeline complejo (no webpack, no Vite). Solo Tailwind compila.
- Equipo de una persona; no hay budget para mantener un frontend SPA aparte.

### Por qué PostgreSQL 16 + pgvector

- Postgres soporta JSONB, GIN indexes, transacciones fuertes — todo lo que
  pide la app.
- pgvector permite guardar los embeddings de InsightFace en la misma DB que
  el resto del modelo, sin agregar un servicio extra (Pinecone, Weaviate,
  Qdrant). Con 4.000 fotos × ~3 caras/foto × 15 eventos/año ≈ 180k vectores
  estimados, pgvector con índices IVFFlat o HNSW es más que suficiente.

### Por qué Cloudflare R2 (y no S3 / GCS / B2)

- **Egress gratis**. Cuando un corredor descargue un ZIP de 50 fotos
  (~200 MB) no nos cobra Cloudflare por servirle el archivo.
  Esto es crítico cuando el modelo del producto es "fotos gratis".
- API S3-compatible, así que `boto3` con `endpoint_url` custom funciona sin
  cambios.
- Precio de storage similar a S3 estándar (~USD 0.015/GB/mes).

### Por qué Railway (y no Render / Fly / AWS)

- Una sola plataforma para web + Postgres + Redis + workers Celery.
- Deploy a partir de `Dockerfile`; sin lock-in de runtime propietario.
- Precio escalable desde ~USD 5/mes para empezar.
- Si en el futuro escalamos fuera de Railway, el `Dockerfile` y el
  `docker-compose.yml` hacen la migración trivial.

### Por qué empezar sin email (y con un `Notifier` abstracto)

- En el día cero los links de upload se mandan por WhatsApp manualmente
  (Jair copia y pega). Esto evita: cuenta de SMTP, dominio verificado para
  SPF/DKIM, problemas de deliverability.
- La capa abstracta `Notifier` permite enchufar Brevo, Resend o Postmark
  cambiando una env var, sin tocar el resto del código.

## Alternativas consideradas y descartadas

- **FastAPI + React/Next**: dos repos, dos pipelines de build, mucho más
  código boilerplate para algo que no necesita SPA.
- **AWS S3 + CloudFront**: egress paid se vuelve un problema con descargas
  gratuitas de ZIPs grandes.
- **Heroku**: precio creció, ya no hay tier free, integración con Postgres
  + workers menos fluida que Railway.
- **Embedding service externo (Pinecone, etc.)**: cuesta extra, agrega
  latencia y un punto de falla. pgvector cubre el caso de uso.

## Consecuencias

### Positivas
- Stack cohesivo: todo en Python excepto compilación de Tailwind.
- Un solo runtime, un solo lenguaje, un solo ORM.
- Operación barata (~USD 20/mes inicial).
- Migración fuera de Railway trivial (todo está dockerizado).

### Negativas / riesgos
- Django + Celery + ML libs no es trivial de optimizar en cold start.
  Mitigación: workers con keep-alive, modelos de InsightFace cargados una vez.
- HTMX tiene comunidad más chica que React — menos snippets de Stack
  Overflow. Mitigación: documentar patrones reutilizables en `docs/`.
- pgvector con muchos vectores requiere índices apropiados. Mitigación:
  evaluar HNSW vs IVFFlat cuando se acerque el límite de performance.
