# panel/signals.py
from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from datetime import date, datetime
from django.db.models.fields.files import FieldFile

from .models import Profil, AuditLog


def _jsonable(value):
    """Zamienia wartości na JSON-safe (dla AuditLog.details)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, FieldFile):
        return value.name or ""
    # prymitywy zostawiamy; inne rzutujemy na str
    try:
        import json
        json.dumps(value)
        return value
    except Exception:
        return str(value)


# --- AUTOMATYCZNE UTWORZENIE PROFILU DLA NOWEGO USERA ---
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profil(sender, instance, created, **kwargs):
    if created:
        Profil.objects.get_or_create(user=instance)
        AuditLog.objects.create(
            actor="system",
            action="create_profile",
            obj_type="user",
            obj_id=str(instance.pk),
            details={"note": "auto-created Profil for new user"},
        )


# --- LOGOWANIE ZMIAN PROFILU (Aron) ---
@receiver(pre_save, sender=Profil)
def profil_pre_save(sender, instance, **kwargs):
    try:
        instance._old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._old_instance = None


@receiver(post_save, sender=Profil)
def profil_post_save(sender, instance, created, **kwargs):
    old = getattr(instance, "_old_instance", None)

    # Pola zgodne z Twoim modelem Profil
    fields = [
        # Twoje bazowe:
        "is_teacher", "numer_telefonu", "tytul_naukowy", "poziom_nauczania",
        "przedmioty", "opis",
        # Rozszerzenia ucznia/opiekuna/zgody:
        "extra_phone", "city", "address_line", "birth_date",
        "guardian_name", "guardian_email", "guardian_phone",
        "marketing_email", "marketing_sms",
        "gdpr_edu_consent", "recording_consent",
        "accessibility_notes", "avatar",
    ]

    changes = {}
    if old:
        for f in fields:
            ov = getattr(old, f, None)
            nv = getattr(instance, f, None)
            # porównujemy po str, ale zapisujemy JSON-safe wartości
            if str(ov) != str(nv):
                changes[f] = {"old": _jsonable(ov), "new": _jsonable(nv)}
    else:
        for f in fields:
            changes[f] = {"old": None, "new": _jsonable(getattr(instance, f, None))}

    AuditLog.objects.create(
        actor="system",
        action="create_profile" if created else "update_profile",
        obj_type="profil",
        obj_id=str(instance.pk),
        details=changes,
    )
