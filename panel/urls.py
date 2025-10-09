from django.urls import path
from django.views.generic import TemplateView
from . import views
from panel.views import strona_glowna_view
from .views import login_view
from .views import moje_konto_uczen_view
from django.contrib.auth.views import LogoutView
from .views import (
    podwyzki_nauczyciele_view,
    virtual_room,
    zajecia_online_view,
    dodaj_material_po_zajeciach,
)

urlpatterns = [
    # Strona główna (jeśli chcesz, możesz ją mieć też w projekcie)
    path("", TemplateView.as_view(template_name="index.html"), name="strona_glowna"),

    # Logowanie / rejestracja / konta
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("moje_konto/", views.moje_konto_view, name="moje_konto"),
    path("uczen/moje-konto/", moje_konto_uczen_view, name="moje_konto_uczen"),

    # Panele
    path("panel_ucznia/", views.panel_ucznia_view, name="panel_ucznia"),
    path("panel_nauczyciela/", views.panel_nauczyciela_view, name="panel_nauczyciela"),
    path("panel_admina/", views.panel_admina_view, name="panel_admina"),
    path("panel_ksiegowosc/", views.panel_ksiegowosci_view, name="panel_ksiegowosc"),
    path("panel_ksiegowosc/edytuj_cene/", views.edytuj_cene_view, name="edytuj_cene"),

    # Księgowość
    path("ksiegowosc/cennik/", views.cennik_view, name="cennik"),
    path("ksiegowosc/wyplaty/", views.wyplaty_nauczycieli_view, name="wypłaty_nauczycieli"),
    path("ksiegowosc/podwyzki/", podwyzki_nauczyciele_view, name="podwyzki_nauczyciele"),
    path("ksiegowosc/rachunki/", views.accounting_invoices_view, name="accounting_invoices"),
    path("ksiegowosc/rachunki/export.csv", views.accounting_invoices_export_csv, name="accounting_invoices_export_csv"),
    # Webhook Autopay (ustaw w panelu Autopay)
    path("webhooks/autopay/", views.autopay_webhook_view, name="autopay_webhook"),

    # Zajęcia / terminy
    path("moj_plan_zajec/", views.moj_plan_zajec_view, name="moj_plan_zajec"),
    path("wybierz_godziny/", views.wybierz_godziny_view, name="wybierz_godziny"),
    path("zapisz_terminy/", views.zapisz_terminy_view, name="zapisz_terminy"),
    path("pobierz_terminy/", views.pobierz_terminy_view, name="pobierz_terminy"),
    path("zarezerwuj_zajecia/", views.zarezerwuj_zajecia_view, name="zarezerwuj_zajecia"),
    path("archiwum_rezerwacji/", views.archiwum_rezerwacji_view, name="archiwum_rezerwacji"),
    path("moje_rezerwacje_ucznia/", views.moje_rezerwacje_ucznia_view, name="moje_rezerwacje_ucznia"),
    path("uczen/dostepne_terminy/", views.dostepne_terminy_view, name="dostepne_terminy"),

    # Wirtualny pokój i zajęcia on-line
    path("wirtualny_pokoj/", virtual_room, name="virtual_room"),
    path("zajecia_online/<int:rezerwacja_id>/", zajecia_online_view, name="zajecia_online"),
    path("dodaj_material/<int:rezerwacja_id>/", dodaj_material_po_zajeciach, name="dodaj_material"),

    # Presence + pobieranie materiałów
    path("ping-online-status/", views.ping_online_status, name="ping_online_status"),
    path("check-online-status/<int:rezerwacja_id>/", views.check_online_status, name="check_online_status"),
    path("pobierz-plik/<int:id>/", views.pobierz_plik, name="pobierz_plik"),
    path("pobierz-material/<int:id>/", views.pobierz_material_po_zajeciach, name="pobierz_material"),

    # Zmiana hasła (uwaga: zostaw TYLKO jedną trasę do zmiany hasła)
    path("zmien_haslo/", views.change_password_view, name="zmien_haslo"),
    # Jeśli korzystasz z innej funkcji, zamień na:
    # path("zmien_haslo/", views.zmien_haslo_view, name="zmien_haslo"),

    # Test
    path("public-test/", views.public_test, name="public_test"),

    # WebRTC signaling (ważne dla audio)
    path("webrtc/offer/<int:rez_id>/", views.webrtc_offer, name="webrtc_offer"),
    path("webrtc/answer/<int:rez_id>/", views.webrtc_answer, name="webrtc_answer"),
    path("webrtc/hangup/<int:rez_id>/", views.webrtc_hangup, name="webrtc_hangup"),
    path("webrtc/debug/<int:rez_id>/", views.webrtc_debug, name="webrtc_debug"),

    # Uczeń
    path("moje-rachunki/", views.student_invoices_view, name="student_invoices"),

    # Pobieranie PDF
    path("rachunki/<int:invoice_id>/pdf/", views.invoice_pdf_download_view, name="invoice_pdf"),

    path('', include('panel.urls')),

    path("test-pdf/", views.test_pdf, name="test_pdf"),



]
