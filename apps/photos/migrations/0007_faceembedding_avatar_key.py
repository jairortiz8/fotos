from django.db import migrations, models


class Migration(migrations.Migration):
    """Agrega `avatar_key` a FaceEmbedding (recorte de la cara para el visor).

    Aditiva y nullable-por-default (blank=""), así que es segura de aplicar en
    caliente: las filas existentes quedan con "" (= sin avatar) hasta que el
    batch de generación las complete.
    """

    dependencies = [
        ("photos", "0006_partial_unique_original_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="faceembedding",
            name="avatar_key",
            field=models.CharField(
                blank=True, db_index=True, max_length=255, verbose_name="key del avatar"
            ),
        ),
    ]
