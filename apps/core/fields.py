"""Custom Django model fields para RunFoto.

EncryptedCharField — encripta el valor antes de guardar y lo desencripta al leer.
Usa Fernet (symmetric AES-128-CBC + HMAC) con clave derivada de SECRET_KEY.

Diseño:
- La clave se deriva de `SECRET_KEY` con SHA-256 + base64. Si SECRET_KEY rota,
  los datos encriptados quedan ilegibles — documentado en docs/runbook.md.
- Si el valor ya estaba en plain text (migración legacy), `from_db_value`
  lo devuelve sin tocar (fallback `InvalidToken`).
- Valores `None` y `""` se pasan sin encriptar para no romper queries
  `WHERE field IS NULL`.

Tests: `tests/core/test_encrypted_field.py`.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    """Crear instancia Fernet con clave derivada de SECRET_KEY (32 bytes)."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class EncryptedCharField(models.CharField):
    """CharField que encripta el valor en reposo.

    Limitaciones conocidas:
    - No es indexable ni buscable por contenido (encripta cada valor con
      nonce distinto). Sólo sirve para "secrets" que se leen completos
      (totp_secret, backup keys, etc.).
    - Si rotás `SECRET_KEY` perdés acceso a los datos. NO rotar sin migrar.
    """

    description = "Char field encriptado con Fernet (clave derivada de SECRET_KEY)."

    def from_db_value(
        self,
        value: str | None,
        expression: Any,
        connection: Any,
    ) -> str | None:
        if value is None:
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Fallback: legacy plain text. Lo devolvemos como vino.
            return value

    def get_prep_value(self, value: Any) -> str | None:
        if value is None or value == "":
            return value
        return _fernet().encrypt(str(value).encode()).decode()
