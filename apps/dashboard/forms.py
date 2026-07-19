"""Forms del dashboard admin."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.events.models import Event, EventStatus, EventVisibility


class _DashMixin:
    """Aplica la clase CSS `rf-input` a todos los widgets de texto/select."""

    fields: dict[str, forms.Field]

    def _style_widgets(self) -> None:
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                continue
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} rf-input".strip()


class EventForm(_DashMixin, forms.ModelForm):
    """Crear / editar evento. Las fechas de retención NO se exponen en el form:
    `Event.save()` las calcula solas (90/180/365 días desde la fecha). El único
    control de retención es `permanent_archive` (mantener la galería abierta).

    Antes el form exponía `public_until`/`searchable_until`/`archive_until` como
    inputs `datetime-local`; en mobile (iPad) el selector arranca en "ahora" y un
    toque dejaba `public_until` en el pasado → la galería se cerraba sola aunque
    hubiera fotos aprobadas. Se quitaron para que no vuelva a pasar."""

    # La portada NO es el ImageField del modelo (que iba a disco efímero): es un
    # campo de subida que la vista procesa → R2 → `event.cover_key`.
    cover = forms.ImageField(
        label=_("Imagen de portada"),
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
        help_text=_("JPG o PNG. Se muestra en la home y arriba de la página del evento."),
    )

    class Meta:
        model = Event
        fields = [
            "name",
            "status",
            "date",
            "location",
            "description",
            "organizer_name",
            "organizer_instagram",
            "organizer_facebook",
            "visibility",
            "brand_overlay",
            "permanent_archive",
        ]
        # IMPORTANTE: el input HTML5 `type=date` SOLO entiende ISO (`YYYY-MM-DD`).
        # Sin un `format` explícito, Django lo renderiza con el locale `es`
        # (`d/m/Y`) y el navegador, al no poder parsearlo, deja el campo VACÍO al
        # editar — daba la sensación de que había que re-poner la fecha cada vez.
        # Forzamos el formato ISO en el render.
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 3}),
            "status": forms.Select(),
            "visibility": forms.Select(),
            "brand_overlay": forms.Select(),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["location"].required = False
        self.fields["description"].required = False
        for f in ("organizer_name", "organizer_instagram", "organizer_facebook"):
            self.fields[f].required = False
        # Estado del evento: exponemos sólo los que el admin setea a mano. "Galería
        # abierta" = público + buscable. Los automáticos (sólo búsqueda, archivado,
        # borrado) los maneja el cron de retención; si el evento YA está en uno, lo
        # incluimos para que se muestre y no se pierda al guardar.
        main = {
            EventStatus.DRAFT,
            EventStatus.UPCOMING,
            EventStatus.LIVE,
            EventStatus.PUBLIC_CLOSED,
        }
        current = self.instance.status if self.instance and self.instance.pk else None
        self.fields["status"].choices = [  # type: ignore[attr-defined]
            (s.value, s.label) for s in EventStatus if s in main or s.value == current
        ]
        self.fields["status"].help_text = _(
            "Borrador = oculto. Galería abierta = visible y buscable. Galería cerrada = solo búsqueda."
        )
        # No requerido: si no viene en el POST, clean_status usa el actual (edición)
        # o Borrador (creación). Así un form sin estado no se rompe.
        self.fields["status"].required = False
        # Los inputs HTML5 envían SIEMPRE en ISO; aceptamos ISO sin importar el locale.
        # (mypy no estrecha el tipo a DateField/DateTimeField → ignoramos attr-defined.)
        self.fields["date"].input_formats = ["%Y-%m-%d"]  # type: ignore[attr-defined]
        # La retención usa los defaults (90/180/365 días); ya NO exponemos las
        # fechas a mano (un valor en el pasado cerraba la galería sin querer). Lo
        # único configurable es "mantener la galería siempre abierta".
        self.fields["permanent_archive"].label = _("Mantener la galería siempre abierta")
        self.fields["permanent_archive"].help_text = _(
            "Ignora la regla de 90 días: la galería pública queda abierta mientras "
            "el evento esté en 'Galería abierta'."
        )
        self.fields["brand_overlay"].required = False
        self.fields["brand_overlay"].label = _("Logos en las fotos")
        self.fields["brand_overlay"].help_text = _(
            "Pega los logos del evento en las esquinas de abajo de cada foto "
            "(reemplaza la marca de agua). Solo para este evento."
        )
        self._style_widgets()

    def clean_status(self) -> str:
        status = self.cleaned_data.get("status")
        if status:
            return str(status)
        if self.instance and self.instance.pk:
            return str(self.instance.status)
        return str(EventStatus.DRAFT)


EXPIRY_CHOICES = [
    (7, _("7 días")),
    (14, _("14 días")),
    (30, _("30 días")),
    (60, _("60 días")),
    (90, _("90 días")),
]


class GenerateLinkForm(_DashMixin, forms.Form):
    """Genera un link de upload para un fotógrafo (no es ModelForm: el token se
    crea con `PhotographerLink.generate_token_and_create`)."""

    photographer_name = forms.CharField(label=_("Nombre del fotógrafo"), max_length=255)
    photographer_email = forms.EmailField(label=_("Email (opcional)"), required=False)
    photographer_phone = forms.CharField(
        label=_("Teléfono (opcional)"), max_length=20, required=False
    )
    expires_in_days = forms.TypedChoiceField(
        label=_("Expira en"), choices=EXPIRY_CHOICES, coerce=int, initial=30
    )
    photo_limit = forms.IntegerField(
        label=_("Límite de fotos (opcional)"), required=False, min_value=1
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._style_widgets()


class RejectPhotoForm(forms.Form):
    """Motivo de rechazo (opcional pero recomendado)."""

    reason = forms.CharField(
        label=_("Motivo del rechazo"),
        required=False,
        max_length=255,
        widget=forms.Textarea(
            attrs={"rows": 2, "class": "rf-input", "placeholder": _("Opcional…")}
        ),
    )


class AddBibForm(forms.Form):
    """Agregar un dorsal manual a una foto."""

    number = forms.CharField(label=_("Dorsal"), max_length=20)

    def clean_number(self) -> str:
        from apps.core.utils import normalize_bib_query

        return normalize_bib_query(self.cleaned_data["number"])


# Visibilidades expuestas en el form (todas menos las que no apliquen).
VISIBILITY_CHOICES = EventVisibility.choices
