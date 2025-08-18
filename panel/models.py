from django.db import models
from django.contrib.auth.models import User
import secrets

class Profil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_teacher = models.BooleanField(default=False)
    numer_telefonu = models.CharField(max_length=15, blank=True, null=True)
    tytul_naukowy = models.CharField(max_length=50, blank=True, null=True)
    poziom_nauczania = models.CharField(max_length=100, blank=True, null=True)
    przedmioty = models.CharField(max_length=255, blank=True, default="")
    opis = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - profil"

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
    cena = models.DecimalField(max_digits=6, decimal_places=2)

    def __str__(self):
        return f"{self.nazwa} ({self.poziom})"


class Rezerwacja(models.Model):
    uczen = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rezerwacje_ucznia')
    nauczyciel = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rezerwacje_nauczyciela')
    termin = models.DateTimeField()
    temat = models.CharField(max_length=255)
    plik = models.FileField(upload_to='rezerwacje/', blank=True, null=True)
    material_po_zajeciach = models.FileField(upload_to='materialy/', blank=True, null=True)

    excalidraw_room_id = models.CharField(max_length=64, default=secrets.token_hex(8))
    excalidraw_room_key = models.CharField(max_length=128, default=secrets.token_hex(32))
    excalidraw_link = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"{self.uczen.username} → {self.nauczyciel.username} ({self.termin})"



class WolnyTermin(models.Model):
    nauczyciel = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.DateField()
    godzina = models.TimeField()

    def __str__(self):
        return f"{self.nauczyciel.get_full_name()} - {self.data} {self.godzina}"

class OnlineStatus(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rezerwacja = models.ForeignKey(Rezerwacja, on_delete=models.CASCADE)
    last_ping = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} online w rezerwacji {self.rezerwacja.id}"

