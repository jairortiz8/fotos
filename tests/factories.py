"""Factory Boy factories — placeholder para Fase 0.

Se llena en Fase 1 cuando aparezcan los modelos Event, Photo, Bib,
FaceEmbedding, PhotographerLink, etc. Ejemplo de cómo lucirá:

    import factory
    from apps.events.models import Event

    class EventFactory(factory.django.DjangoModelFactory):
        class Meta:
            model = Event

        name = factory.Sequence(lambda n: f"Evento {n}")
        slug = factory.Sequence(lambda n: f"evento-{n}")
        ...
"""

from __future__ import annotations
