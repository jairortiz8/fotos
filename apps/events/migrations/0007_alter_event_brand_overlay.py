# Generated manually — feat: template de logos SÉPTIMO x CEP (solo choices)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0006_event_reviewer_visible'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='brand_overlay',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Ninguno (watermark normal)'),
                    ('surf_city', 'Surf City (logos en las esquinas)'),
                    ('septimo_cep', 'SÉPTIMO x CEP (5 logos abajo)'),
                ],
                default='',
                help_text='Pega los logos del evento en las esquinas de abajo de cada foto. Se aplica SOLO a este evento.',
                max_length=32,
                verbose_name='logos de marca en las fotos',
            ),
        ),
    ]
