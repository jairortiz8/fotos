"""Forms del dashboard admin."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.events.models import Event, EventVisibility


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
    """Crear / editar evento. Las fechas de retención son opcionales: si quedan
    vacías, el `Event.save()` las calcula (90/180/365 días desde la fecha)."""

    class Meta:
        model = Event
        fields = [
            "name",
            "date",
            "location",
            "description",
            "cover_image",
            "visibility",
            "public_until",
            "searchable_until",
            "archive_until",
            "permanent_archive",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "visibility": forms.Select(),
            "public_until": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "searchable_until": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "archive_until": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["location"].required = False
        self.fields["description"].required = False
        self.fields["cover_image"].required = False
        for f in ("public_until", "searchable_until", "archive_until"):
            self.fields[f].required = False
            self.fields[f].help_text = _("Opcional. Si lo dejás vacío usamos la política estándar.")
        self._style_widgets()


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
