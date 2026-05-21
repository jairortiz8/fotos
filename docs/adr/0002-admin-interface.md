# ADR 0002 — Paquete para el Django Admin custom

- **Fecha**: 2026-05-21
- **Estado**: Aceptado
- **Decisores**: Jair

## Contexto

`CLAUDE.md` §6 (Fase 1) pide un Django Admin "custom y bonito, no el default feo". Y §5 dice que la paleta de colores y la tipografía deben replicar `reference/runfoto-design/index.html` (dark theme con `#0A0A0B` de fondo, `#FC5200` como acento naranja para CTAs, `#00D4FF` cyan para datos numéricos).

En 2026 hay tres paquetes maduros para "Django Admin tuneado":

1. **`django-admin-interface`** (>1M downloads/mes, mantenido)
2. **`django-jazzmin`** (>500k downloads/mes, mantenido, basado en AdminLTE/Bootstrap)
3. **`django-unfold`** (>200k downloads/mes, mantenido, basado en Tailwind v3+)

## Decisión

Usamos **`django-unfold`**.

## Razones

1. **Stack consistente con el resto del proyecto.** RunFoto ya usa Tailwind CSS v4 (Fase 0) para los templates públicos. Unfold también es Tailwind-first; reutilizamos vocabulario de utilities, los mismos colores, y la misma filosofía de "design tokens en CSS vars". `django-admin-interface` y `django-jazzmin` arrastran Bootstrap o jQuery — extra runtime que no necesitamos.

2. **Dark mode nativo y configurable.** El design system de RunFoto es dark-first. Unfold soporta dark mode out-of-the-box y permite override de la paleta con un dict `UNFOLD["COLORS"]`. Jazzmin tiene dark mode pero menos "polished"; admin-interface lo hace via DB (incómodo para versionar).

3. **API de configuración declarativa en `settings.py`.** Toda la config de Unfold vive en `UNFOLD = {...}` — colors, sidebar, dashboard callback. Eso queda en code review, en git, y en `settings/base.py` junto al resto del setup. En cambio `admin-interface` guarda la config en la DB (fila editable desde el propio admin), lo que rompe el principio "infrastructure as code" y hace casi imposible reproducir la config en CI o en dev.

4. **Componentes modernos listos para usar.** Unfold trae:
   - `ModelAdmin` con sidebar collapsible, breadcrumbs y badges.
   - `TabularInline` con tabs en el detail page.
   - Acciones bulk con decorador `@action`.
   - Search global en el sidebar.
   - Dashboard callback para meter widgets custom (stats cards, gráficos) en Fase 5.

5. **Sin dependencias pesadas.** Unfold pesa ~1 MB (estáticos + python). Jazzmin trae AdminLTE entero (~3 MB). admin-interface es liviano pero arrastra `django-colorfield`.

## Alternativas y por qué no

- **`django-jazzmin`**: muy popular y maduro, pero su look-and-feel (AdminLTE) ya se siente antiguo en 2026 y customizar la paleta dark requiere overrides de CSS más invasivos.
- **`django-admin-interface`**: muy ligero y bonito, pero la config en DB es un anti-pattern para nuestro caso (queremos infra reproducible, no fila editable).
- **No usar nada (Django admin default)**: contradice CLAUDE.md §6.
- **Hacer un dashboard 100% custom desde cero**: planeado para Fase 5 (apps/dashboard/) — convive con Unfold. Unfold es para CRUD; el dashboard custom es para los flujos rituales del super admin (cola de aprobación, generar links con QR).

## Configuración aplicada

En `config/settings/base.py`:

- `INSTALLED_APPS` incluye `unfold` + `unfold.contrib.filters` + `unfold.contrib.forms` **antes** de `django.contrib.admin`.
- `UNFOLD` dict con:
  - `SITE_TITLE` y `SITE_HEADER` desde `SITE_NAME` (env var, nunca hardcodeado).
  - `COLORS`: paleta base derivada de `--color-ink-*` del design system (RGB triplets); primary derivado de `#FC5200`.
  - `SIDEBAR`: navegación agrupada en 4 secciones (Contenido / Operación / Privacidad / Sistema), con iconos Material Symbols.
  - `BORDER_RADIUS`: `8px` — coincide con `--radius-control` del design system.

Cada `ModelAdmin` hereda de `unfold.admin.ModelAdmin` (no del `admin.ModelAdmin` clásico) para acceder a los componentes Unfold (tabs en inlines, pills, decorators).

## Consecuencias

### Positivas
- Mismo lenguaje visual entre app pública (Tailwind) y admin (Unfold/Tailwind).
- Configuración versionada en git.
- Dashboard callback queda listo para Fase 5 sin reinstalar nada.

### Negativas / riesgos
- Unfold está activamente desarrollado y suele introducir cambios menores en estructuras (`UNFOLD["SIDEBAR"]` evolucionó dos veces). Mitigación: pinear minor version (`>=0.45,<0.46`).
- Material Symbols icons llegan via fuente Google. Cuando endurezcamos CSP en Fase 6, hay que listar el origen o auto-hostear la fuente. Anotado en `docs/runbook.md`.

## Migración futura

Si llega un punto en que Unfold deja de mantenerse o decidimos migrar:
- El `ModelAdmin` de Unfold es API-compatible con el de Django: bastaría cambiar el import.
- La config visual (`UNFOLD`) se borra; la paleta del admin pasa a ser la default de Django.
- Cero pérdida de funcionalidad.
