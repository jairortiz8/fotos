# Diagrama de entidades (ERD)

```mermaid
erDiagram
    USER ||--o| USERMFA : "tiene"
    USER ||--o{ AUDITLOG : "actúa"

    EVENT ||--o{ PHOTO : "contiene"
    EVENT ||--o{ PHOTOGRAPHERLINK : "habilita"

    PHOTOGRAPHERLINK ||--o{ PHOTO : "subió"

    PHOTO ||--o{ BIB : "tiene"
    PHOTO ||--o{ FACEEMBEDDING : "tiene"

    DATADELETIONREQUEST ||--o{ PHOTO : "borra"

    USER {
        bigint id PK
        string username UK
        string email
        bool is_staff
        bool is_superuser
        datetime created_at
        datetime updated_at
    }

    USERMFA {
        bigint id PK
        bigint user_id FK
        encrypted totp_secret "NULL hasta activar MFA"
        json backup_codes
        bool is_active
        datetime activated_at
    }

    AUDITLOG {
        bigint id PK
        bigint user_id FK "nullable"
        string action "ej. event.created"
        string target_type
        string target_id
        json metadata
        ip ip_address "anonimizada (último octeto = 0)"
        datetime created_at
    }

    EVENT {
        bigint id PK
        string slug UK
        string name
        date date
        string status "8 estados: draft → upcoming → live → public_closed → searchable_only → archived → pending_deletion → deleted"
        string visibility "public | unlisted | private"
        datetime public_until "default: date + 90d"
        datetime searchable_until "default: date + 180d"
        datetime archive_until "default: date + 365d"
        bool permanent_archive
        int photo_count "denormalizado"
        int pending_count "denormalizado"
    }

    PHOTOGRAPHERLINK {
        bigint id PK
        bigint event_id FK
        string photographer_name
        string photographer_email "opcional"
        string photographer_phone "para WhatsApp"
        string token_hash UK "sha256(token)"
        datetime expires_at
        bool is_active
        datetime revoked_at "nullable"
        int photo_limit "nullable = sin límite"
        int photos_uploaded
        datetime last_used_at
        ip last_used_ip "anonimizada"
    }

    PHOTO {
        bigint id PK
        bigint event_id FK
        bigint photographer_link_id FK "nullable (admin upload)"
        string original_key UK "R2 path"
        string preview_key "R2 path con watermark"
        string thumbnail_key "R2 path"
        int width
        int height
        bigint file_size
        datetime capture_time "extraído de EXIF"
        json exif_raw
        string status "uploading | processing | pending_review | approved | rejected | deleted"
        datetime approved_at
        bool has_minors_detected
        bool has_bibs_detected
        int view_count
        int download_count
    }

    BIB {
        bigint id PK
        bigint photo_id FK
        string number "string (acepta 'A123')"
        float confidence "0..1"
        string source "ocr_paddle | ocr_easy | manual_admin | manual_user_report"
        json bbox "{x, y, w, h}"
        bool is_validated
        bool rejected
    }

    FACEEMBEDDING {
        bigint id PK
        bigint photo_id FK
        vector embedding "pgvector 512-d (InsightFace)"
        json bbox
        smallint estimated_age "nullable"
        bool is_minor "activa blur en preview"
        datetime last_matched_at
        int match_count
    }

    DATADELETIONREQUEST {
        bigint id PK
        int matched_photo_count
        int deleted_photo_count
        int deleted_embedding_count
        string status "pending | processing | completed | failed"
        string requester_ip_hash "sha256(IP) para rate-limiting"
        datetime completed_at
        text error_message
    }
```

## Convenciones

- **TimeStampedModel**: todos los modelos del dominio heredan `created_at` (auto_now_add) y `updated_at` (auto_now). No los repito en el diagrama por brevedad excepto donde son significativos.
- **`UK`**: unique constraint.
- **`FK`**: foreign key (cardinalidad indicada con `||--o{`, etc.).
- **`anonimizada`**: campos de IP se zerifican antes de guardar (último octeto en IPv4, últimos 80 bits en IPv6) — privacidad por defecto.
- **`encrypted`**: campo que pasa por `apps.core.fields.EncryptedCharField` (Fernet + clave derivada de `SECRET_KEY`).

## Decisiones de diseño relevantes

- **`User` custom desde día 1**: heredamos de `AbstractUser` (`apps.core.User`) y registramos `AUTH_USER_MODEL = "core.User"`. Migrar después es costoso.
- **`AuditLog` append-only**: el admin **no puede** editar ni borrar registros desde Django Admin. Sólo lectura.
- **`DataDeletionRequest` no guarda el embedding**: el selfie del solicitante se procesa en memoria; sólo persistimos el hash de la IP (para rate-limiting) y contadores.
- **`FaceEmbedding` con HNSW**: índice `vector_cosine_ops` con `m=16` y `ef_construction=64`. Si en el futuro pasamos de ~180k vectores, evaluamos subir `m` o ir a IVFFlat.
- **Retención escalonada** en `Event`: 4 ventanas temporales independientes (`public_until`, `searchable_until`, `archive_until`, y `permanent_archive` que las bypasea). Ver ADR 0003.
