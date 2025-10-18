from django.contrib import admin
from .models import Profil, WolnyTermin, Rezerwacja
from .models import Payment, Invoice
from .models import SiteLegalConfig

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

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("provider_payment_id","student","status","amount_grosz","paid_at","created_at")
    search_fields = ("provider_payment_id","student__username","student__email")
    list_filter = ("status","provider")

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number","student","issue_date","total_grosz","payment")
    search_fields = ("number","student__username","student__email")
    date_hierarchy = "issue_date"

@admin.register(SiteLegalConfig)
class SiteLegalConfigAdmin(admin.ModelAdmin):
    list_display = ("site_owner", "site_email", "updated_at", "updated_by")
    readonly_fields = ("updated_at", "updated_by")
