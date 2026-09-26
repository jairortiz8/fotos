"""Instagram del fotógrafo — aditiva (ADD COLUMN con default, sin backfill)."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("photographers", "0002_photographerlink_featured_image_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="photographerlink",
            name="instagram",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Usuario (@foto) o link de Instagram. Se muestra en su carpeta del álbum."
                ),
                max_length=30,
                verbose_name="Instagram del fotógrafo",
            ),
        ),
    ]
