from django.urls import path
from . import views
from .views import podwyzki_nauczyciele_view
from .views import virtual_room
from .views import zajecia_online_view
from .views import dodaj_material_po_zajeciach
from django.contrib import admin
from django.views.generic import TemplateView
from django.urls import path, include


urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="strona_glowna"),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('panel_ucznia/', views.panel_ucznia_view, name='panel_ucznia'),
    path('panel_nauczyciela/', views.panel_nauczyciela_view, name='panel_nauczyciela'),
    path('moj_plan_zajec/', views.moj_plan_zajec_view, name='moj_plan_zajec'),
    path('wybierz_godziny/', views.wybierz_godziny_view, name='wybierz_godziny'),
    path('zmien_haslo/', views.change_password_view, name='zmien_haslo'),
    path('panel_admina/', views.panel_admina_view, name='panel_admina'),
    path('zapisz_terminy/', views.zapisz_terminy_view, name='zapisz_terminy'),
    path('pobierz_terminy/', views.pobierz_terminy_view, name='pobierz_terminy'),
    path('zarezerwuj_zajecia/', views.zarezerwuj_zajecia_view, name='zarezerwuj_zajecia'),
    path('archiwum_rezerwacji/', views.archiwum_rezerwacji_view, name='archiwum_rezerwacji'),
    path('moje_rezerwacje_ucznia/', views.moje_rezerwacje_ucznia_view, name='moje_rezerwacje_ucznia'),
    path('uczen/dostepne_terminy/', views.dostepne_terminy_view, name='dostepne_terminy'),
    path('logout/', views.logout_view, name='logout'),
    path('panel_ksiegowosc/', views.panel_ksiegowosci_view, name='panel_ksiegowosc'),
    path('panel_ksiegowosc/edytuj_cene/', views.edytuj_cene_view, name='edytuj_cene'),
    path('moje_konto/', views.moje_konto_view, name='moje_konto'),
    path('ksiegowosc/cennik/', views.cennik_view, name='cennik'),
    path('ksiegowosc/wyplaty/', views.wyplaty_nauczycieli_view, name='wypłaty_nauczycieli'),
    path('ksiegowosc/podwyzki/', podwyzki_nauczyciele_view, name='podwyzki_nauczyciele'),
    path('wirtualny_pokoj/', virtual_room, name='virtual_room'),
    path('zajecia_online/<int:rezerwacja_id>/', zajecia_online_view, name='zajecia_online'),
    path('dodaj_material/<int:rezerwacja_id>/', dodaj_material_po_zajeciach, name='dodaj_material'),
    path('ping-online-status/', views.ping_online_status, name='ping_online_status'),
    path('check-online-status/<int:rezerwacja_id>/', views.check_online_status, name='check_online_status'),
    path("pobierz-plik/<int:id>/", views.pobierz_plik, name="pobierz_plik"),
    path("pobierz-material/<int:id>/", views.pobierz_material_po_zajeciach, name="pobierz_material"),
    path('zmien_haslo/', views.zmien_haslo_view, name='zmien_haslo'),
    path("public-test/", views.public_test, name="public_test"),
    path("webrtc/offer/<int:rez_id>/", views.webrtc_offer, name="webrtc_offer"),
    path("webrtc/answer/<int:rez_id>/", views.webrtc_answer, name="webrtc_answer"),
    path("", include("panel.urls")),

]
from . import views
