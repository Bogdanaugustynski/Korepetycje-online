from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Profil, AuditLog
import json

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profil.objects.get_or_create(user=instance)
        AuditLog.objects.create(actor="system", action="create_profile", obj_type="user", obj_id=str(instance.pk),
                                details={"note": "auto-created profil for new user"})

@receiver(pre_save, sender=Profil)
def profil_pre_save(sender, instance, **kwargs):
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        old = None

    # store diff in AuditLog after save in post_save if needed
    # We'll create post_save to write the actual changes
    instance._old_instance = old

@receiver(post_save, sender=Profil)
def profil_post_save(sender, instance, created, **kwargs):
    old = getattr(instance, "_old_instance", None)
    # build a diff of changed fields
    changes = {}
    if old:
        for field in ['telefon','extra_phone','city','address_line','birth_date','guardian_name','guardian_email','guardian_phone',
                      'marketing_email','marketing_sms','gdpr_edu_consent','recording_consent','accessibility_notes','avatar']:
            old_val = getattr(old, field, None)
            new_val = getattr(instance, field, None)
            if str(old_val) != str(new_val):
                changes[field] = {"old": old_val, "new": new_val}
    else:
        # new instance -> log fields
        changes = {field: {"old": None, "new": getattr(instance, field, None)} for field in
                   ['telefon','extra_phone','city','address_line','birth_date','guardian_name','guardian_email','guardian_phone',
                    'marketing_email','marketing_sms','gdpr_edu_consent','recording_consent','accessibility_notes','avatar']}

    # create audit record
    AuditLog.objects.create(actor="system", action="update_profile" if not created else "create_profile",
                            obj_type="profil", obj_id=str(instance.pk),
                            details=changes)
