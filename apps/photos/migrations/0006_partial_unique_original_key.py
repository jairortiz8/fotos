"""UNIQUE parcial en Photo.original_key (en vez de UNIQUE total).

Contexto (incidente Surf City, 2026-07-20): `original_key` tenía `unique=True`.
Al subir una foto se crea la fila con `original_key=""` y recién tras subir a R2
se setea la key real. Una subida abandonada a mitad dejaba una fila con `""`;
como `""` ya "existía", TODA subida nueva chocaba con el UNIQUE y tiraba 500
(una foto trabada bloqueaba las subidas de todos los fotógrafos).

La solución: unicidad PARCIAL (solo `original_key <> ''`). Así conviven muchas
filas con `""` sin perder la unicidad de las keys reales.

Este cambio YA fue aplicado a mano en la BD de producción durante el incidente
(sin deploy), con el MISMO nombre de índice `uniq_original_key_nonempty`. Por eso
las operaciones de base de datos son idempotentes (`IF EXISTS` / `IF NOT EXISTS`):
en prod son no-op, y en dev/CI/tests aplican el cambio real. El estado del ORM se
actualiza vía `state_operations` para que Django no detecte drift.
"""

from __future__ import annotations

from django.db import migrations, models
from django.db.models import Q, UniqueConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("photos", "0005_photo_branded_key"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE photos_photo "
                        "DROP CONSTRAINT IF EXISTS photos_photo_original_key_key; "
                        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_original_key_nonempty "
                        "ON photos_photo (original_key) WHERE original_key <> '';"
                    ),
                    reverse_sql=(
                        "DROP INDEX IF EXISTS uniq_original_key_nonempty; "
                        "ALTER TABLE photos_photo "
                        "ADD CONSTRAINT photos_photo_original_key_key "
                        "UNIQUE (original_key);"
                    ),
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="photo",
                    name="original_key",
                    field=models.CharField(max_length=500, verbose_name="key del original"),
                ),
                migrations.AddConstraint(
                    model_name="photo",
                    constraint=UniqueConstraint(
                        fields=["original_key"],
                        condition=~Q(original_key=""),
                        name="uniq_original_key_nonempty",
                    ),
                ),
            ],
        ),
    ]
