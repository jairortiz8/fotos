# Runbook operacional — RunFoto

> Este archivo crece fase a fase. Hoy (Fase 0) sólo tiene el esqueleto.

## Tabla de contenido

- [Acceso a producción](#acceso-a-producción)
- [Cómo deployar](#cómo-deployar)
- [Cómo levantar el stack local](#cómo-levantar-el-stack-local)
- [Backups](#backups)
- [Rotación de credenciales](#rotación-de-credenciales)
- [Incidentes comunes](#incidentes-comunes)

---

## Acceso a producción

- **Railway**: dashboard `<pendiente, agregar cuando el proyecto esté
  conectado>`.
- **Cloudflare R2**: dashboard `<pendiente>`.
- **GitHub**: <https://github.com/jairortiz8/fotos>.
- **Sentry**: `<pendiente>`.

## Cómo deployar

Hoy todavía no hay deploy automático. Cuando se conecte Railway al repo,
el flujo será:

1. Mergear PR en `main`.
2. GitHub Actions corre `ruff`, `mypy`, `pytest`. Tiene que estar en verde.
3. Railway detecta el push a `main` y dispara el build con el `Dockerfile`.
4. El servicio `web` ejecuta `python manage.py migrate --noinput` antes de
   arrancar `gunicorn`.
5. Los servicios `worker` y `beat` reciben la misma imagen pero arrancan
   con comandos distintos (`celery -A config worker` / `celery -A config beat`).

## Cómo levantar el stack local

Ver `README.md` para el setup completo. Resumen:

```bash
# Una sola vez
brew install python@3.12 postgresql@16 pgvector redis
brew services start postgresql@16
brew services start redis
createdb runfoto
psql runfoto -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Cada vez que abrís el proyecto
source .venv/bin/activate
python manage.py migrate
python manage.py runserver
```

Alternativa con Docker (cuando Docker Desktop esté instalado):

```bash
docker compose up
```

## Backups

> **Fase 0**: no aplica todavía (no hay datos en producción).
>
> **Fase 1+**: Railway hace snapshots automáticos de Postgres. Documentar
> acá la frecuencia y cómo restaurar.

## Rotación de credenciales

> Documentar acá:
> - Cuándo rotar `SECRET_KEY` (nunca durante la vida normal; sólo si se
>   filtra).
> - Cómo rotar las credenciales de R2 (generar nuevo par en Cloudflare,
>   actualizar Railway secrets, redeploy).
> - Cómo rotar el password del super admin.

## Incidentes comunes

> Se llena fase a fase con cosas reales que pasen. Por ahora, vacío.

### Sintoma → Causa probable → Cómo arreglar

- _(pendiente — se completa cuando aparezcan los primeros incidentes)_
