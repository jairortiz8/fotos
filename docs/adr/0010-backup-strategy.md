# ADR 0010 — Estrategia de backups de la base de datos

- **Estado**: Aceptado
- **Fecha**: Fase 6
- **Decisión de**: Jair + Claude

## Contexto

Al ir a producción necesitamos backups de la base de datos. La DB guarda todo lo
que no está en R2: eventos, fotos (metadata), dorsales, embeddings faciales,
links de fotógrafo, audit log. Perderla sería catastrófico aunque las imágenes
sigan en R2 (no sabríamos a qué evento pertenece cada foto, ni los dorsales
detectados).

Queremos una estrategia con redundancia: que no dependa de un solo mecanismo ni
de un solo proveedor.

## Decisión

Dos niveles de backup:

### Primario — snapshots automáticos de Railway

El servicio Postgres de Railway hace **snapshots automáticos gestionados por la
plataforma**. Es la primera línea: no requiere código nuestro, lo maneja Railway.
El procedimiento de restauración queda **documentado en el runbook** (cómo
restaurar un snapshot desde el dashboard de Railway).

### Secundario / adicional — `pg_dump` a R2

Backup propio, independiente de Railway, por si algún día migramos de plataforma o
queremos una copia bajo nuestro control:

- Comando de management **`python manage.py backup_db`** + task de Celery
  **`core.backup_database`** (Celery beat, todos los días a la **1 AM**).
- Hace `pg_dump` → comprime con gzip → sube a R2 bajo el prefijo
  **`backups/db/<timestamp>.sql.gz`**.
- **Poda automática**: borra los backups con más de **30 días**.
- **Resiliente por diseño**: si falta el binario `pg_dump`, o R2 no está
  configurado, **loggea el problema y NO rompe** (no tira la task ni el deploy).
  Un backup que falla en silencio sería peor, por eso loggea; pero un backup que
  voltea el sistema también, por eso no lanza excepción fatal.

### Bucket

Usamos el bucket **`runfoto-prod`** con el prefijo **`backups/db/`**. **No
creamos un bucket separado** para backups — sólo existe ese bucket (consistente
con lo decidido en fases anteriores: un único bucket por ahora).

## Consecuencias / Limitaciones

Siendo honestos sobre el estado real hoy:

- **Versión de `pg_dump`**: `pg_dump` necesita ser de versión **mayor o igual** a
  la del servidor. Railway corre **Postgres 18**, pero la imagen Docker **NO trae
  `postgresql-client-18` todavía** (no agregamos el repo PGDG para no arriesgar la
  estabilidad de los deploys con un repo externo).
- **Consecuencia directa**: el backup secundario funciona **en local** (donde
  corremos Postgres 16) pero **en producción todavía no**, porque le falta el
  cliente de pg18 en la imagen. Para habilitarlo en prod hay que agregar
  `postgresql-client-18` a la imagen Docker.
- **Mientras tanto**: el **primario (snapshots de Railway) cubre** la necesidad de
  backup en producción. El secundario es una mejora de redundancia pendiente.
- **Worker/beat en prod**: además, el worker y el beat de Celery **todavía no
  corren en producción** (pendiente de fases anteriores). Sin beat, la task
  diaria `core.backup_database` no se dispara sola en prod aunque el cliente
  estuviera instalado.

En resumen: en producción el backup HOY lo da Railway (primario). El backup
secundario a R2 está construido, testeado en local, y queda listo para activarse
en prod cuando (1) se agregue `postgresql-client-18` a la imagen y (2) corran
worker + beat.
