from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
import secrets
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxLengthValidator
from django.contrib.auth import get_user_model

# --- upload paths ---
def avatar_upload_path(instance, filename):
    return f"avatars/{instance.user_id}/{filename}"

def invoice_upload_path(instance, filename):
    # Uwaga: przy pierwszym zapisie instance.id może być None – to w niczym nie przeszkadza.
    return f"invoices/{filename}" if instance.id is None else f"invoices/{instance.id}_{filename}"


# --- Profil / dane użytkownika ---
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
        full = self.nauczyciel.get_full_name().strip()
        name = full if full else self.nauczyciel.username
        return f"{name} – {self.przedmiot} ({self.poziom}) – {self.stawka} zł"


class UstawieniaPlatnosci(models.Model):
    # Cena: zostaje w modelu (dla innych ekranów), ale nie edytujemy jej tutaj.
    cena_za_godzine = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))]
    )
    numer_telefonu = models.CharField(max_length=32, blank=True, default="")
    numer_konta = models.CharField(max_length=64, blank=True, default="")  # IBAN/NRB
    wlasciciel_konta = models.CharField(max_length=100, blank=True, default="")
    # Pole historyczne/kompatybilność – jeśli gdzieś było używane:
    dane_odbiorcy = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"Ustawienia płatności (cena: {self.cena_za_godzine} zł)"


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
    # 8 bajtów => 16 znaków hex
    return secrets.token_hex(8)

def default_excalidraw_room_key() -> str:
    # 32 bajty => 64 znaki hex
    return secrets.token_hex(32)


class Rezerwacja(models.Model):
    uczen = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rezerwacje_ucznia')
    nauczyciel = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rezerwacje_nauczyciela')
    
    termin = models.DateTimeField()

    temat = models.CharField(max_length=255)
    plik = models.FileField(upload_to='rezerwacje/', blank=True, null=True)
    material_po_zajeciach = models.FileField(upload_to='materialy/', blank=True, null=True)
    przedmiot = models.CharField(max_length=80, blank=True, null=True)
    poziom    = models.CharField(max_length=20, blank=True, null=True)
    oplacona = models.BooleanField(default=False)
    odrzucona = models.BooleanField(default=False)
    # --- EDUKACJA (NOWE) ---
    TYP_OSOBY_CHOICES = [
        ("podstawowa", "Uczeń szkoły podstawowej"),
        ("srednia",    "Uczeń szkoły średniej"),
        ("student",    "Student uczelni wyższej"),
    ]
    typ_osoby    = models.CharField(max_length=15, choices=TYP_OSOBY_CHOICES, blank=True, null=True)
    poziom_nauki = models.CharField(max_length=30, blank=True, null=True)

    excalidraw_room_id = models.CharField(max_length=64, default=default_excalidraw_room_id)
    excalidraw_room_key = models.CharField(max_length=128, default=default_excalidraw_room_key)
    excalidraw_link = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"{self.uczen.username} → {self.nauczyciel.username} ({self.termin})"

    def save(self, *args, **kwargs):
        if not self.excalidraw_link and self.excalidraw_room_id and self.excalidraw_room_key:
            self.excalidraw_link = f"https://excalidraw.com/#room={self.excalidraw_room_id},{self.excalidraw_room_key}"
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["termin"]
        indexes = [
            models.Index(fields=["termin"]),
            models.Index(fields=["nauczyciel", "termin"]),
            models.Index(fields=["uczen", "termin"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["nauczyciel", "termin"],
                name="uniq_rez_teacher_datetime",
            ),
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


# --- Płatności i rachunki ---
class Payment(models.Model):
    reservation = models.ForeignKey("panel.Rezerwacja", on_delete=models.CASCADE, related_name="payments")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=32, default="autopay")
    provider_payment_id = models.CharField(max_length=128, unique=True)
    amount_grosz = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="PLN")
    status = models.CharField(max_length=32, default="pending")  # pending|paid|failed|refunded
    paid_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider}:{self.provider_payment_id} ({self.status})"


class Invoice(models.Model):
    number = models.CharField(max_length=64, unique=True)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices")
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="invoice")
    reservation = models.ForeignKey("panel.Rezerwacja", on_delete=models.PROTECT, related_name="invoices")
    issue_date = models.DateField()
    place = models.CharField(max_length=128, blank=True, default="")
    description = models.CharField(max_length=255)
    hours = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    rate_grosz = models.PositiveIntegerField()
    total_grosz = models.PositiveIntegerField()
    pdf = models.FileField(upload_to=invoice_upload_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number
    


class PaymentConfirmation(models.Model):
    rezerwacja = models.ForeignKey("Rezerwacja", on_delete=models.CASCADE, related_name="potwierdzenia")
    file = models.FileField(upload_to="potwierdzenia/%Y/%m/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Potwierdzenie #{self.id} rezerwacja {self.rezerwacja_id}"

class SiteLegalConfig(models.Model):
    site_owner = models.CharField(max_length=255, default="Bogdan Auguściński")
    site_address = models.CharField(max_length=255, default="Polska (miasto)")
    site_email = models.EmailField(default="polubiszto.pl@gmail.com")
    site_url = models.CharField(max_length=255, default="https://polubiszto.pl")

    # Regulamin
    payment_operator = models.CharField(
        max_length=255,
        default="Autopay oraz płatności BLIK/przelew"
    )

    # Polityka prywatności
    processors = models.CharField(
        max_length=500,
        default="hosting Render/OVH, poczta, Autopay, narzędzia analityczne bez profilowania"
    )
    cookies_desc = models.CharField(
        max_length=500,
        default="techniczne (sesja), analityczne zagregowane, preferencje interfejsu"
    )
    video_tools = models.CharField(
        max_length=500,
        default="Jitsi (audio/wideo), Excalidraw (tablica współdzielona)"
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        get_user_model(), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Konfiguracja dokumentów prawnych"
        verbose_name_plural = "Konfiguracje dokumentów prawnych"

    def __str__(self):
        return f"SiteLegalConfig #{self.pk or '∅'}"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj