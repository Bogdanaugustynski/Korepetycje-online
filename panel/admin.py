from django.contrib import admin
from .models import Profil, WolnyTermin, Rezerwacja

@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'numer_telefonu')
    list_filter = ('poziom_nauczania',)

@admin.register(WolnyTermin)
class WolnyTerminAdmin(admin.ModelAdmin):
    list_display = ('nauczyciel', 'data', 'godzina')

@admin.register(Rezerwacja)
class RezerwacjaAdmin(admin.ModelAdmin):
    list_display = ('uczen', 'nauczyciel', 'termin', 'temat')
