from django.urls import path
from django.views.generic import TemplateView
from . import views
from panel.views import strona_glowna_view
from .views import login_view
from .views import moje_konto_uczen_view
from django.contrib.auth.views import LogoutView
from .views import legal_edit_config_view, regulamin_view, polityka_view
from .views import webrtc_offer, webrtc_answer, webrtc_hangup, webrtc_debug, ping_online_status, check_online_status
from .views import (
    podwyzki_nauczyciele_view,
    virtual_room,
    zajecia_online_view,
    dodaj_material_po_zajeciach,
)

urlpatterns = [
    # Strona główna (jeśli chcesz, możesz ją mieć też w projekcie)
    path("", strona_glowna_view, name="strona_glowna"),

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
    path("zarezerwuj_zajecia/", views.zarezerwuj_zajecia, name="zarezerwuj_zajecia"),
    path("archiwum_rezerwacji/", views.archiwum_rezerwacji_view, name="archiwum_rezerwacji"),
    path("moje_rezerwacje_ucznia/", views.moje_rezerwacje_ucznia_view, name="moje_rezerwacje_ucznia"),
    path("uczen/dostepne_terminy/", views.dostepne_terminy_view, name="dostepne_terminy"),

    # Wirtualny pokój i zajęcia on-line
    path("wirtualny_pokoj/", virtual_room, name="virtual_room"),
    path("zajecia_online/<int:rezerwacja_id>/", zajecia_online_view, name="zajecia_online"),
    path("dodaj_material/<int:rezerwacja_id>/", dodaj_material_po_zajeciach, name="dodaj_material"),

    # Presence + pobieranie materiałów
    path("pobierz-plik/<int:id>/", views.pobierz_plik, name="pobierz_plik"),
    path("pobierz-material/<int:id>/", views.pobierz_material, name="pobierz_material"),

    # Zmiana hasła (uwaga: zostaw TYLKO jedną trasę do zmiany hasła)
    path("zmien_haslo/", views.change_password_view, name="zmien_haslo"),
    # Jeśli korzystasz z innej funkcji, zamień na:
    # path("zmien_haslo/", views.zmien_haslo_view, name="zmien_haslo"),

    # Test
    path("public-test/", views.public_test, name="public_test"),

    # WebRTC signaling (ważne dla audio)
    path("webrtc_offer/<int:rez_id>/", webrtc_offer, name="webrtc_offer"),
    path("webrtc_answer/<int:rez_id>/", webrtc_answer, name="webrtc_answer"),
    path("webrtc_hangup/<int:rez_id>/", webrtc_hangup, name="webrtc_hangup"),
    path("webrtc_debug/<int:rez_id>/", webrtc_debug, name="webrtc_debug"),
    path("ping_online_status/", ping_online_status, name="ping_online_status"),
    path("check-online-status/<int:rezerwacja_id>/", check_online_status, name="check_online_status"),

    # Uczeń
    path("moje-rachunki/", views.student_invoices_view, name="student_invoices"),

    # Pobieranie PDF
    path("rachunki/<int:invoice_id>/pdf/", views.invoice_pdf_download_view, name="invoice_pdf"),

    path("test-pdf/", views.test_pdf, name="test_pdf"),

 # Uczeń – płatności (informacyjne)
    path("uczen/platnosci/", views.platnosci_lista_view, name="platnosci_lista"),
    path("uczen/platnosci/<int:rez_id>/", views.platnosci_view, name="platnosci_view"),

    # Księgowość – ręczna akceptacja
    path("ksiegowosc/platnosci/", views.ksiegowosc_platnosci_lista, name="ksiegowosc_platnosci_lista"),
    path("ksiegowosc/platnosci/<int:rez_id>/oplacona/", views.ksiegowosc_oznacz_oplacona, name="ksiegowosc_oznacz_oplacona"),
    path("ksiegowosc/platnosci/<int:rez_id>/odrzucona/", views.ksiegowosc_oznacz_odrzucona, name="ksiegowosc_oznacz_odrzucona"),
    path("ksiegowosc/potwierdzenie/<int:pk>/", views.confirmation_download, name="confirmation_download"),
    path("regulamin/", regulamin_view, name="regulamin"),
    path("polityka-prywatnosci/", polityka_view, name="polityka_prywatnosci"),
    # Panel Księgowości – edycja
    path("ksiegowosc/legal/", legal_edit_config_view, name="legal_edit_config"),

    #TESTY
    path("pokoj_testowy/", views.pokoj_testowy_view, name="pokoj_testowy"),
    path("strefa_ai_home/", views.strefa_ai_home_view, name="strefa_ai_home"),
    path("ai_chat/", views.ai_chat, name="ai_chat"),

    #Tablica
    path("aliboard/", views.aliboard_view, name="aliboard"),
    path("aliboard/new/", aliboard_views.aliboard_new_room, name="aliboard_new_room"),


]
