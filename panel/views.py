import json
import logging
log = logging.getLogger("webrtc")
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User, Group
from django.core.cache import cache
from django.views.decorators.cache import never_cache
from django.core.exceptions import PermissionDenied
from django.core.files.storage import FileSystemStorage
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
    FileResponse,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# MODELE
from .models import (
    OnlineStatus,
    Profil,
    Rezerwacja,
    WolnyTermin,
    UstawieniaPlatnosci,
)
from panel.models import PrzedmiotCennik, StawkaNauczyciela

log = logging.getLogger("webrtc")


# --- Proste testy/public ---
def public_test(request):
    return HttpResponse("PUBLIC OK")


def test_publiczny(request):
    return HttpResponse("PUBLIC OK")


def strona_glowna_view(request):
    return render(request, "index.html")


# ==========================
#       WEBRTC SIGNALING
# ==========================
def _keys(rez_id: int):
    return (f"webrtc:{rez_id}:offer", f"webrtc:{rez_id}:answer")


def _json_response(data, status=200):
    resp = JsonResponse(data, status=status, safe=isinstance(data, dict))
    # nic nie buforujemy po drodze (przeglądarka / CDN)
    resp["Cache-Control"] = "no-store"
    return resp


def _keys(rez_id: int):
    return (f"webrtc:{rez_id}:offer", f"webrtc:{rez_id}:answer")

@csrf_exempt
def webrtc_offer(request, rez_id: int):
    offer_key, answer_key = _keys(rez_id)

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            if not isinstance(data, dict) or "type" not in data or "sdp" not in data:
                return HttpResponseBadRequest("Invalid SDP payload")
            cache.set(offer_key, data, timeout=60*10)   # 10 min
            cache.delete(answer_key)                    # nowy offer kasuje stare answer
            log.info("OFFER POST rez=%s len=%s", rez_id, len(data["sdp"]))
            return JsonResponse({"ok": True})
        except Exception as e:
            log.exception("OFFER POST error rez=%s", rez_id)
            return HttpResponseBadRequest(str(e))

    if request.method == "GET":
        data = cache.get(offer_key)
        if not data:
            return HttpResponseNotFound("No offer yet")
        return JsonResponse(data)

    return HttpResponseBadRequest("Method not allowed")

@csrf_exempt
@never_cache
def webrtc_answer(request, rez_id: int):
    offer_key, answer_key = _keys(rez_id)

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            t = data.get("type")
            sdp = data.get("sdp")

            # prosta walidacja, ale NIE modyfikujemy SDP
            if t != "answer" or not isinstance(sdp, str) or not sdp.startswith("v="):
                return HttpResponseBadRequest("Invalid SDP payload")

            if not cache.get(offer_key):
                return HttpResponseNotFound("No offer to answer")

            # zapisz answer...
            cache.set(answer_key, {"type": t, "sdp": sdp}, timeout=60 * 10)

            # ✅ kluczowa linia: po przyjęciu odpowiedzi kasujemy offer,
            #    żeby watchery nie widziały w kółko "nowej" oferty
            cache.delete(offer_key)

            log.info("ANSWER POST rez=%s len=%s", rez_id, len(sdp))
            resp = JsonResponse({"ok": True})
            resp["Cache-Control"] = "no-store"
            return resp

        except Exception as e:
            log.exception("ANSWER POST error rez=%s", rez_id)
            return HttpResponseBadRequest(str(e))

    elif request.method == "GET":
        data = cache.get(answer_key)
        if not data:
            return HttpResponseNotFound("No answer yet")
        resp = JsonResponse(data)
        resp["Cache-Control"] = "no-store"
        return resp

    else:
        return HttpResponseBadRequest("Method not allowed")

@csrf_exempt
def webrtc_debug(request, rez_id: int):
    """
    GET: szybki podgląd czy Offer/Answer są zapisane w cache (i jak długie mają SDP).
    Niczego nie modyfikuje.
    """
    if request.method != "GET":
        return HttpResponseBadRequest("Method not allowed")

    offer_key, answer_key = _keys(rez_id)
    offer = cache.get(offer_key)
    answer = cache.get(answer_key)

    def _sdp_len(x):
        try:
            return len((x or {}).get("sdp", "") or "")
        except Exception:
            return 0

    data = {
        "offer": bool(offer),
        "answer": bool(answer),
        "offer_len": _sdp_len(offer),
        "answer_len": _sdp_len(answer),
        "keys": {"offer": offer_key, "answer": answer_key},
    }
    return JsonResponse(data)


# ==========================
#      POBIERANIE PLIKÓW
# ==========================
@login_required
def pobierz_plik(request, id):
    """
    Bezpieczne pobieranie materiałów lekcyjnych.
    Plik otrzyma tylko nauczyciel lub uczeń przypisany do danej rezerwacji.
    """
    rezerwacja = get_object_or_404(Rezerwacja, id=id)

    # Dostęp wyłącznie dla właściwych użytkowników
    if request.user != rezerwacja.nauczyciel and request.user != rezerwacja.uczen:
        raise Http404("Brak dostępu")

    if not rezerwacja.plik:
        raise Http404("Plik nie istnieje")

    return FileResponse(rezerwacja.plik.open("rb"), as_attachment=True)


@login_required
def pobierz_material_po_zajeciach(request, id):
    rez = get_object_or_404(Rezerwacja, id=id)

    if request.user not in (rez.nauczyciel, rez.uczen):
        raise Http404("Brak dostępu")

    if not rez.material_po_zajeciach:
        raise Http404("Plik nie istnieje")

    return FileResponse(rez.material_po_zajeciach.open("rb"), as_attachment=True)


# ==========================
#           AUTH
# ==========================
def logout_view(request):
    logout(request)
    return redirect("login")


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return render(request, "login.html", {"error": "Niepoprawny e-mail lub hasło."})

        user_auth = authenticate(request, username=user.username, password=password)
        if user_auth is not None:
            login(request, user_auth)
            if user_auth.groups.filter(name="Księgowość").exists():
                return redirect("panel_ksiegowosc")
            elif hasattr(user_auth, "profil") and user_auth.profil.is_teacher:
                return redirect("panel_nauczyciela")
            else:
                return redirect("panel_ucznia")
        else:
            return render(request, "login.html", {"error": "Niepoprawny e-mail lub hasło."})

    return render(request, "login.html")


def register_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        phone = request.POST.get("phone")

        if User.objects.filter(email=email).exists():
            return render(request, "register.html", {"error": "Ten e-mail już istnieje."})

        user = User.objects.create_user(
            username=email, email=email, password=password, first_name=first_name, last_name=last_name
        )
        Profil.objects.create(user=user, is_teacher=False, numer_telefonu=phone)
        return redirect("login")

    return render(request, "register.html")


# ==========================
#         PRESENCE
# ==========================
@csrf_exempt
@login_required
def ping_online_status(request):
    if request.method != "POST":
        return JsonResponse({"error": "Tylko POST"}, status=405)

    rezerwacja_id = request.POST.get("rezerwacja_id")
    if not rezerwacja_id:
        return JsonResponse({"error": "Brak ID rezerwacji"}, status=400)

    status, _ = OnlineStatus.objects.get_or_create(user=request.user, rezerwacja_id=rezerwacja_id)
    status.last_ping = timezone.now()
    status.save()
    return JsonResponse({"status": "ping zapisany"})


@login_required
def check_online_status(request, rezerwacja_id):
    try:
        rezerwacja = Rezerwacja.objects.get(id=rezerwacja_id)
    except Rezerwacja.DoesNotExist:
        return JsonResponse({"error": "Nie znaleziono rezerwacji"}, status=404)

    if request.user == rezerwacja.uczen:
        other_user = rezerwacja.nauczyciel
    elif request.user == rezerwacja.nauczyciel:
        other_user = rezerwacja.uczen
    else:
        return JsonResponse({"error": "Brak dostępu do tej rezerwacji"}, status=403)

    try:
        online_status = OnlineStatus.objects.get(user=other_user, rezerwacja_id=rezerwacja_id)
        is_online = (timezone.now() - online_status.last_ping).total_seconds() < 15
    except OnlineStatus.DoesNotExist:
        is_online = False

    return JsonResponse({"online": is_online})


# ==========================
#     WIDOK LEKCJI (HTML)
# ==========================
@login_required
def zajecia_online_view(request, rezerwacja_id):
    rezerwacja = get_object_or_404(Rezerwacja, id=rezerwacja_id)
    user = request.user
    teraz = timezone.now()

    # zapis linku Excalidraw przez nauczyciela
    if request.method == "POST" and user == rezerwacja.nauczyciel:
        link = request.POST.get("excalidraw_link")
        if link:
            rezerwacja.excalidraw_link = link
            rezerwacja.save()
            return redirect("zajecia_online", rezerwacja_id=rezerwacja.id)

    # Dostęp poza pokojem testowym (np. ID=1) – tylko w okienku czasu
    if rezerwacja.id != 1:
        if user == rezerwacja.uczen:
            start = rezerwacja.termin
            koniec = start + timedelta(minutes=55)
            okno_start = start - timedelta(minutes=5)
            if not (okno_start <= teraz <= koniec):
                return HttpResponseForbidden("Dostęp tylko w czasie trwania zajęć.")
        elif user != rezerwacja.nauczyciel:
            return HttpResponseForbidden("Brak dostępu do tej tablicy.")
    else:
        if user not in (rezerwacja.uczen, rezerwacja.nauczyciel):
            return HttpResponseForbidden("Brak dostępu do tej tablicy.")

    return render(
        request,
        "zajecia_online.html",
        {
            "rezerwacja": rezerwacja,
            "is_teacher": user == rezerwacja.nauczyciel,
            "room_id": f"room-{rezerwacja.id}",
        },
    )


# ==========================
#     SYNC (opcjonalne)
# ==========================
@login_required
def sync_note_changes(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)

    data = request.POST.get("data")
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "virtual_room",
        {"type": "note_sync", "message": data},
    )
    return JsonResponse({"status": "success"})


async def note_sync(event):
    message = event["message"]
    await self.send(text_data=message)  # typowy stub na potrzeby Channels Consumer


# ==========================
#        KSIĘGOWOŚĆ
# ==========================
def is_accounting(user):
    return user.groups.filter(name="Księgowość").exists()


@login_required
def podwyzki_nauczyciele_view(request):
    if not is_accounting(request.user):
        raise PermissionDenied

    nauczyciele = User.objects.filter(profil__is_teacher=True).order_by("last_name")

    if request.method == "POST":
        nauczyciel_id = request.POST.get("nauczyciel_id")
        przedmiot = request.POST.get("przedmiot")
        poziom = request.POST.get("poziom")
        nowa_stawka = request.POST.get("stawka")

        if nauczyciel_id and przedmiot and poziom and nowa_stawka:
            nauczyciel = User.objects.get(id=nauczyciel_id)
            stawka_obj, _ = StawkaNauczyciela.objects.get_or_create(
                nauczyciel=nauczyciel, przedmiot=przedmiot, poziom=poziom
            )
            stawka_obj.stawka = nowa_stawka
            stawka_obj.save()

    cennik = PrzedmiotCennik.objects.all()
    stawki = StawkaNauczyciela.objects.all()
    nauczyciele_dane = []

    for nauczyciel in nauczyciele:
        profil = nauczyciel.profil
        przedmioty = [p.strip() for p in (profil.przedmioty or "").split(",") if p.strip()]
        poziomy = [p.strip() for p in (profil.poziom_nauczania or "").split(",") if p.strip()]

        dane = []
        for przedmiot in przedmioty:
            for poziom in poziomy:
                stawka_ind = stawki.filter(
                    nauczyciel=nauczyciel, przedmiot=przedmiot, poziom=poziom
                ).first()
                stawka = (
                    stawka_ind.stawka
                    if stawka_ind
                    else (cennik.filter(nazwa=przedmiot, poziom=poziom).first() or "")
                )
                dane.append({"przedmiot": przedmiot, "poziom": poziom, "stawka": getattr(stawka, "stawka", "")})

        nauczyciele_dane.append({"nauczyciel": nauczyciel, "stawki": dane})

    return render(request, "ksiegowosc/podwyzki_nauczyciele.html", {"nauczyciele_dane": nauczyciele_dane})


@login_required
def virtual_room(request):
    return render(request, "virtual_room.html")


@require_POST
@login_required
def dodaj_material_po_zajeciach(request, rezerwacja_id):
    rezerwacja = get_object_or_404(Rezerwacja, id=rezerwacja_id)
    if request.user != rezerwacja.nauczyciel:
        return HttpResponseForbidden("Brak dostępu.")

    if "material" in request.FILES:
        rezerwacja.material_po_zajeciach = request.FILES["material"]
        rezerwacja.save()

    return redirect("moj_plan_zajec")


@login_required
def cennik_view(request):
    if not is_accounting(request.user):
        raise PermissionDenied

    if request.method == "POST":
        if "zapisz_id" in request.POST:
            try:
                przedmiot_id = int(request.POST.get("zapisz_id"))
                cena = float(request.POST.get("cena"))
                przedmiot = PrzedmiotCennik.objects.get(pk=przedmiot_id)
                przedmiot.cena = cena
                przedmiot.save()
            except Exception as e:
                log.exception("Błąd zapisu cennika")

        elif "usun_id" in request.POST:
            try:
                przedmiot_id = int(request.POST.get("usun_id"))
                PrzedmiotCennik.objects.get(pk=przedmiot_id).delete()
            except Exception as e:
                log.exception("Błąd usuwania pozycji cennika")

        elif "dodaj_przedmiot" in request.POST:
            try:
                nazwa = request.POST.get("nazwa")
                poziom = request.POST.get("poziom")
                cena = float(request.POST.get("nowa_cena"))
                PrzedmiotCennik.objects.create(nazwa=nazwa, poziom=poziom, cena=cena)
            except Exception as e:
                log.exception("Błąd dodawania pozycji cennika")

    przedmioty = PrzedmiotCennik.objects.all().order_by("nazwa", "poziom")
    return render(request, "ksiegowosc/cennik.html", {"przedmioty": przedmioty})


@login_required
def wyplaty_nauczycieli_view(request):
    if not is_accounting(request.user):
        raise PermissionDenied

    ustawienia = UstawieniaPlatnosci.objects.first()
    cena = ustawienia.cena_za_godzine if ustawienia else 100

    nauczyciele = User.objects.filter(groups__name="Nauczyciel")
    dane = []
    for nauczyciel in nauczyciele:
        liczba_zajec = Rezerwacja.objects.filter(nauczyciel=nauczyciel).count()
        do_wyplaty = liczba_zajec * cena
        dane.append(
            {
                "imie": nauczyciel.first_name,
                "nazwisko": nauczyciel.last_name,
                "liczba_zajec": liczba_zajec,
                "stawka": cena,
                "do_wyplaty": do_wyplaty,
            }
        )

    return render(request, "ksiegowosc/wyplaty_nauczycieli.html", {"nauczyciele": dane})


@login_required
def panel_nauczyciela_view(request):
    if not hasattr(request.user, "profil") or not request.user.profil.is_teacher:
        return redirect("login")
    return render(request, "panel_nauczyciela.html")


@login_required
def edytuj_cene_view(request):
    try:
        ustawienia = UstawieniaPlatnosci.objects.get(id=1)
    except UstawieniaPlatnosci.DoesNotExist:
        ustawienia = UstawieniaPlatnosci(id=1)

    if request.method == "POST":
        ustawienia.cena_za_godzine = request.POST.get("cena", "").replace(",", ".")
        ustawienia.numer_telefonu = request.POST.get("telefon")
        ustawienia.numer_konta = request.POST.get("konto")
        ustawienia.wlasciciel_konta = request.POST.get("wlasciciel")
        ustawienia.save()
        return redirect("panel_ksiegowosc")

    return render(request, "ksiegowosc/edytuj_cene.html", {"ustawienia": ustawienia})


@login_required
def moje_rezerwacje_ucznia_view(request):
    rezerwacje = Rezerwacja.objects.filter(uczen=request.user).select_related("nauczyciel")
    return render(request, "moje_rezerwacje_ucznia.html", {"rezerwacje": rezerwacje})


@login_required
def moje_konto_view(request):
    profil = request.user.profil
    user = request.user

    if request.method == "POST":
        user.first_name = request.POST.get("first_name", user.first_name)
        user.last_name = request.POST.get("last_name", user.last_name)
        profil.numer_telefonu = request.POST.get("numer_telefonu", profil.numer_telefonu)

        profil.tytul_naukowy = ",".join(request.POST.getlist("tytul_naukowy"))
        profil.poziom_nauczania = ",".join(request.POST.getlist("poziom_nauczania"))
        profil.przedmioty = ",".join(request.POST.getlist("przedmioty"))
        profil.opis = request.POST.get("opis", profil.opis)

        user.save()
        profil.save()
        return redirect("panel_nauczyciela")

    cennik = PrzedmiotCennik.objects.all().order_by("nazwa", "poziom")
    return render(request, "moje_konto.html", {"profil": profil, "user": user, "cennik": cennik})


@login_required
def dostepne_terminy_view(request):
    terminy = WolnyTermin.objects.select_related("nauczyciel").all()
    return render(request, "uczen/dostepne_terminy.html", {"terminy": terminy})


@login_required
def archiwum_rezerwacji_view(request):
    rok_tem = timezone.now() - timedelta(days=365)
    rezerwacje = (
        Rezerwacja.objects.filter(nauczyciel=request.user, termin__lt=timezone.now(), termin__gte=rok_tem)
        .select_related("uczen")
    )

    archiwum = {}
    for r in rezerwacje:
        miesiac = r.termin.strftime("%Y-%m")
        archiwum.setdefault(miesiac, {}).setdefault(r.uczen, []).append(r)

    return render(request, "nauczyciel/archiwum_rezerwacji.html", {"archiwum": archiwum})


@login_required
def panel_ucznia_view(request):
    if hasattr(request.user, "profil") and request.user.profil.is_teacher:
        return redirect("panel_nauczyciela")
    terminy = WolnyTermin.objects.all().select_related("nauczyciel")
    return render(request, "panel_ucznia.html", {"terminy": terminy})


@login_required
def zapisz_terminy_view(request):
    if request.method == "POST":
        data = json.loads(request.body)
        date_str = data.get("data")
        godziny = data.get("godziny", [])

        for godzina in godziny:
            WolnyTermin.objects.get_or_create(
                nauczyciel=request.user,
                data=datetime.strptime(date_str, "%Y-%m-%d").date(),
                godzina=datetime.strptime(godzina, "%H:%M").time(),
            )
        return JsonResponse({"status": "ok"})

    return JsonResponse({"error": "Invalid method"}, status=405)


@login_required
def stawki_nauczyciela_view(request):
    if not hasattr(request.user, "profil") or not request.user.profil.is_teacher:
        return redirect("login")
    cennik = PrzedmiotCennik.objects.all().order_by("nazwa", "poziom")
    return render(request, "stawki_nauczyciela.html", {"cennik": cennik})


@login_required
def moj_plan_zajec_view(request):
    rezerwacje = (
        Rezerwacja.objects.filter(nauczyciel=request.user, termin__gte=datetime.now()).select_related("uczen")
    )
    return render(request, "moj_plan_zajec.html", {"rezerwacje": rezerwacje})


def wybierz_godziny_view(request):
    if request.method == "POST":
        data = json.loads(request.body)
        wybrane_daty = data.get("terminy", [])

        for wpis in wybrane_daty:
            data_str = wpis.get("data")
            godziny = wpis.get("godziny", [])
            for godzina_str in godziny:
                WolnyTermin.objects.create(
                    nauczyciel=request.user,
                    data=parse_date(data_str),
                    godzina=parse_time(godzina_str),
                )
        return JsonResponse({"status": "success"})

    return render(request, "wybierz_dzien_i_godzine_w_ktorej_poprowadzisz_korepetycje.html")


@login_required
def zmien_haslo_view(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            return redirect("moje_rezerwacje_ucznia")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "zmien_haslo.html", {"form": form})


@staff_member_required
def panel_admina_view(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        email = request.POST.get("email")
        password = request.POST.get("password")
        numer_telefonu = request.POST.get("numer_telefonu")

        if User.objects.filter(username=email).exists():
            return render(request, "admin_panel.html", {"error": "Użytkownik już istnieje!"})

        user = User.objects.create_user(
            username=email, email=email, password=password, first_name=first_name, last_name=last_name
        )
        Profil.objects.create(user=user, is_teacher=True, numer_telefonu=numer_telefonu)

    nauczyciele = Profil.objects.filter(is_teacher=True)
    return render(request, "admin_panel.html", {"nauczyciele": nauczyciele})


def tylko_ksiegowosc(user):
    return user.groups.filter(name="Księgowość").exists()


@login_required
@user_passes_test(tylko_ksiegowosc)
def panel_ksiegowosci_view(request):
    ustawienia = UstawieniaPlatnosci.objects.first()
    return render(request, "ksiegowosc/panel_ksiegowosc.html", {"ustawienia": ustawienia})


@login_required
def pobierz_terminy_view(request):
    terminy = WolnyTermin.objects.filter(nauczyciel=request.user)
    lista = [{"data": t.data.strftime("%Y-%m-%d"), "godzina": t.godzina.strftime("%H:%M")} for t in terminy]
    return JsonResponse({"terminy": lista})


@login_required
def change_password_view(request):
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Hasło zostało pomyślnie zmienione.")
            return redirect("panel_nauczyciela")
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, "teacher_change_password.html", {"form": form})


@login_required
def zarezerwuj_zajecia_view(request):
    if request.method == "GET":
        termin_id = request.GET.get("termin_id")
        termin = get_object_or_404(WolnyTermin, id=termin_id)
        return render(request, "zarezerwuj_formularz.html", {"termin": termin})

    elif request.method == "POST":
        termin_id = request.POST.get("termin_id")
        temat = request.POST.get("temat")
        plik = request.FILES.get("plik")
        termin = get_object_or_404(WolnyTermin, id=termin_id)

        termin_datetime = datetime.combine(termin.data, termin.godzina)

        Rezerwacja.objects.create(
            uczen=request.user,
            nauczyciel=termin.nauczyciel,
            termin=termin_datetime,
            temat=temat,
            plik=plik,
        )
        termin.delete()
        return redirect("panel_ucznia")

    return HttpResponseRedirect("/")
