from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
import secrets
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils import timezone

def avatar_upload_path(instance, filename):
    return f"avatars/{instance.user_id}/{filename}"


class Profil(models.Model):
    # ----- podstawowe -----
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_teacher = models.BooleanField(default=False)
    numer_telefonu = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^[0-9+\-\s()]{6,}$", "Podaj poprawny numer telefonu.")]
    )
    tytul_naukowy = models.CharField(max_length=50, blank=True, null=True)
    poziom_nauczania = models.CharField(max_length=100, blank=True, null=True)
    przedmioty = models.CharField(max_length=255, blank=True, default="")
    opis = models.TextField(blank=True, null=True)

    # ----- dane ucznia -----
    extra_phone = models.CharField("Drugi numer telefonu", max_length=32, blank=True)
    city = models.CharField("Miasto", max_length=80, blank=True)
    address_line = models.CharField("Adres", max_length=160, blank=True)
    birth_date = models.DateField("Data urodzenia", null=True, blank=True)

    # ----- dane opiekuna -----
    guardian_name = models.CharField("Imię i nazwisko opiekuna", max_length=120, blank=True)
    guardian_email = models.EmailField("E-mail opiekuna", blank=True)
    guardian_phone = models.CharField("Telefon opiekuna", max_length=32, blank=True)

    # ----- zgody i prywatność -----
    marketing_email = models.BooleanField("Zgoda na kontakt e-mail", default=False)
    marketing_sms = models.BooleanField("Zgoda na kontakt SMS", default=False)
    gdpr_edu_consent = models.BooleanField("Zgoda na przetwarzanie danych edukacyjnych", default=False)
    recording_consent = models.BooleanField("Zgoda na nagrywanie lekcji", default=False)

    accessibility_notes = models.TextField("Uwagi o potrzebach edukacyjnych", blank=True)

    # ----- plik / avatar -----
    avatar = models.ImageField("Avatar", upload_to=avatar_upload_path, blank=True, null=True)

    # ----- meta -----
    updated_at = models.DateTimeField(auto_now=True)

    # ----- helper -----
    @property
    def is_minor(self):
        """Zwraca True, jeśli uczeń ma mniej niż 18 lat."""
        if not self.birth_date:
            return None
        today = timezone.localdate()
        try:
            age = today.year - self.birth_date.year - (
                (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
            )
            return age < 18
        except Exception:
            return None

    def __str__(self):
        return f"{self.user.username} - profil"
    
class AuditLog(models.Model):
    """
    Aron: zapis akcji zmian modelu/profilu/wdrożeń - audyt dla Arona.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actor = models.CharField(max_length=120, blank=True)  # np. 'system', 'Aron', 'Noa'
    action = models.CharField(max_length=120)  # e.g. "update_profile", "create_profile", "deploy"
    obj_type = models.CharField(max_length=80, blank=True)
    obj_id = models.CharField(max_length=80, blank=True)
    details = models.JSONField(blank=True, null=True)  # strukturalne dane o zmianie
    created_by_ip = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"{self.created_at.isoformat()} {self.action} {self.obj_type}:{self.obj_id}"

class StawkaNauczyciela(models.Model):
    nauczyciel = models.ForeignKey(User, on_delete=models.CASCADE)
    przedmiot = models.CharField(max_length=100)
    poziom = models.CharField(max_length=20, choices=[("podstawowy", "Podstawowy"), ("rozszerzony", "Rozszerzony")])
    stawka = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        unique_together = ('nauczyciel', 'przedmiot', 'poziom')

    def __str__(self):
        return f"{self.nauczyciel.get_full_name()} – {self.przedmiot} ({self.poziom}) – {self.stawka} zł"

class UstawieniaPlatnosci(models.Model):
    cena_za_godzine = models.DecimalField(max_digits=6, decimal_places=2)
    numer_telefonu = models.CharField(max_length=20)
    numer_konta = models.CharField(max_length=50)
    dane_odbiorcy = models.CharField(max_length=100, blank=True, null=True)
    wlasciciel_konta = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Ustawienia płatności: {self.cena_za_godzine} zł"

class Księgowość(models.Model):
    nazwa = models.CharField(max_length=100, default="Panel Księgowości")

    class Meta:
        permissions = [
            ("can_view_ksiegowosc", "Może przeglądać panel księgowości"),
        ]

    def __str__(self):
        return self.nazwa

class PrzedmiotCennik(models.Model):
    POZIOMY = (
        ('podstawowy', 'Podstawowy'),
        ('rozszerzony', 'Rozszerzony'),
    )

    nazwa = models.CharField(max_length=100)
    poziom = models.CharField(max_length=20, choices=POZIOMY)
    cena = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Cena nauczyciela [zł/h]"
    )
    cena_uczen = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Cena dla ucznia [zł/h]"
    )

    class Meta:
        unique_together = ("nazwa", "poziom")
        verbose_name = "Przedmiot w cenniku"
        verbose_name_plural = "Cennik przedmiotów"

    def __str__(self):
        return f"{self.nazwa} ({self.poziom})"


# --- Pomocnicze: bezpieczne, migracje-serializowalne defaulty ---
def default_excalidraw_room_id() -> str:
    # 8 bajtów => 16 znaków hex, stabilnie i krótko
    return secrets.token_hex(8)

def default_excalidraw_room_key() -> str:
    # 32 bajty => 64 znaki hex (klucz do pokoju)
    return secrets.token_hex(32)


class Rezerwacja(models.Model):
    uczen = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rezerwacje_ucznia')
    nauczyciel = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rezerwacje_nauczyciela')

    # U Ciebie to DateTimeField (bez FK) — zostawiamy, ale zabezpieczamy unikalność
    termin = models.DateTimeField()

    temat = models.CharField(max_length=255)
    plik = models.FileField(upload_to='rezerwacje/', blank=True, null=True)
    material_po_zajeciach = models.FileField(upload_to='materialy/', blank=True, null=True)

    # UWAGA: defaulty muszą być CALLABLE, nie wywołane przy imporcie!
    excalidraw_room_id = models.CharField(max_length=64, default=default_excalidraw_room_id)
    excalidraw_room_key = models.CharField(max_length=128, default=default_excalidraw_room_key)
    excalidraw_link = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"{self.uczen.username} → {self.nauczyciel.username} ({self.termin})"

    def save(self, *args, **kwargs):
        # Zbuduj link Excalidraw jeśli brak
        if not self.excalidraw_link and self.excalidraw_room_id and self.excalidraw_room_key:
            self.excalidraw_link = f"https://excalidraw.com/#room={self.excalidraw_room_id},{self.excalidraw_room_key}"
        super().save(*args, **kwargs)

    class Meta:
        # Chronologia od najbliższych (backendowo też porządkujemy)
        ordering = ["termin"]
        indexes = [
            models.Index(fields=["termin"]),
            models.Index(fields=["nauczyciel", "termin"]),
            models.Index(fields=["uczen", "termin"]),
        ]
        constraints = [
            # Kluczowa blokada duplikatów: jeden nauczyciel nie może mieć 2 rezerwacji na tę samą chwilę
            models.UniqueConstraint(
                fields=["nauczyciel", "termin"],
                name="uniq_rez_teacher_datetime",
            ),
            # (opcjonalnie) zablokuj uczniowi nakładanie rezerwacji co do sekundy:
            # models.UniqueConstraint(fields=["uczen", "termin"], name="uniq_rez_student_datetime"),
            # (opcjonalnie, jeśli chcesz wymusić rezerwacje tylko w przyszłości — raczej NIE na stałe,
            # bo przeszłe rezerwacje są przydatne do archiwum):
            # models.CheckConstraint(check=models.Q(termin__gte=Now()), name="rez_termin_not_past"),
        ]


class WolnyTermin(models.Model):
    nauczyciel = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.DateField()
    godzina = models.TimeField()

    def __str__(self):
        full = self.nauczyciel.get_full_name().strip()
        name = full if full else self.nauczyciel.username
        return f"{name} - {self.data} {self.godzina}"

    class Meta:
        ordering = ["data", "godzina"]
        indexes = [
            models.Index(fields=["data", "godzina"]),
            models.Index(fields=["nauczyciel", "data", "godzina"]),
        ]
        constraints = [
            # Unikalny slot w grafiku nauczyciela — tu kończymy z duplikatami
            models.UniqueConstraint(
                fields=["nauczyciel", "data", "godzina"],
                name="uniq_slot_teacher_date_time",
            ),
        ]

class OnlineStatus(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rezerwacja = models.ForeignKey(Rezerwacja, on_delete=models.CASCADE)
    last_ping = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} online w rezerwacji {self.rezerwacja.id}"

