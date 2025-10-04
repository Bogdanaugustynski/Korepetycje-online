import json
import logging
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User, Group
from django.core.cache import cache
from django.views.decorators.cache import never_cache
from django.core.exceptions import PermissionDenied 
from django.contrib.auth import authenticate, login, logout, get_user_model
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
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.apps import apps
from django.db.models import Exists, OuterRef, ForeignKey
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.urls import reverse
from django.db import transaction, models
from django.db.models import Q
import re

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


# --- STRONA GŁÓWNA (lista tylko nauczycieli: profil.is_teacher=True) ---
from django.contrib.auth.models import User
from django.shortcuts import render

def strona_glowna_view(request):
    # Pobierz aktywnych użytkowników z ustawionym profilem nauczyciela
    qs = (
        User.objects
        .filter(is_active=True, profil__is_teacher=True)
        .select_related("profil")
        .order_by("last_name", "first_name")
    )

    nauczyciele = []
    for u in qs:
        profil = getattr(u, "profil", None)

        # Bezpieczne pobranie zdjęcia (obsługa różnych nazw pól i FileField/URL/str)
        photo_url = ""
        if profil:
            for field_name in ("zdjecie", "photo", "avatar", "photo_url"):
                val = getattr(profil, field_name, "")
                if val:
                    try:
                        photo_url = val.url  # jeśli to FileField/ImageField
                    except Exception:
                        photo_url = str(val)  # jeśli to zwykły string/URL
                    if photo_url:
                        break

        # Tagowanie (np. przedmioty / poziomy / tytuły) – złączone i odfiltrowane duplikaty
        raw_tags = []
        if profil:
            for src in ("przedmioty", "poziom_nauczania", "tytul_naukowy"):
                s = getattr(profil, src, "") or ""
                if s:
                    raw_tags.extend([t.strip() for t in s.split(",") if t.strip()])
        # unikalne z zachowaniem kolejności, max 6
        seen = set()
        tag_list = []
        for t in raw_tags:
            if t not in seen:
                seen.add(t)
                tag_list.append(t)
            if len(tag_list) >= 6:
                break

        nauczyciele.append({
            "full_name": (f"{u.first_name} {u.last_name}".strip() or u.username).strip(),
            "bio": getattr(profil, "opis", "") if profil else "",
            "photo_url": photo_url,
            "tag_list": tag_list,
            "default_avatar": "https://placehold.co/72x72",
        })

    return render(request, "index.html", {
        "nauczyciele": nauczyciele
    })



# ==========================
#       WEBRTC SIGNALING
# ==========================
# ====== Klucze w cache ======
def _keys(rez_id: int):
    """
    Zestaw kluczy powiązanych z jedną sesją (rezerwacją):
    - offer / answer: ładunki SDP
    - lock: kto został offererem (anti-race)
    """
    base = f"webrtc:{rez_id}"
    return {
        "offer": f"{base}:offer",
        "answer": f"{base}:answer",
        "lock": f"{base}:lock",
    }

# Stałe czasowe
OFFER_TTL = 60 * 10   # 10 min
ANSWER_TTL = 60 * 10  # 10 min
LOCK_TTL  = 60 * 2    # 2 min – wystarczy, żeby student zdążył odebrać

def _no_store(resp: JsonResponse) -> JsonResponse:
    resp["Cache-Control"] = "no-store"
    return resp

# ====== OFFER ======
@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def webrtc_offer(request, rez_id: int):
    keys = _keys(rez_id)
    offer_key = keys["offer"]
    answer_key = keys["answer"]
    lock_key = keys["lock"]

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            if not isinstance(data, dict) or data.get("type") != "offer" or not isinstance(data.get("sdp"), str):
                return HttpResponseBadRequest("Invalid SDP payload")

            # Kto pierwszy – ten offerer (SETNX = cache.add)
            user_id = getattr(getattr(request, "user", None), "id", None) or "anon"
            claimed = cache.add(lock_key, str(user_id), timeout=LOCK_TTL)
            current_locker = cache.get(lock_key)

            # Jeżeli lock istnieje i nie my go trzymamy – ktoś już dzwoni
            if not claimed and str(current_locker) != str(user_id):
                log.info("OFFER POST blocked by lock rez=%s by=%s", rez_id, current_locker)
                return JsonResponse({"error": "Offerer already set"}, status=409)

            # Zapisz offer (najnowszy nadpisuje stary); answer czyścimy
            cache.set(offer_key, {"type": "offer", "sdp": data["sdp"]}, timeout=OFFER_TTL)
            cache.delete(answer_key)

            log.info("OFFER POST rez=%s len=%s by=%s", rez_id, len(data["sdp"]), user_id)
            return _no_store(JsonResponse({"ok": True}))
        except Exception as e:
            log.exception("OFFER POST error rez=%s", rez_id)
            return HttpResponseBadRequest(str(e))

    # GET
    data = cache.get(offer_key)
    if not data:
        return HttpResponseNotFound("No offer yet")
    return _no_store(JsonResponse(data))

# ====== ANSWER ======
@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def webrtc_answer(request, rez_id: int):
    keys = _keys(rez_id)
    offer_key = keys["offer"]
    answer_key = keys["answer"]

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            t = data.get("type")
            sdp = data.get("sdp")

            # Walidacja odpowiedzi
            if t != "answer" or not isinstance(sdp, str) or not sdp.startswith("v="):
                return HttpResponseBadRequest("Invalid SDP payload")

            # Odpowiadać można tylko na istniejącą ofertę
            if not cache.get(offer_key):
                return HttpResponseNotFound("No offer to answer")

            cache.set(answer_key, {"type": "answer", "sdp": sdp}, timeout=ANSWER_TTL)
            # Po przyjęciu answer kasujemy offer, by watchery nie „dzwoniły” w kółko
            cache.delete(offer_key)

            log.info("ANSWER POST rez=%s len=%s", rez_id, len(sdp))
            return _no_store(JsonResponse({"ok": True}))
        except Exception as e:
            log.exception("ANSWER POST error rez=%s", rez_id)
            return HttpResponseBadRequest(str(e))

    # GET
    data = cache.get(answer_key)
    if not data:
        return HttpResponseNotFound("No answer yet")
    return _no_store(JsonResponse(data))

# ====== HANGUP (sprzątanie stanu) ======
@csrf_exempt
@never_cache
@require_POST
def webrtc_hangup(request, rez_id: int):
    keys = _keys(rez_id)
    cache.delete_many([keys["offer"], keys["answer"], keys["lock"]])
    log.info("HANGUP rez=%s – cleared offer/answer/lock", rez_id)
    return _no_store(JsonResponse({"ok": True}))

# ====== DEBUG (podgląd kluczy) ======
@csrf_exempt
@never_cache
@require_GET
def webrtc_debug(request, rez_id: int):
    keys = _keys(rez_id)
    offer = cache.get(keys["offer"])
    answer = cache.get(keys["answer"])
    locker = cache.get(keys["lock"])

    def _sdp_len(x):
        try:
            return len((x or {}).get("sdp", "") or "")
        except Exception:
            return 0

    data = {
        "keys": keys,
        "offer": bool(offer),
        "answer": bool(answer),
        "offer_len": _sdp_len(offer),
        "answer_len": _sdp_len(answer),
        "lock_holder": locker,
    }
    return _no_store(JsonResponse(data))


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


User = get_user_model()

def login_view(request):
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        remember = request.POST.get("remember")

        # Szukaj po e-mailu case-insensitive (uniknij DoesNotExist/MultipleObjects)
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return render(request, "login.html", {"error": "Niepoprawny e-mail lub hasło."})

        if not user.is_active:
            return render(request, "login.html", {"error": "Konto jest nieaktywne. Skontaktuj się z administratorem."})

        user_auth = authenticate(request, username=user.username, password=password)
        if user_auth is None:
            return render(request, "login.html", {"error": "Niepoprawny e-mail lub hasło."})

        # Logowanie OK
        login(request, user_auth)

        # „Zapamiętaj mnie”: jeśli zaznaczone, sesja wg SESSION_COOKIE_AGE; jeśli nie, do zamknięcia przeglądarki
        if remember:
            request.session.set_expiry(None)   # domyślnie np. 1209600 s (14 dni) — ustaw w settings.SESSION_COOKIE_AGE
        else:
            request.session.set_expiry(0)

        # Priorytet dla ?next=..., inaczej Twoje role jak dotąd
        next_url = request.GET.get("next")
        if next_url:
            return redirect(next_url)

        if user_auth.groups.filter(name="Księgowość").exists():
            return redirect("panel_ksiegowosc")
        elif hasattr(user_auth, "profil") and getattr(user_auth.profil, "is_teacher", False):
            return redirect("panel_nauczyciela")
        else:
            return redirect("panel_ucznia")

    # GET
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
@login_required
@never_cache
@require_POST
def ping_online_status(request):
    rezerwacja_id = request.POST.get("rezerwacja_id")
    if not rezerwacja_id:
        return JsonResponse({"error": "Brak ID rezerwacji"}, status=400)

    status, _ = OnlineStatus.objects.get_or_create(user=request.user, rezerwacja_id=rezerwacja_id)
    status.last_ping = timezone.now()
    status.save()
    return _no_store(JsonResponse({"status": "ping zapisany"}))

@login_required
@never_cache
@require_GET
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
        return HttpResponseForbidden("Brak dostępu do tej rezerwacji")

    try:
        online_status = OnlineStatus.objects.get(user=other_user, rezerwacja_id=rezerwacja_id)
        is_online = (timezone.now() - online_status.last_ping).total_seconds() < 20
    except OnlineStatus.DoesNotExist:
        is_online = False

    return _no_store(JsonResponse({"online": is_online}))


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


def _range_for_scope(now, scope: str):
    if scope == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if scope == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7)
    if scope == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        tmp = (start.replace(day=28) + timedelta(days=4))
        end = tmp.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, end
    return None, None  # all

@login_required
def moje_rezerwacje_ucznia_view(request):
    scope = request.GET.get("scope", "all")
    if scope not in {"day", "week", "month", "all"}: scope = "all"

    now = timezone.localtime()

    base = (
        Rezerwacja.objects
        .filter(uczen=request.user)
        .select_related("nauczyciel")
    )

    start, end = _range_for_scope(now, scope)
    if start is not None and end is not None:
        base = base.filter(termin__gte=start, termin__lt=end)

    # Rozbicie jak w panelu: upcoming ↑, finished ↓
    upcoming = base.filter(termin__gte=now).order_by("termin")
    finished = base.filter(termin__lt=now).order_by("-termin")

    return render(request, "moje_rezerwacje_ucznia.html", {
        "scope": scope,
        "upcoming": upcoming,
        "finished": finished,
        # (opcjonalnie) zgodność wstecz:
        "rezerwacje": base.order_by("termin"),
    })


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

@transaction.atomic
def zarezerwuj_zajecia(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Nieprawidłowa metoda")

    termin_txt = request.POST.get("termin", "").strip()  # "YYYY-MM-DD HH:MM"
    nauczyciel_id = request.POST.get("nauczyciel_id")
    termin_id = request.POST.get("termin_id")  # jeśli masz FK do WolnyTermin
    temat = request.POST.get("temat", "").strip()
    plik = request.FILES.get("plik")

    if not (termin_txt and nauczyciel_id and temat):
        return HttpResponseBadRequest("Brak danych")

    # Parsowanie daty/godziny z termin_txt
    try:
        data_str, godz_str = termin_txt.split(" ")
    except ValueError:
        return HttpResponseBadRequest("Zły format terminu")

    from datetime import datetime
    try:
        data = datetime.strptime(data_str, "%Y-%m-%d").date()
        godzina = datetime.strptime(godz_str, "%H:%M").time()
    except ValueError:
        return HttpResponseBadRequest("Zły format daty/godziny")

    now = timezone.localtime()
    if (data < now.date()) or (data == now.date() and godzina < now.time()):
        return HttpResponseBadRequest("Nie można rezerwować przeszłych terminów")

    User = apps.get_model("auth", "User")
    Rezerwacja = apps.get_model("panel", "Rezerwacja")
    WolnyTermin = apps.get_model("panel", "WolnyTermin")

    # 1) Jeżeli używasz FK do WolnyTermin:
    if termin_id:
        try:
            slot = (WolnyTermin.objects
                    .select_for_update()
                    .select_related("nauczyciel")
                    .get(id=termin_id, nauczyciel_id=nauczyciel_id, data=data, godzina=godzina))
        except WolnyTermin.DoesNotExist:
            return HttpResponseBadRequest("Termin nie istnieje")

        # Próba założenia rezerwacji – w połączeniu z UniqueConstraint przebija duplikaty
        obj, created = Rezerwacja.objects.get_or_create(
            # jeśli masz pole termin=FK:
            # termin=slot,
            # a jeśli masz termin=DateTimeField:
            nauczyciel=slot.nauczyciel,
            termin=timezone.make_aware(datetime.combine(data, godzina)),
            defaults={
                "uczen": request.user,
                "temat": temat,
                "plik": plik,
            }
        )
        if not created:
            return HttpResponseBadRequest("Ten termin jest już zarezerwowany")

    else:
        # 2) Jeżeli NIE masz FK – pilnuj unikalności (nauczyciel, termin[DT])
        nauczyciel = User.objects.get(id=nauczyciel_id)
        when_dt = timezone.make_aware(datetime.combine(data, godzina))

        obj, created = Rezerwacja.objects.get_or_create(
            nauczyciel=nauczyciel,
            termin=when_dt,
            defaults={
                "uczen": request.user,
                "temat": temat,
                "plik": plik,
            }
        )
        if not created:
            return HttpResponseBadRequest("Ten termin jest już zarezerwowany")

    # OK → przekierowanie (np. do „Moje rezerwacje”)
    return HttpResponseRedirect(reverse("moje_rezerwacje"))

def _subject_levels_from_profile(nauczyciel):
    """
    Czyta profil.przedmioty (lista stringów jak 'Matematyka - podstawowy')
    i buduje słownik: {"Matematyka": ["podstawowy","rozszerzony"], ...}.
    Obsługuje przypadek, gdy dane są stringiem (po przecinku/nowej linii).
    """
    result = {}

    profil = getattr(nauczyciel, "profil", None)
    raw = getattr(profil, "przedmioty", None)
    if not raw:
        return result

    # Ujednolicenie do listy stringów
    if isinstance(raw, str):
        # rozdziel po przecinkach lub liniach
        items = [x.strip() for x in re.split(r"[\n,]+", raw) if x.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        # np. QuerySet lub inne — spróbuj iterować
        try:
            items = [str(x).strip() for x in raw if str(x).strip()]
        except Exception:
            items = []

    for item in items:
        # formatu "Nazwa - poziom" / "Nazwa – poziom"
        parts = re.split(r"\s*[-–]\s*", item, maxsplit=1)
        subject = (parts[0] if parts else "").strip() or "Ogólne"
        level = (parts[1] if len(parts) > 1 else "").strip()
        result.setdefault(subject, set())
        if level:
            result[subject].add(level)

    # zamień sety na posortowane listy
    return {s: sorted(list(levels)) for s, levels in result.items()}


# --- (Awaryjny) HELPER: z modeli tabelarycznych (np. StawkaNauczyciela) ---
def _subject_levels_from_table(nauczyciel):
    """
    Próbuje odczytać przedmiot/poziom z panel.StawkaNauczyciela lub panel.NauczycielPrzedmiot.
    Działa nawet, gdy FK 'nauczyciel' wskazuje na profil lub Usera (próbuje kilku wariantów).
    """
    def collect(model_label):
        try:
            M = apps.get_model("panel", model_label)
        except LookupError:
            return {}

        field_names = {f.name for f in M._meta.get_fields()}
        if not {"nauczyciel", "przedmiot", "poziom"} <= field_names:
            return {}

        fk = M._meta.get_field("nauczyciel")
        target = getattr(fk.remote_field, "model", None)

        filters = []
        # Najpierw po obiekcie
        filters.append({"nauczyciel": nauczyciel})
        # Po id nauczyciela
        if hasattr(nauczyciel, "id"):
            filters.append({"nauczyciel_id": nauczyciel.id})
        # Po profilu, jeśli FK nie jest do Usera
        profil = getattr(nauczyciel, "profil", None)
        if profil is not None:
            filters.append({"nauczyciel": profil})
            if hasattr(profil, "id"):
                filters.append({"nauczyciel_id": profil.id})

        rows = []
        for f in filters:
            try:
                qs = M.objects.filter(**f).values("przedmiot", "poziom")
                if qs.exists():
                    rows = list(qs)
                    break
            except Exception:
                continue

        out = {}
        for r in rows:
            s = (r.get("przedmiot") or "").strip() or "Ogólne"
            l = (r.get("poziom") or "").strip()
            out.setdefault(s, set())
            if l:
                out[s].add(l)
        return {k: sorted(list(v)) for k, v in out.items()}

    # Najpierw StawkaNauczyciela, potem alternatywny model
    data = collect("StawkaNauczyciela")
    if not data:
        data = collect("NauczycielPrzedmiot")
    return data


@login_required
def dostepne_terminy_view(request):
    """
    Lista dostępnych terminów (tylko przyszłość, sort, wykluczenie zajętych)
    + wierszowa informacja o PRZEDMIOCIE i POZIOMIE z panelu 'Moje konto'.
    W kolumnie:
      - jeśli nauczyciel ma 1 przedmiot → pokazujemy nazwę przedmiotu, a dla poziomu:
          * 1 poziom → tekst,
          * >1 poziom → select.
      - jeśli ma >1 przedmiot → pokażemy select PRZEDMIOT, a POZIOM zależny od wyboru.
    """
    now = timezone.localtime()

    terminy_qs = (
        WolnyTermin.objects
        .select_related("nauczyciel")
        .filter(
            models.Q(data__gt=now.date()) |
            models.Q(data=now.date(), godzina__gte=now.time())
        )
        .order_by("data", "godzina")
    )

    # Wyklucz zajęte (obsługa FK / DateTimeField)
    try:
        Rezerwacja = apps.get_model("panel", "Rezerwacja")
    except LookupError:
        Rezerwacja = None

    if Rezerwacja:
        try:
            pole = Rezerwacja._meta.get_field("termin")
        except Exception:
            pole = None

        if isinstance(pole, ForeignKey) and getattr(pole.remote_field, "model", None) is WolnyTermin:
            terminy_qs = terminy_qs.exclude(
                Exists(Rezerwacja.objects.filter(termin_id=OuterRef("id")))
            )
        else:
            terminy_qs = terminy_qs.exclude(
                Exists(
                    Rezerwacja.objects.filter(
                        nauczyciel=OuterRef("nauczyciel"),
                        termin__date=OuterRef("data"),
                        termin__time=OuterRef("godzina"),
                    )
                )
            )

    terminy = list(terminy_qs)

    # Dla każdego nauczyciela: najpierw dane z profilu, jeśli brak — tabela
    for t in terminy:
        subj_map = _subject_levels_from_profile(t.nauczyciel)
        if not subj_map:
            subj_map = _subject_levels_from_table(t.nauczyciel)
        if not subj_map:
            subj_map = {"Ogólne": []}
        # przekaż do szablonu
        t.subj_levels_json = json.dumps(
            [{"przedmiot": s, "levels": lvls} for s, lvls in subj_map.items()],
            ensure_ascii=False
        )

    return render(request, "uczen/dostepne_terminy.html", {"terminy": terminy})

@require_POST
@login_required
@transaction.atomic
def dodaj_wolny_termin(request):
    """
    Dodaje wolny termin dla zalogowanego nauczyciela.
    Idempotentnie: używa get_or_create(nauczyciel, data, godzina).
    """
    if not request.user.is_staff and not request.user.groups.filter(name="nauczyciele").exists():
        return HttpResponseBadRequest("Brak uprawnień")

    data_str = (request.POST.get("data") or "").strip()        # "YYYY-MM-DD"
    godzina_str = (request.POST.get("godzina") or "").strip()  # "HH:MM"

    if not data_str or not godzina_str:
        return HttpResponseBadRequest("Podaj datę i godzinę")

    # parsowanie
    try:
        data = datetime.strptime(data_str, "%Y-%m-%d").date()
        godzina = datetime.strptime(godzina_str, "%H:%M").time()
    except ValueError:
        return HttpResponseBadRequest("Zły format daty/godziny")

    # najważniejsze: idempotencja
    obj, created = WolnyTermin.objects.get_or_create(
        nauczyciel=request.user,
        data=data,
        godzina=godzina,
    )

    # jeśli wywołujesz to fetch’em, możesz zwracać JSON:
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "created": created, "id": obj.id})

    # albo zwykłe przekierowanie po sukcesie
    return HttpResponseRedirect(reverse("panel_nauczyciela_kalendarz"))

@require_POST
@login_required
@transaction.atomic
def dodaj_wiele_wolnych_terminow(request):
    # zakładamy że przyszły listy: data[] i godzina[]
    datas = request.POST.getlist("data[]")      # ["2025-10-05", "2025-10-06", ...]
    godziny = request.POST.getlist("godzina[]") # ["10:00", "11:00", ...]
    slots = set()

    for d in datas:
        for g in godziny:
            try:
                dt = datetime.strptime(d, "%Y-%m-%d").date()
                tm = datetime.strptime(g, "%H:%M").time()
            except ValueError:
                continue
            slots.add((dt, tm))

    objs = [
        WolnyTermin(nauczyciel=request.user, data=dt, godzina=tm)
        for (dt, tm) in slots
    ]
    # klucz: brak duplikatów nawet gdy formularz wyśle się 2x
    WolnyTermin.objects.bulk_create(objs, ignore_conflicts=True)

    return JsonResponse({"ok": True, "added": len(objs)})

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
    now = timezone.localtime()
    scope = request.GET.get("scope", "all")  # "day" | "week" | "all"

    qs = (Rezerwacja.objects
          .filter(nauczyciel=request.user)
          .select_related("uczen")
          .order_by("termin"))

    # Zakresy
    if scope == "day":
        start_d = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_d = start_d + timedelta(days=1)
        qs = qs.filter(termin__gte=start_d, termin__lt=end_d)
    elif scope == "week":
        weekday = now.weekday()  # 0=Mon
        week_start = (now - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)
        qs = qs.filter(termin__gte=week_start, termin__lt=week_end)

    # Wzbogacenie + podział na listy
    upcoming, finished = [], []
    for r in qs:
        start = timezone.localtime(r.termin)
        end = start + timedelta(minutes=55)
        is_past = now > end
        status = "Zakończone" if is_past else ("Trwa" if start <= now <= end else "Nadchodzące")
        item = {
            "obj": r,
            "start": start,
            "end": end,
            "is_past": is_past,
            "status": status,
        }
        (finished if is_past else upcoming).append(item)

    # sortowanie: nadchodzące rosnąco, zakończone malejąco
    upcoming.sort(key=lambda x: x["start"])
    finished.sort(key=lambda x: x["start"], reverse=True)

    ctx = {
        "upcoming": upcoming,
        "finished": finished,
        "now": now,
        "scope": scope,
    }
    return render(request, "moj_plan_zajec.html", ctx)


def _is_future(d, t):
    now = timezone.localtime()
    dt = timezone.make_aware(datetime.combine(d, t), now.tzinfo)
    return dt >= now

@ensure_csrf_cookie                 # ustawi cookie CSRF na GET
@login_required
@transaction.atomic
def wybierz_godziny_view(request):
    if request.method == "GET":
        # To jest ta strona „Wybierz dzień i godzinę…”
        return render(request, "wybierz_dzien_i_godzine_w_ktorej_poprowadzisz_korepetycje.html")

    if request.method != "POST":
        return HttpResponseBadRequest("Niedozwolona metoda")

    # --- POST JSON z kalendarza ---
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Błąd JSON: {e}"}, status=400)

    items = payload.get("terminy", [])
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "Pole 'terminy' musi być listą."}, status=400)

    nauczyciel = request.user
    to_create, skipped = [], []

    for it in items:
        d = parse_date((it.get("data") or "").strip())
        if not d:
            skipped.append({"data": it.get("data"), "powod": "zły format daty"})
            continue
        for g_str in it.get("godziny") or []:
            t = parse_time((g_str or "").strip())
            if not t:
                skipped.append({"data": it.get("data"), "godzina": g_str, "powod": "zły format godziny"})
                continue
            if not _is_future(d, t):
                skipped.append({"data": it.get("data"), "godzina": g_str, "powod": "przeszłość"})
                continue
            to_create.append(WolnyTermin(nauczyciel=nauczyciel, data=d, godzina=t))

    created = WolnyTermin.objects.bulk_create(to_create, ignore_conflicts=True)
    return JsonResponse({"ok": True, "created": len(created), "skipped": len(skipped), "details": skipped})


@login_required
@ensure_csrf_cookie     # upewnia się, że przeglądarka ma cookie CSRF dla kolejnych fetchy
@require_http_methods(["GET"])
def pobierz_terminy_view(request):
    """Zwraca tylko przyszłe sloty zalogowanego nauczyciela, posortowane."""
    now = timezone.localtime()
    qs = (WolnyTermin.objects
          .filter(nauczyciel=request.user)
          .filter(Q(data__gt=now.date()) | Q(data=now.date(), godzina__gte=now.time()))
          .order_by("data", "godzina"))
    out = [{"data": w.data.strftime("%Y-%m-%d"), "godzina": w.godzina.strftime("%H:%M")} for w in qs]
    return JsonResponse({"terminy": out})


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
