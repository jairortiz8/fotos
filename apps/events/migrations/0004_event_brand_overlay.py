# Generated manually — feat: brand overlay (logos por evento) 2026-07-19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0003_event_cover_key_event_organizer_facebook_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='brand_overlay',
            field=models.CharField(
                blank=True,
                choices=[('', 'Ninguno (watermark normal)'), ('surf_city', 'Surf City (logos en las esquinas)')],
                default='',
                help_text='Pega los logos del evento en las esquinas de abajo de cada foto. Se aplica SOLO a este evento.',
                max_length=32,
                verbose_name='logos de marca en las fotos',
            ),
        ),
    ]
