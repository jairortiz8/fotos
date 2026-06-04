# ADR 0008 — Dashboard admin custom (no Django admin) para el uso diario

- **Estado**: Aceptado
- **Fecha**: Fase 5
- **Decisión de**: Jair (prompt de Fase 5) + Claude

## Contexto

En Fase 1 montamos el Django admin con `django-unfold` (ADR 0002) como interfaz
de gestión. Funciona, pero el admin de Django es genérico (CRUD tabular) y no
encaja con el flujo de trabajo real del super admin de RunFoto:

- Aprobar/rechazar fotos de a cientos, con vista de grilla y atajos de teclado.
- Generar links de upload con QR y mensaje de WhatsApp listo para copiar.
- Ver un evento como una unidad (resumen + fotos + fotógrafos + dorsales) con tabs.
- Métricas a un vistazo.

Replicar las pantallas 08–13 del design system dentro del Django admin es pelear
contra el framework. El prompt de Fase 5 pidió un dashboard propio.

## Decisión

Construimos un **dashboard custom** en `apps/dashboard/`, montado en
`/dashboard/`, con sus propias vistas (CBV + HTMX + Alpine), templates que
replican el design system, y autenticación propia (login en `/dashboard/login/`).

El **Django admin (unfold) sigue existiendo** como *fallback de emergencia*,
movido de `/admin/` a **`/admin/django/`**. No es de uso diario, pero permite
editar cualquier registro a mano si algo del dashboard falla.

Puntos de diseño:

- **Acceso**: `StaffRequiredMixin` exige login + `is_staff`. Un usuario sin
  permiso se redirige al login (no un 403 que confirme que el panel existe).
- **Auditoría**: TODAS las acciones (crear/editar evento, aprobar/rechazar foto,
  generar/revocar link, cambiar contraseña, editar dorsales) van a `AuditLog`.
- **Counters denormalizados**: se recalculan **síncrono** (`services.
  recalculate_event_counters`), no con Celery — el worker no corre en prod y los
  counters son baratos (un par de COUNTs).
- **Stats sin tracking nuevo**: las métricas se derivan de datos ya existentes
  (fotos por día/hora, totales por evento). NO se creó `SearchLog` — respeta la
  decisión de privacidad de Fase 3 (no guardamos qué busca cada visitante). Por
  eso no hay "búsquedas por día" ni "top dorsales buscados".
- **QR**: generado server-side con la librería `qrcode` (PNG en base64 inline).

## Consecuencias

- (+) UX a medida del flujo real: aprobar 50 fotos toma pocos clicks (multi-select
  + bulk, o atajos A/R/←/→).
- (+) El admin de Django queda como red de seguridad sin mantenimiento extra.
- (+) Diseño 100% fiel al design system (mismas fuentes, colores, componentes).
- (−) Más código que mantener que el admin auto-generado.
- (−) Dos lugares para "editar un evento" (dashboard + `/admin/django/`). El
  dashboard es la fuente de verdad para el uso diario.

## Pantallas del design replicadas

08 dashboard home · 10 generar link (modal + QR) · 11 cola de aprobación ·
12 drawer de detalle (EXIF + dorsales editables) · 13 detalle de evento (tabs).
Las pantallas "login" y "lista/form de eventos" no estaban en el design de
referencia; se construyeron coherentes con el lenguaje visual.
