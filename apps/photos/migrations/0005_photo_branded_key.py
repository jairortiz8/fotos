from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("photos", "0004_alter_bib_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="photo",
            name="branded_key",
            field=models.CharField(
                blank=True,
                default="",
                max_length=500,
                verbose_name="key del original con logos",
            ),
        ),
    ]
