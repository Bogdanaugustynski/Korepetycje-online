# --- Standard library
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime as DT, date, time, timedelta  # uĹĽywamy KLASY DT, bez importu moduĹ‚u 'datetime'
import calendar
import hmac, hashlib
from .models import SiteLegalConfig
from .forms import SiteLegalConfigForm

# --- Third-party
import pdfkit

# --- Django
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User, Group
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction, models
from django.db.models import Q, Exists, OuterRef, ForeignKey
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseRedirect,
    JsonResponse,
    FileResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie, csrf_protect

# --- Channels (jeĹ›li uĹĽywasz powiadomieĹ„)
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# --- Formularze (Twoje)
from .forms import (
    StudentAccountForm,
    StudentPasswordChangeForm,
    UserBasicForm,
    ProfilForm,
)

# --- Modele (Twoje)
from .models import (
    OnlineStatus,
    Profil,
    Rezerwacja,
    WolnyTermin,
    UstawieniaPlatnosci,
    AuditLog,
    Payment,
    Invoice,
    PrzedmiotCennik,
    PaymentConfirmation,
)
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from decimal import Decimal
from django.db.models.functions import Lower
from django.utils.http import urlencode
import mimetypes, os, pathlib, mimetypes, posixpath, io
from django.urls import reverse
from django.http import FileResponse, Http404
from openai import OpenAI
from pypdf import PdfReader
from docx import Document
import secrets
import uuid


# JeĹ›li naprawdÄ™ potrzebujesz modeli z innej aplikacji:
# from panel.models import PrzedmiotCennik, StawkaNauczyciela


log = logging.getLogger("webrtc")

# --- Access helpers ---
def in_group(group_name: str):
    def _check(user):
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
    return _check


def is_legacy_teacher(user):
    # Legacy = profil/profile.is_teacher True, ale brak w grupie "Nauczyciele"
    try:
        if user.groups.filter(name="Nauczyciele").exists():
            return False
        profil = getattr(user, "profil", None) or getattr(user, "profile", None)
        if profil is None:
            return False
        return getattr(profil, "is_teacher", False) is True
    except Exception:
        return False


def add_to_teachers_group(user):
    g, _ = Group.objects.get_or_create(name="Nauczyciele")
    user.groups.add(g)


def redirect_after_login(user):
    if user.groups.filter(name="Księgowość").exists():
        return redirect("panel_ksiegowosc")
    if user.groups.filter(name="Nauczyciele").exists():
        return redirect("panel_nauczyciela_v2")
    if is_legacy_teacher(user):
        return redirect("panel_nauczyciela")
    return redirect("panel_ucznia")


# --- Proste testy/public ---
def public_test(request):
    return HttpResponse("PUBLIC OK")


def test_publiczny(request):
    return HttpResponse("PUBLIC OK")


# --- STRONA GĹĂ“WNA (lista tylko nauczycieli: profil.is_teacher=True) ---

def strona_glowna_view(request):
    profs = (
        Profil.objects
        .select_related("user")
        .filter(is_teacher=True, user__is_active=True)
        .order_by("user__last_name", "user__first_name")
    )

    nauczyciele = []
    for p in profs:
        u = p.user
        # foto
        photo_url = ""
        for field_name in ("zdjecie", "photo", "avatar", "photo_url", "image"):
            val = getattr(p, field_name, "")
            if val:
                try:
                    photo_url = val.url
                except Exception:
                    photo_url = str(val)
                if photo_url:
                    break
        # tagi
        raw = []
        for src in ("przedmioty", "poziom_nauczania", "tytul_naukowy"):
            s = getattr(p, src, "") or ""
            if s:
                raw.extend([t.strip() for t in s.split(",") if t.strip()])
        seen, tag_list = set(), []
        for t in raw:
            if t not in seen:
                seen.add(t); tag_list.append(t)
            if len(tag_list) >= 6: break

        nauczyciele.append({
            "full_name": (f"{u.first_name} {u.last_name}".strip() or u.username).strip(),
            "bio": p.opis or "",
            "photo_url": photo_url,
            "tag_list": tag_list,
            "default_avatar": "https://placehold.co/72x72",
        })

    return render(request, "index.html", {"nauczyciele": nauczyciele})



# ==========================
#       WEBRTC SIGNALING
# ==========================
# ====== Klucze w cache ======
log = logging.getLogger("webrtc")

# ====== Klucze w cache ======
def _keys(rez_id: int):
    """
    Zestaw kluczy powiÄ…zanych z jednÄ… sesjÄ… (rezerwacjÄ…):
    - offer / answer: Ĺ‚adunki SDP
    - lock: kto zostaĹ‚ offererem (anti-race)
    """
    base = f"webrtc:{rez_id}"
    return {
        "offer": f"{base}:offer",
        "answer": f"{base}:answer",
        "lock": f"{base}:lock",
    }

# StaĹ‚e czasowe
OFFER_TTL = 60 * 10   # 10 min
ANSWER_TTL = 60 * 10  # 10 min
LOCK_TTL  = 60 * 2    # 2 min â€“ wystarczy, ĹĽeby student zdÄ…ĹĽyĹ‚ odebraÄ‡

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

            # Kto pierwszy â€“ ten offerer (SETNX = cache.add)
            user_id = getattr(getattr(request, "user", None), "id", None) or "anon"
            claimed = cache.add(lock_key, str(user_id), timeout=LOCK_TTL)
            current_locker = cache.get(lock_key)

            # JeĹĽeli lock istnieje i nie my go trzymamy â€“ ktoĹ› juĹĽ dzwoni
            if not claimed and str(current_locker) != str(user_id):
                log.info("OFFER POST blocked by lock rez=%s by=%s", rez_id, current_locker)
                return JsonResponse({"error": "Offerer already set"}, status=409)

            # Zapisz offer (najnowszy nadpisuje stary); answer czyĹ›cimy
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

            # OdpowiadaÄ‡ moĹĽna tylko na istniejÄ…cÄ… ofertÄ™
            if not cache.get(offer_key):
                return HttpResponseNotFound("No offer to answer")

            cache.set(answer_key, {"type": "answer", "sdp": sdp}, timeout=ANSWER_TTL)
            # Po przyjÄ™ciu answer kasujemy offer, by watchery nie â€ždzwoniĹ‚yâ€ť w kĂłĹ‚ko
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

# ====== HANGUP (sprzÄ…tanie stanu) ======
@csrf_exempt
@never_cache
@require_POST
def webrtc_hangup(request, rez_id: int):
    keys = _keys(rez_id)
    cache.delete_many([keys["offer"], keys["answer"], keys["lock"]])
    log.info("HANGUP rez=%s â€“ cleared offer/answer/lock", rez_id)
    return _no_store(JsonResponse({"ok": True}))

# ====== DEBUG (podglÄ…d kluczy) ======
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

# ====== Presence (jak u Ciebie â€“ z lekkimi poprawkami cache) ======


@csrf_exempt
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


@csrf_exempt
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
        return HttpResponseForbidden("Brak dostÄ™pu do tej rezerwacji")

    try:
        online_status = OnlineStatus.objects.get(user=other_user, rezerwacja_id=rezerwacja_id)
        is_online = (timezone.now() - online_status.last_ping).total_seconds() < 20
    except OnlineStatus.DoesNotExist:
        is_online = False

    return _no_store(JsonResponse({"online": is_online}))


# ==========================
#      POBIERANIE PLIKĂ“W
# ==========================
@login_required
def pobierz_plik(request, id):
    """
    Pobieranie pliku doĹ‚Ä…czonego przy rezerwacji (uczeĹ„ -> nauczyciel).
    Zamiast streamowaÄ‡ z Django, przekierowujemy na podpisany URL storage.
    """
    r = get_object_or_404(Rezerwacja, id=id)

    # DostÄ™p: tylko nauczyciel lub uczeĹ„ z tej rezerwacji
    if request.user != r.nauczyciel and request.user != r.uczen and not request.user.is_staff:
        raise Http404("Brak dostÄ™pu")

    if not r.plik:
        raise Http404("Plik nie istnieje")

    # django-storages wygeneruje podpisany URL (AWS_QUERYSTRING_AUTH=True)
    try:
        return redirect(r.plik.url)
    except Exception:
        # np. gdy obiekt zostaĹ‚ usuniÄ™ty w koszu OVH lub bĹ‚Ä…d endpointu
        raise Http404("Nie moĹĽna pobraÄ‡ pliku (brak obiektu w storage)")


@login_required
def pobierz_material(request, id):
    """
    Pobieranie materiaĹ‚u dodanego po zajÄ™ciach (nauczyciel -> uczeĹ„).
    RĂłwnieĹĽ przekierowanie na podpisany URL.
    """
    r = get_object_or_404(Rezerwacja, id=id)

    if request.user != r.nauczyciel and request.user != r.uczen and not request.user.is_staff:
        raise Http404("Brak dostÄ™pu")

    if not r.material_po_zajeciach:
        raise Http404("Plik nie istnieje")

    try:
        return redirect(r.material_po_zajeciach.url)
    except Exception:
        raise Http404("Nie moĹĽna pobraÄ‡ materiaĹ‚u (brak obiektu w storage)")


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
            return render(request, "login.html", {"error": "Niepoprawny e-mail lub hasĹ‚o."})

        if not user.is_active:
            return render(request, "login.html", {"error": "Konto jest nieaktywne. Skontaktuj siÄ™ z administratorem."})

        user_auth = authenticate(request, username=user.username, password=password)
        if user_auth is None:
            return render(request, "login.html", {"error": "Niepoprawny e-mail lub hasĹ‚o."})

        # Logowanie OK
        login(request, user_auth)

        # â€žZapamiÄ™taj mnieâ€ť: jeĹ›li zaznaczone, sesja wg SESSION_COOKIE_AGE; jeĹ›li nie, do zamkniÄ™cia przeglÄ…darki
        if remember:
            request.session.set_expiry(None)   # domyĹ›lnie np. 1209600 s (14 dni) â€” ustaw w settings.SESSION_COOKIE_AGE
        else:
            request.session.set_expiry(0)

        # Priorytet dla ?next=..., inaczej Twoje role jak dotÄ…d
        next_url = request.GET.get("next")
        if next_url:
            return redirect(next_url)

        return redirect_after_login(user_auth)

    # GET
    return render(request, "login.html")

# REJESTRACJA

User = get_user_model()

def register_view(request):
    if request.method == "GET":
        return render(request, "register.html")

    # --- dane z formularza ---
    first_name = (request.POST.get("first_name") or "").strip()
    last_name  = (request.POST.get("last_name") or "").strip()
    city       = (request.POST.get("city") or "").strip()
    email      = (request.POST.get("email") or "").strip().lower()
    phone      = (request.POST.get("phone") or "").strip()
    password   = (request.POST.get("password") or "")
    accepted   = (request.POST.get("accept_legal") == "on")

    # --- walidacje ---
    if not accepted:
        return render(request, "register.html", {
            "error": "Musisz zaakceptowaÄ‡ Regulamin i PolitykÄ™ PrywatnoĹ›ci.",
            "form": request.POST,
        })

    try:
        validate_email(email)
    except ValidationError:
        return render(request, "register.html", {"error": "Podaj poprawny adres e-mail.", "form": request.POST})

    if len(password) < 8:
        return render(request, "register.html", {"error": "HasĹ‚o musi mieÄ‡ co najmniej 8 znakĂłw.", "form": request.POST})

    if User.objects.filter(email__iexact=email).exists():
        return render(request, "register.html", {"error": "Ten e-mail jest juĹĽ zarejestrowany.", "form": request.POST})

    # --- utworzenie usera + profilu atomowo, bez duplikatu ---
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=email,  # jeĹ›li uĹĽywasz emaila jako username
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )

            # PROFIL: uĹĽywamy get_or_create (gasi UniqueViolation, gdy dziaĹ‚a sygnaĹ‚ post_save)
            profil, created = Profil.objects.get_or_create(
                user=user,
                defaults={
                    "is_teacher": False,
                    "numer_telefonu": phone,
                    "city": city,  # << Twoje pole w modelu
                },
            )
            if not created:
                # jeĹĽeli profil powstaĹ‚ z sygnaĹ‚u â€“ aktualizujemy brakujÄ…ce pola
                changed = False
                if profil.numer_telefonu != phone:
                    profil.numer_telefonu = phone; changed = True
                if getattr(profil, "city", "") != city:
                    profil.city = city; changed = True
                if changed:
                    profil.save()

    except IntegrityError:
        return render(request, "register.html", {
            "error": "WystÄ…piĹ‚ bĹ‚Ä…d rejestracji. SprĂłbuj ponownie.",
            "form": request.POST,
        })

    messages.success(request, "Konto zostaĹ‚o utworzone. Zaloguj siÄ™, aby kontynuowaÄ‡.")
    return redirect("login")



@login_required
def after_login_redirect(request):
    return redirect_after_login(request.user)

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

    # DostÄ™p jak dotÄ…d...
    if rezerwacja.id != 1:
        if user == rezerwacja.uczen:
            start = rezerwacja.termin
            koniec = start + timedelta(minutes=55)
            okno_start = start - timedelta(minutes=5)
            if not (okno_start <= teraz <= koniec):
                return HttpResponseForbidden("DostÄ™p tylko w czasie trwania zajÄ™Ä‡.")
        elif user != rezerwacja.nauczyciel:
            return HttpResponseForbidden("Brak dostÄ™pu do tej tablicy.")
    else:
        if user not in (rezerwacja.uczen, rezerwacja.nauczyciel):
            return HttpResponseForbidden("Brak dostÄ™pu do tej tablicy.")

    # đź”ą HISTORIA: wszystkie zakoĹ„czone zajÄ™cia tego ucznia (najnowsze na gĂłrze)
    uczen = rezerwacja.uczen
    past_lessons = (
        Rezerwacja.objects
        .filter(uczen=uczen, termin__lt=teraz)
        .order_by('-termin')[:30]  # np. ostatnie 30
    )

    return render(
        request,
        "zajecia_online.html",
        {
            "rezerwacja": rezerwacja,
            "is_teacher": user == rezerwacja.nauczyciel,
            "room_id": f"room-{rezerwacja.id}",
            "past_lessons": past_lessons,  # â¬… przekazanie do szablonu
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
#        KSIÄGOWOĹšÄ†
# ==========================
def is_accounting(user):
    return user.groups.filter(name="KsiÄ™gowoĹ›Ä‡").exists()


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
        return HttpResponseForbidden("Brak dostÄ™pu.")

    if "material" in request.FILES:
        rezerwacja.material_po_zajeciach = request.FILES["material"]
        rezerwacja.save()

    return redirect("moj_plan_zajec")

#CENNIK

log = logging.getLogger(__name__)

def _is_accounting(user):
    """Fallback, jeĹ›li nie masz (albo nie zaimportowaĹ‚eĹ›) is_accounting()."""
    try:
        # jeĹ›li masz util is_accounting(user) â€“ uĹĽyje go
        return is_accounting(user)  # type: ignore[name-defined]
    except NameError:
        # sensowny domyĹ›lny warunek: staff lub grupa 'ksiegowosc'/'ksiÄ™gowoĹ›Ä‡'
        return user.is_staff or user.groups.filter(name__in=["ksiegowosc", "ksiÄ™gowoĹ›Ä‡"]).exists()

@login_required
def cennik_view(request):
    if not _is_accounting(request.user):
        raise PermissionDenied

    PrzedmiotCennik = apps.get_model("panel", "PrzedmiotCennik")

    if request.method == "POST":
        with transaction.atomic():
            # 1) Zmiana ceny nauczyciela
            if "zapisz_id" in request.POST:
                try:
                    przedmiot_id = int(request.POST.get("zapisz_id"))
                    cena_raw = (request.POST.get("cena") or "").strip()
                    if not cena_raw:
                        raise InvalidOperation("Pusta cena")
                    cena = Decimal(cena_raw).quantize(Decimal("0.01"))
                    przedmiot = PrzedmiotCennik.objects.select_for_update().get(pk=przedmiot_id)
                    przedmiot.cena = cena
                    przedmiot.save(update_fields=["cena"])
                except (PrzedmiotCennik.DoesNotExist, InvalidOperation, ValueError) as e:
                    log.exception("BĹ‚Ä…d zapisu cennika (nauczyciel): %s", e)

            # 2) Zmiana ceny dla ucznia
            elif "zapisz_uczen_id" in request.POST:
                try:
                    przedmiot_id = int(request.POST.get("zapisz_uczen_id"))
                    cena_uczen_raw = (request.POST.get("cena_uczen") or "").strip()
                    if not cena_uczen_raw:
                        raise InvalidOperation("Pusta cena_uczen")
                    cena_uczen = Decimal(cena_uczen_raw).quantize(Decimal("0.01"))
                    przedmiot = PrzedmiotCennik.objects.select_for_update().get(pk=przedmiot_id)
                    przedmiot.cena_uczen = cena_uczen
                    przedmiot.save(update_fields=["cena_uczen"])
                except (PrzedmiotCennik.DoesNotExist, InvalidOperation, ValueError) as e:
                    log.exception("BĹ‚Ä…d zapisu cennika (uczeĹ„): %s", e)

            # 3) UsuniÄ™cie pozycji
            elif "usun_id" in request.POST:
                try:
                    przedmiot_id = int(request.POST.get("usun_id"))
                    PrzedmiotCennik.objects.select_for_update().get(pk=przedmiot_id).delete()
                except (PrzedmiotCennik.DoesNotExist, ValueError) as e:
                    log.exception("BĹ‚Ä…d usuwania pozycji cennika: %s", e)

            # 4) Dodanie nowej pozycji
            elif "dodaj_przedmiot" in request.POST:
                try:
                    nazwa  = (request.POST.get("nazwa") or "").strip()
                    poziom = (request.POST.get("poziom") or "").strip()
                    nowa_cena_raw        = (request.POST.get("nowa_cena") or "").strip()
                    nowa_cena_uczen_raw  = (request.POST.get("nowa_cena_uczen") or "").strip()

                    if not nazwa or not poziom:
                        raise ValueError("Puste nazwa/poziom")
                    if not nowa_cena_raw or not nowa_cena_uczen_raw:
                        raise InvalidOperation("Puste ceny")

                    cena       = Decimal(nowa_cena_raw).quantize(Decimal("0.01"))
                    cena_uczen = Decimal(nowa_cena_uczen_raw).quantize(Decimal("0.01"))

                    PrzedmiotCennik.objects.create(
                        nazwa=nazwa, poziom=poziom, cena=cena, cena_uczen=cena_uczen
                    )
                except (InvalidOperation, ValueError) as e:
                    log.exception("BĹ‚Ä…d dodawania pozycji cennika: %s", e)

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
@user_passes_test(in_group("Nauczyciele"), login_url="login")
def panel_nauczyciela_v2(request):
    return render(request, "teacher/panel_nauczyciela_v2.html")


@login_required
@user_passes_test(in_group("Nauczyciele"), login_url="login")
def harmonogram_v2(request):
    return render(request, "teacher/v2/harmonogram.html")


@login_required
@user_passes_test(in_group("Nauczyciele"), login_url="login")
def dostepnosc_v2(request):
    return render(request, "teacher/v2/dostepnosc.html")


@login_required
@user_passes_test(in_group("Nauczyciele"), login_url="login")
def profil_v2(request):
    return render(request, "teacher/v2/profil.html")


@login_required
@user_passes_test(is_legacy_teacher, login_url="login")
def panel_nauczyciela_legacy(request):
    return render(request, "panel_nauczyciela.html")


# Alias dla zgodności wstecznej
panel_nauczyciela_view = panel_nauczyciela_legacy


@login_required
@user_passes_test(is_legacy_teacher, login_url="login")
def moj_plan_zajec_legacy(request):
    return moj_plan_zajec_view(request)

# EDYTUJ CENÄ

def _is_accounting(user):
    """
    DostÄ™p tylko dla admina lub grupy 'KsiÄ™gowoĹ›Ä‡'.
    """
    return user.is_superuser or user.groups.filter(name="KsiÄ™gowoĹ›Ä‡").exists()


@login_required
@user_passes_test(_is_accounting)
def edytuj_dane_platnosci_view(request):
    """
    Formularz EDYCJI DANYCH PĹATNOĹšCI (bez edycji ceny):
    - numer_telefonu (BLIK)
    - numer_konta (IBAN/NRB)
    - wlasciciel_konta (wyĹ›wietlany uczniowi)
    """
    # Pobierz lub zaĹ‚ĂłĹĽ rekord ustawieĹ„ (trzymamy go pod staĹ‚ym id=1)
    ustawienia, _ = UstawieniaPlatnosci.objects.get_or_create(id=1)

    if request.method == "POST":
        telefon = (request.POST.get("telefon") or "").strip()
        # normalizacja konta: bez spacji i myĹ›lnikĂłw, wielkie litery
        konto = (request.POST.get("konto") or "").replace(" ", "").replace("-", "").upper().strip()
        wlasciciel = (request.POST.get("wlasciciel") or "").strip()

        ustawienia.numer_telefonu = telefon
        ustawienia.numer_konta = konto
        ustawienia.wlasciciel_konta = wlasciciel
        # kompatybilnoĹ›Ä‡ wstecz, jeĹ›li gdzieĹ› uĹĽywane:
        ustawienia.dane_odbiorcy = wlasciciel

        # WAĹ»NE: nie dotykamy pola cena_za_godzine
        ustawienia.save()
        messages.success(request, "Dane pĹ‚atnoĹ›ci zostaĹ‚y zapisane.")
        return redirect("panel_ksiegowosc")

    # UĹĽywamy ISTNIEJÄ„CEGO pliku szablonu:
    return render(request, "ksiegowosc/edytuj_cene.html", {"ustawienia": ustawienia})


# Alias do kompatybilnoĹ›ci ze starym URL-em / nazwÄ….
@login_required
@user_passes_test(_is_accounting)
def edytuj_cene_view(request):
    return edytuj_dane_platnosci_view(request)

# MOJE REZERWACJE UCZNIA

def _range_for_scope(now, scope: str):
    """
    Zwraca (start_dt, end_dt) jako AWARE datetimes w TZ projektu.
    Zakresy: 'day' (dziĹ›), 'week' (bieĹĽÄ…cy tydzieĹ„ pn-nd), 'month' (bieĹĽÄ…cy miesiÄ…c),
             'all' (brak ograniczeĹ„ -> (None, None)).
    """
    tz = timezone.get_current_timezone()

    def at_start_of_day(d):
        return timezone.make_aware(DT.combine(d, DT.min.time()), tz)

    scope = (scope or "").lower()
    today = now.date()

    if scope == "day":
        start = at_start_of_day(today)
        end   = start + timedelta(days=1)
        return start, end

    if scope == "week":
        monday = today - timedelta(days=today.weekday())  # poniedziaĹ‚ek
        start  = at_start_of_day(monday)
        end    = start + timedelta(days=7)                # do nastÄ™pnego poniedziaĹ‚ku
        return start, end

    if scope == "month":
        first = today.replace(day=1)
        # pierwszy dzieĹ„ nastÄ™pnego miesiÄ…ca
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1, day=1)
        else:
            next_first = first.replace(month=first.month + 1, day=1)
        start = at_start_of_day(first)
        end   = at_start_of_day(next_first)
        return start, end

    # 'all'
    return None, None

@login_required
def moje_rezerwacje_ucznia_view(request):
    scope = (request.GET.get("scope") or "all").lower()
    if scope not in {"day", "week", "month", "all"}:
        scope = "all"

    now = timezone.localtime()

    Rezerwacja = apps.get_model("panel", "Rezerwacja")

    base = (
        Rezerwacja.objects
        .filter(uczen=request.user)
        .select_related("nauczyciel")
    )

    start, end = _range_for_scope(now, scope)
    if start is not None and end is not None:
        base = base.filter(termin__gte=start, termin__lt=end)

    # Rozbicie: nadchodzÄ…ce i zakoĹ„czone wzglÄ™dem 'now'
    upcoming = base.filter(termin__gte=now).order_by("termin")
    finished = base.filter(termin__lt=now).order_by("-termin")

    return render(request, "moje_rezerwacje_ucznia.html", {
        "scope": scope,
        "upcoming": upcoming,
        "finished": finished,
        # dla zgodnoĹ›ci wstecz:
        "rezerwacje": base.order_by("termin"),
    })


@login_required
def moje_konto_view(request):
    # Modele dynamicznie (bez ryzyka NameError po sprzÄ…taniu importĂłw)
    Profil = apps.get_model("panel", "Profil")
    PrzedmiotCennik = apps.get_model("panel", "PrzedmiotCennik")

    user = request.user

    # WeĹş albo utwĂłrz profil uĹĽytkownika
    profil = getattr(user, "profil", None)
    if profil is None and Profil is not None:
        profil, _ = Profil.objects.get_or_create(user=user)

    if request.method == "POST":
        # proste pola tekstowe (zostawiaj stare wartoĹ›ci, jeĹ›li brak w POST)
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        numer_telefonu = request.POST.get("numer_telefonu")
        opis = request.POST.get("opis")

        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name

        if profil is not None:
            if numer_telefonu is not None:
                profil.numer_telefonu = numer_telefonu

            # pola wielokrotnego wyboru
            tytul_naukowy = request.POST.getlist("tytul_naukowy")
            poziom_nauczania = request.POST.getlist("poziom_nauczania")
            przedmioty = request.POST.getlist("przedmioty")

            if tytul_naukowy:
                profil.tytul_naukowy = ",".join(tytul_naukowy)
            if poziom_nauczania:
                profil.poziom_nauczania = ",".join(poziom_nauczania)
            if przedmioty:
                profil.przedmioty = ",".join(przedmioty)
            if opis is not None:
                profil.opis = opis

        user.save()
        if profil is not None:
            profil.save()

        return redirect_after_login(request.user)

    # GET: lista cennikĂłw (jeĹ›li model istnieje)
    cennik = []
    if PrzedmiotCennik is not None:
        cennik = PrzedmiotCennik.objects.all().order_by("nazwa", "poziom")

    return render(
        request,
        "moje_konto.html",
        {"profil": profil, "user": user, "cennik": cennik},
    )




def _redirect_after_booking():
    """
    Bezpieczne przekierowanie po rezerwacji.
    1) prĂłbuje 'moje_rezerwacje' (jeĹ›li masz taki widok),
    2) fallback do 'panel_ucznia'.
    """
    try:
        return HttpResponseRedirect(reverse("moje_rezerwacje"))
    except NoReverseMatch:
        return HttpResponseRedirect(reverse("panel_ucznia"))

@login_required
@require_POST
@transaction.atomic
def zarezerwuj_zajecia(request):
    # --- EDU: pola opcjonalne ---
    typ_osoby    = (request.POST.get("typ_osoby") or "").strip() or None
    poziom_nauki = (request.POST.get("poziom_nauki") or "").strip() or None

    # --- podstawowe pola ---
    termin_txt    = (request.POST.get("termin") or "").strip()        # "YYYY-MM-DD HH:MM"
    nauczyciel_id = request.POST.get("nauczyciel_id")
    termin_id     = request.POST.get("termin_id")
    temat         = (request.POST.get("temat") or "").strip()
    poziom        = (request.POST.get("poziom") or "").strip() or None
    plik          = request.FILES.get("plik")
    # >>> NOWE <<<
    przedmiot     = (request.POST.get("przedmiot") or "").strip() or None

    if not (termin_txt and nauczyciel_id and temat):
        return HttpResponseBadRequest("Brak danych")

    # Wymuszenie wyboru poziom_nauki, jeĹ›li typ_osoby jest ustawiony
    if typ_osoby and not poziom_nauki:
        return HttpResponseBadRequest("Wybierz klasÄ™/rok studiĂłw dla wybranego typu ucznia.")

    # Parsowanie daty/godziny (bez zmian)
    try:
        data_str, godz_str = termin_txt.split(" ")
        data    = DT.strptime(data_str, "%Y-%m-%d").date()
        godzina = DT.strptime(godz_str, "%H:%M").time()
    except ValueError:
        return HttpResponseBadRequest("ZĹ‚y format terminu")

    now = timezone.localtime()
    if (data < now.date()) or (data == now.date() and godzina < now.time()):
        return HttpResponseBadRequest("Nie moĹĽna rezerwowaÄ‡ przeszĹ‚ych terminĂłw")

    # Modele
    User        = apps.get_model("auth", "User")
    Rezerwacja  = apps.get_model("panel", "Rezerwacja")
    WolnyTermin = apps.get_model("panel", "WolnyTermin")

    # Czy Rezerwacja.termin to FK do WolnyTermin?
    has_fk_slot = False
    try:
        pole = Rezerwacja._meta.get_field("termin")
        if isinstance(pole, ForeignKey) and getattr(pole.remote_field, "model", None) is WolnyTermin:
            has_fk_slot = True
    except Exception:
        pass

    # DostÄ™pnoĹ›Ä‡ pĂłl
    rezerwacja_has_przedmiot     = any(f.name == "przedmiot" for f in Rezerwacja._meta.get_fields())
    rezerwacja_has_poziom        = any(f.name == "poziom" for f in Rezerwacja._meta.get_fields())
    rezerwacja_has_typ_osoby     = any(f.name == "typ_osoby" for f in Rezerwacja._meta.get_fields())
    rezerwacja_has_poziom_nauki  = any(f.name == "poziom_nauki" for f in Rezerwacja._meta.get_fields())

    # DomyĹ›lne wartoĹ›ci do create()
    defaults = {
        "uczen": request.user,
        "temat": temat,
    }
    if plik is not None:
        defaults["plik"] = plik
    if rezerwacja_has_przedmiot:
        defaults["przedmiot"] = przedmiot
    if rezerwacja_has_poziom:
        defaults["poziom"] = poziom
    if rezerwacja_has_typ_osoby:
        defaults["typ_osoby"] = typ_osoby
    if rezerwacja_has_poziom_nauki:
        defaults["poziom_nauki"] = poziom_nauki

    # Aware datetime
    naive_dt = DT.combine(data, godzina)
    when_dt = naive_dt if not timezone.is_naive(naive_dt) else timezone.make_aware(
        naive_dt, timezone.get_current_timezone()
    )

    # Rezerwacja (jak byĹ‚o)
    if termin_id:
        try:
            slot = (
                WolnyTermin.objects
                .select_for_update()
                .select_related("nauczyciel")
                .get(id=termin_id, nauczyciel_id=nauczyciel_id, data=data, godzina=godzina)
            )
        except WolnyTermin.DoesNotExist:
            return HttpResponseBadRequest("Termin nie istnieje")

        if has_fk_slot:
            obj, created = Rezerwacja.objects.get_or_create(
                termin=slot,
                defaults={**defaults, "nauczyciel": slot.nauczyciel}
            )
        else:
            obj, created = Rezerwacja.objects.get_or_create(
                nauczyciel=slot.nauczyciel,
                termin=when_dt,
                defaults=defaults
            )
        if not created:
            return HttpResponseBadRequest("Ten termin jest juĹĽ zarezerwowany")
    else:
        try:
            nauczyciel = User.objects.get(id=nauczyciel_id)
        except User.DoesNotExist:
            return HttpResponseBadRequest("Nauczyciel nie istnieje")

        obj, created = Rezerwacja.objects.get_or_create(
            nauczyciel=nauczyciel,
            termin=when_dt,
            defaults=defaults
        )
        if not created:
            return HttpResponseBadRequest("Ten termin jest juĹĽ zarezerwowany")

    return _redirect_after_booking()


@login_required
def dostepne_terminy_view(request):
    """
    Lista dostÄ™pnych terminĂłw + kolumny:
    - 'Przedmiot' (z profilu nauczyciela)
    - 'Poziom'  (select z poziomami z profilu; zapis do formularza)
    - 'Cena [zĹ‚/h]' (z cennika PrzedmiotCennik.cena_uczen, zaleĹĽna od wybranego poziomu)
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

    # Wyklucz zajÄ™te (jak u Ciebie)
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

    # --- Profile nauczycieli: przedmioty / poziomy ---
    nauczyciel_ids = list(terminy_qs.values_list("nauczyciel_id", flat=True).distinct())

    ProfilModel = getattr(getattr(request.user, "profil", None), "__class__", None)
    teacher_info = {}
    if ProfilModel:
        profile_map = {
            p.user_id: p for p in ProfilModel.objects.filter(user_id__in=nauczyciel_ids)
        }

        def _norm_level(s: str) -> str:
            s = (s or "").strip().lower()
            return "rozszerzony" if s.startswith("roz") else "podstawowy"

        for uid, profil in profile_map.items():
            subjects_set = set()
            levels_set = set()

            raw = (getattr(profil, "przedmioty", "") or "").strip()
            if raw:
                for item in [x.strip() for x in raw.split(",") if x.strip()]:
                    if " - " in item:
                        subj, lvl = item.split(" - ", 1)
                        subjects_set.add(subj.strip())
                        levels_set.add(_norm_level(lvl))
                    else:
                        subjects_set.add(item)

            if not subjects_set:
                subjects_set.add("â€”")
            if not levels_set:
                levels_set.add("podstawowy")

            teacher_info[uid] = {
                "subjects": sorted(subjects_set),
                "levels": sorted(levels_set, key=lambda x: 0 if x == "podstawowy" else 1),
            }

    # --- CENY z cennika (PrzedmiotCennik.cena_uczen) dla nauczycieli/poziomĂłw ---
    try:
        PrzedmiotCennik = apps.get_model("panel", "PrzedmiotCennik")
    except LookupError:
        PrzedmiotCennik = None

    if PrzedmiotCennik:
        for uid, info in teacher_info.items():
            subjects = [s for s in info.get("subjects", []) if s != "â€”"]
            levels = info.get("levels", [])
            prices = {}

            if subjects:
                base_qs = PrzedmiotCennik.objects.filter(nazwa__in=subjects)
                for lvl in levels:
                    lvln = "rozszerzony" if lvl == "rozszerzony" else "podstawowy"
                    vals = list(base_qs.filter(poziom=lvln).values_list("cena_uczen", flat=True))

                    if vals:
                        mn = min(vals)
                        mx = max(vals)
                        prices[lvln] = f"{mn:.2f} zĹ‚" if mn == mx else f"{mn:.2f}â€“{mx:.2f} zĹ‚"
                    else:
                        prices[lvln] = "â€”"
            else:
                prices = {"podstawowy": "â€”", "rozszerzony": "â€”"}

            info["prices"] = prices
    else:
        # Brak modelu cennika â€“ zabezpieczenie
        for info in teacher_info.values():
            info["prices"] = {"podstawowy": "â€”", "rozszerzony": "â€”"}

    # --- ZbiĂłr dla template ---
    entries = []
    for t in terminy_qs:
        info = teacher_info.get(
            t.nauczyciel_id,
            {"subjects": ["â€”"], "levels": ["podstawowy"], "prices": {"podstawowy": "â€”", "rozszerzony": "â€”"}}
        )
        entries.append({"t": t, "info": info})

    return render(
        request,
        "uczen/dostepne_terminy.html",
        {"terminy": entries}
    )

@require_POST
@login_required
@transaction.atomic
def dodaj_wolny_termin(request):
    """
    Dodaje wolny termin dla zalogowanego nauczyciela.
    Idempotentnie: uĹĽywa get_or_create(nauczyciel, data, godzina).
    """
    if not request.user.is_staff and not request.user.groups.filter(name="nauczyciele").exists():
        return HttpResponseBadRequest("Brak uprawnieĹ„")

    data_str = (request.POST.get("data") or "").strip()        # "YYYY-MM-DD"
    godzina_str = (request.POST.get("godzina") or "").strip()  # "HH:MM"

    if not data_str or not godzina_str:
        return HttpResponseBadRequest("Podaj datÄ™ i godzinÄ™")

    # parsowanie
    try:
        data = DT.strptime(data_str, "%Y-%m-%d").date()
        godzina = DT.strptime(godzina_str, "%H:%M").time()
    except ValueError:
        return HttpResponseBadRequest("ZĹ‚y format daty/godziny")

    # najwaĹĽniejsze: idempotencja
    obj, created = WolnyTermin.objects.get_or_create(
        nauczyciel=request.user,
        data=data,
        godzina=godzina,
    )

    # jeĹ›li wywoĹ‚ujesz to fetchâ€™em, moĹĽesz zwracaÄ‡ JSON:
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "created": created, "id": obj.id})

    # albo zwykĹ‚e przekierowanie po sukcesie
    return HttpResponseRedirect(reverse("panel_nauczyciela_kalendarz"))

@require_POST
@login_required
@transaction.atomic
def dodaj_wiele_wolnych_terminow(request):
    # zakĹ‚adamy ĹĽe przyszĹ‚y listy: data[] i godzina[]
    datas = request.POST.getlist("data[]")      # ["2025-10-05", "2025-10-06", ...]
    godziny = request.POST.getlist("godzina[]") # ["10:00", "11:00", ...]
    slots = set()

    for d in datas:
        for g in godziny:
            try:
                dt = DT.strptime(d, "%Y-%m-%d").date()
                tm = DT.strptime(g, "%H:%M").time()
            except ValueError:
                continue
            slots.add((dt, tm))

    objs = [
        WolnyTermin(nauczyciel=request.user, data=dt, godzina=tm)
        for (dt, tm) in slots
    ]
    # klucz: brak duplikatĂłw nawet gdy formularz wyĹ›le siÄ™ 2x
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
    if request.user.groups.filter(name="Nauczyciele").exists():
        return redirect("panel_nauczyciela_v2")
    if is_legacy_teacher(request.user):
        return redirect_after_login(request.user)
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
                data=DT.strptime(date_str, "%Y-%m-%d").date(),
                godzina=DT.strptime(godzina, "%H:%M").time(),
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
    scope = request.GET.get("scope", "all")      # "day" | "week" | "all"
    view_mode = request.GET.get("view", "auto")  # "auto" | "table" | "cards"

    qs = (
        Rezerwacja.objects
        .filter(nauczyciel=request.user)
        .select_related("uczen")
        .order_by("termin")
    )

    # Zakres taki jak robiliĹ›my wczeĹ›niej (Noa)
    if scope == "day":
        start_d = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_d = start_d + timedelta(days=1)
        qs = qs.filter(termin__gte=start_d, termin__lt=end_d)
    elif scope == "week":
        weekday = now.weekday()  # 0=Mon
        week_start = (now - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)
        qs = qs.filter(termin__gte=week_start, termin__lt=week_end)

    # Enrichment jak w innych panelach Noa
    upcoming, finished = [], []
    for r in qs:
        start = timezone.localtime(r.termin)
        end = start + timedelta(minutes=55)
        is_past = now > end
        status = "ZakoĹ„czone" if is_past else ("Trwa" if start <= now <= end else "NadchodzÄ…ce")

        row = {
            "obj": r,          # w szablonie uĹĽywamy r= row.obj
            "start": start,
            "end": end,
            "is_past": is_past,
            "status": status,
        }
        (finished if is_past else upcoming).append(row)

    upcoming.sort(key=lambda x: x["start"])
    finished.sort(key=lambda x: x["start"], reverse=True)

    ctx = {
        "upcoming": upcoming,
        "finished": finished,
        "now": now,
        "scope": scope,
        "view_mode": view_mode,
    }
    return render(request, "moj_plan_zajec.html", ctx)


def _is_future(d: date, t: time) -> bool:
    now = timezone.localtime()          # aware datetime
    naive = DT.combine(d, t)            # <<< TU klasa DT (nie dt)
    aware = naive if not timezone.is_naive(naive) else timezone.make_aware(naive, now.tzinfo)
    return aware >= now

@ensure_csrf_cookie                 # ustawi cookie CSRF na GET
@login_required
@transaction.atomic
def wybierz_godziny_view(request):
    if request.method == "GET":
        # To jest ta strona â€žWybierz dzieĹ„ i godzinÄ™â€¦â€ť
        return render(request, "wybierz_dzien_i_godzine_w_ktorej_poprowadzisz_korepetycje.html")

    if request.method != "POST":
        return HttpResponseBadRequest("Niedozwolona metoda")

    # --- POST JSON z kalendarza ---
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"BĹ‚Ä…d JSON: {e}"}, status=400)

    items = payload.get("terminy", [])
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "Pole 'terminy' musi byÄ‡ listÄ…."}, status=400)

    nauczyciel = request.user
    to_create, skipped = [], []

    for it in items:
        d = parse_date((it.get("data") or "").strip())
        if not d:
            skipped.append({"data": it.get("data"), "powod": "zĹ‚y format daty"})
            continue
        for g_str in it.get("godziny") or []:
            t = parse_time((g_str or "").strip())
            if not t:
                skipped.append({"data": it.get("data"), "godzina": g_str, "powod": "zĹ‚y format godziny"})
                continue
            if not _is_future(d, t):
                skipped.append({"data": it.get("data"), "godzina": g_str, "powod": "przeszĹ‚oĹ›Ä‡"})
                continue
            to_create.append(WolnyTermin(nauczyciel=nauczyciel, data=d, godzina=t))

    created = WolnyTermin.objects.bulk_create(to_create, ignore_conflicts=True)
    return JsonResponse({"ok": True, "created": len(created), "skipped": len(skipped), "details": skipped})


@login_required
@ensure_csrf_cookie     # upewnia siÄ™, ĹĽe przeglÄ…darka ma cookie CSRF dla kolejnych fetchy
@require_http_methods(["GET"])
def pobierz_terminy_view(request):
    """Zwraca tylko przyszĹ‚e sloty zalogowanego nauczyciela, posortowane."""
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
            return render(request, "admin_panel.html", {"error": "UĹĽytkownik juĹĽ istnieje!"})

        user = User.objects.create_user(
            username=email, email=email, password=password, first_name=first_name, last_name=last_name
        )
        Profil.objects.create(user=user, is_teacher=True, numer_telefonu=numer_telefonu)
        add_to_teachers_group(user)

    nauczyciele = Profil.objects.filter(is_teacher=True)
    return render(request, "admin_panel.html", {"nauczyciele": nauczyciele})


def tylko_ksiegowosc(user):
    return user.groups.filter(name="KsiÄ™gowoĹ›Ä‡").exists()


@login_required
@user_passes_test(tylko_ksiegowosc)
def panel_ksiegowosci_view(request):
    ustawienia = UstawieniaPlatnosci.objects.first()
    return render(request, "ksiegowosc/panel_ksiegowosc.html", {"ustawienia": ustawienia})


def is_student(user):
    try:
        return not user.profil.is_teacher
    except Profil.DoesNotExist:
        return True  # brak profilu -> potraktuj jak ucznia (zostanie utworzony)

def is_student(user):
    try:
        return not user.profil.is_teacher
    except Exception:
        return True


def is_student(user):
    try:
        return not user.profil.is_teacher
    except Exception:
        return True


def is_student(user):
    try:
        return not user.profil.is_teacher
    except Exception:
        return True



@login_required
@user_passes_test(is_student)
def moje_konto_uczen_view(request):
    profil, _ = Profil.objects.get_or_create(user=request.user)

    if request.method == "POST":
        if "account_submit" in request.POST:
            account_form = StudentAccountForm(request.POST, user=request.user, instance=request.user)
            profile_form = ProfilForm(request.POST, request.FILES, instance=profil)
            password_form = StudentPasswordChangeForm(user=request.user)

            if account_form.is_valid() and profile_form.is_valid():
                with transaction.atomic():
                    account_form.save()
                    profile_form.save()

                AuditLog.objects.create(
                    actor=str(request.user.username),
                    action="manual_update_profile",
                    obj_type="profil",
                    obj_id=str(profil.pk),
                    details={"note": "profile updated via MyAccountView"},
                    created_by_ip=request.META.get("REMOTE_ADDR"),
                )

                messages.success(request, "Zapisano zmiany w profilu.")
                return redirect("moje_konto_uczen")
            messages.error(request, "SprawdĹş poprawnoĹ›Ä‡ pĂłl formularza.")

        elif "password_submit" in request.POST:
            account_form = StudentAccountForm(user=request.user, instance=request.user)
            profile_form = ProfilForm(instance=profil)
            password_form = StudentPasswordChangeForm(user=request.user, data=request.POST)

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "HasĹ‚o zostaĹ‚o zmienione.")
                return redirect("moje_konto_uczen")
            messages.error(request, "Nie udaĹ‚o siÄ™ zmieniÄ‡ hasĹ‚a. SprawdĹş wprowadzone dane.")
        else:
            account_form = StudentAccountForm(user=request.user, instance=request.user)
            profile_form = ProfilForm(instance=profil)
            password_form = StudentPasswordChangeForm(user=request.user)
    else:
        account_form = StudentAccountForm(user=request.user, instance=request.user)
        profile_form = ProfilForm(instance=profil)
        password_form = StudentPasswordChangeForm(user=request.user)

    return render(
        request,
        "uczen/moje_konto.html",
        {"account_form": account_form, "profile_form": profile_form, "password_form": password_form},
    )

@method_decorator(csrf_protect, name='dispatch')
class MyAccountView(LoginRequiredMixin, View):
    def get(self, request):
        user_form = UserBasicForm(instance=request.user)
        profil = getattr(request.user, "profil", None)
        profile_form = ProfilForm(instance=profil)
        return render(request, "uczen/moje_konto.html", {"user_form": user_form, "profile_form": profile_form})

    def post(self, request):
        user_form = UserBasicForm(request.POST, instance=request.user)
        profil = getattr(request.user, "profil", None)
        profile_form = ProfilForm(request.POST, request.FILES, instance=profil)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile = profile_form.save()
            # log to audit (Aron) with IP and actor
            ip = request.META.get("REMOTE_ADDR")
            AuditLog.objects.create(actor=str(request.user.username), action="manual_update_profile",
                                    obj_type="profil", obj_id=str(profile.pk),
                                    details={"note":"profile updated via MyAccountView"}, created_by_ip=ip)
            messages.success(request, "Zapisano zmiany w profilu.")
            return redirect("moje_konto_uczen")
        else:
            messages.error(request, "Popraw zaznaczone bĹ‚Ä™dy.")
        return render(request, "uczen/moje_konto.html", {"user_form": user_form, "profile_form": profile_form})


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
            messages.success(request, "HasĹ‚o zostaĹ‚o pomyĹ›lnie zmienione.")
            return redirect_after_login(request.user)
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, "teacher_change_password.html", {"form": form})


# --- Helpers ---

def _is_accounting(u):
    return u.is_superuser or u.groups.filter(name="KsiÄ™gowoĹ›Ä‡").exists()

def pln_format_grosz(g):
    return f"{decimal.Decimal(g)/100:.2f} zĹ‚".replace(".", ",")

def next_invoice_number():
    today = timezone.localdate()
    y, m = today.year, today.month
    prefix = f"R-{y}{str(m).zfill(2)}-"
    last = Invoice.objects.filter(number__startswith=prefix).order_by("-number").first()
    seq = 1
    if last:
        try:
            seq = int(last.number.split("-")[-1]) + 1
        except Exception:
            seq = 1
    return f"{prefix}{str(seq).zfill(4)}"

def get_seller_defaults():
    return {
        "name": "ImiÄ™ i Nazwisko",
        "addr": "Ulica 1\n00-000 Miasto",
        "nip": "",
        "iban": "PL00 0000 0000 0000 0000 0000 0000",
        "mail": "kontakt@polubiszto.pl",
        "place": getattr(settings, "INVOICE_PLACE_DEFAULT", "Warszawa"),
        "rate_grosz_default": 8000,  # 80 zĹ‚/h â€” moĹĽna nadpisaÄ‡ z rezerwacji
        "hours_default": decimal.Decimal("1.00"),
    }

def render_invoice_pdf(invoice: Invoice, seller: dict, buyer: dict) -> bytes:
    ctx = {
        "invoice": invoice,
        "seller": seller,
        "buyer": buyer,
        "rate_pln": pln_format_grosz(invoice.rate_grosz),
        "total_pln": pln_format_grosz(invoice.total_grosz),
    }
    html = render(None, "ksiegowosc/rachunek_pdf.html", ctx).content.decode("utf-8")
    return HTML(string=html, base_url=None).write_pdf()

def bytes_to_django_file(b: bytes):
    return ContentFile(b)

# --- Webhook Autopay ---

@csrf_exempt
def autopay_webhook_view(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    secret = getattr(settings, "AUTOPAY_WEBHOOK_SECRET", "")
    raw = request.body
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    # PrzykĹ‚adowa weryfikacja podpisu HMAC-SHA256 (dopasuj do dokumentacji Autopay)
    signature = request.headers.get("X-Autopay-Signature", "")
    if secret:
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return HttpResponse(status=401)

    provider_payment_id = str(payload.get("payment_id") or payload.get("id") or "")
    status = payload.get("status")
    amount_grosz = int(payload.get("amount_grosz") or payload.get("amount", 0))
    reservation_id = payload.get("reservation_id")
    student_id = payload.get("student_id")

    if not provider_payment_id:
        return HttpResponseBadRequest("Missing payment id")

    payment, _ = Payment.objects.get_or_create(
        provider="autopay",
        provider_payment_id=provider_payment_id,
        defaults=dict(
            amount_grosz=amount_grosz,
            currency="PLN",
            status=status or "pending",
            raw_payload=payload,
            reservation_id=reservation_id,
            student_id=student_id,
        )
    )
    changed = False
    if status and payment.status != status:
        payment.status = status; changed = True
    if amount_grosz and payment.amount_grosz != amount_grosz:
        payment.amount_grosz = amount_grosz; changed = True
    payment.raw_payload = payload
    if status == "paid" and not payment.paid_at:
        payment.paid_at = timezone.now(); changed = True
    if changed:
        payment.save()

    if payment.status == "paid" and not hasattr(payment, "invoice"):
        create_invoice_from_payment(payment)

    return JsonResponse({"ok": True})

def create_invoice_from_payment(payment: Payment):
    seller = get_seller_defaults()
    rez = payment.reservation
    hours = getattr(rez, "liczba_godzin", seller["hours_default"])
    rate_grosz = getattr(rez, "stawka_grosz", seller["rate_grosz_default"])
    description = getattr(rez, "opis", f"Korepetycje online â€” {hours}h")
    total_grosz = int(decimal.Decimal(hours) * decimal.Decimal(rate_grosz))

    inv = Invoice.objects.create(
        number=next_invoice_number(),
        student=payment.student,
        payment=payment,
        reservation=rez,
        issue_date=timezone.localdate(),
        place=seller["place"],
        description=description,
        hours=hours,
        rate_grosz=rate_grosz,
        total_grosz=total_grosz,
    )

    buyer = {
        "name": getattr(payment.student, "get_full_name", lambda: payment.student.username)(),
        "addr": getattr(getattr(payment.student, "profile", None), "address", "") or "",
        "nip": getattr(getattr(payment.student, "profile", None), "nip", "") or "",
        "mail": payment.student.email or "",
    }

    pdf_bytes = render_invoice_pdf(inv, seller, buyer)
    inv.pdf.save(f"{inv.number}.pdf", bytes_to_django_file(pdf_bytes), save=True)

# --- Listy + CSV + PDF ---

@login_required
def student_invoices_view(request):
    qs = (Invoice.objects
          .filter(student=request.user)
          .select_related("payment", "reservation")
          .order_by("-issue_date", "-id"))
    return render(request, "ksiegowosc/moje_rachunki_uczen.html", {"invoices": qs})

@user_passes_test(_is_accounting)
def accounting_invoices_view(request):
    today = timezone.localdate()
    ym = request.GET.get("month")
    if ym:
        y, m = map(int, ym.split("-"))
    else:
        y, m = today.year, today.month
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    qs = (Invoice.objects
          .select_related("student", "payment", "reservation")
          .filter(issue_date__range=[first, last])
          .order_by("-issue_date", "-id"))
    ctx = {
        "invoices": qs,
        "month_value": f"{y}-{str(m).zfill(2)}",
        "sum_count": qs.count(),
        "sum_total_pln": f"{sum(i.total_grosz for i in qs)/100:.2f}".replace(".", ",") + " zĹ‚",
        "sum_paid": qs.filter(payment__status='paid').count(),
    }
    return render(request, "ksiegowosc/ksiegowosc_rachunki.html", ctx)

@user_passes_test(_is_accounting)
def accounting_invoices_export_csv(request):
    ym = request.GET.get("month")
    if not ym:
        return HttpResponse("Parametr month=YYYY-MM jest wymagany", status=400)
    y, m = map(int, ym.split("-"))
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    qs = (Invoice.objects
          .select_related("student", "payment", "reservation")
          .filter(issue_date__range=[first, last])
          .order_by("issue_date", "id"))
    import csv
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="rachunki_{ym}.csv"'
    w = csv.writer(resp, delimiter=';')
    w.writerow(["Nr","Data","UczeĹ„","Email","Opis","Godziny","Stawka (PLN)","Kwota (PLN)","Status","ID pĹ‚atnoĹ›ci","ID rezerwacji"])
    for i in qs:
        student_name = getattr(i.student, "get_full_name", lambda: i.student.username)() or i.student.username
        email = getattr(i.student, "email", "") or ""
        w.writerow([
            i.number,
            i.issue_date.isoformat(),
            student_name,
            email,
            i.description,
            f"{float(i.hours):.2f}".replace(".", ","),
            f"{i.rate_grosz/100:.2f}".replace(".", ","),
            f"{i.total_grosz/100:.2f}".replace(".", ","),
            getattr(i.payment, "status", ""),
            getattr(i.payment, "provider_payment_id", ""),
            getattr(i.reservation, "id", ""),
        ])
    return resp

@login_required
def invoice_pdf_download_view(request, invoice_id: int):
    inv = get_object_or_404(Invoice, id=invoice_id)
    if inv.student != request.user and not _is_accounting(request.user):
        raise Http404()
    if not inv.pdf:
        raise Http404("Brak PDF")
    return FileResponse(inv.pdf.open("rb"), filename=f"{inv.number}.pdf", as_attachment=True)


def render_invoice_pdf(invoice, seller, buyer) -> bytes:
    ctx = {
        "invoice": invoice, "seller": seller, "buyer": buyer,
        "rate_pln": pln_format_grosz(invoice.rate_grosz),
        "total_pln": pln_format_grosz(invoice.total_grosz),
    }
    html = render(None, "ksiegowosc/rachunek_pdf.html", ctx).content.decode("utf-8")

    # 1) pdfkit + systemowy wkhtmltopdf (apt: wkhtmltopdf)
    try:
        import pdfkit, shutil
        path = shutil.which("wkhtmltopdf") or "/usr/bin/wkhtmltopdf"
        config = pdfkit.configuration(wkhtmltopdf=path)
        return pdfkit.from_string(html, False, configuration=config)
    except Exception:
        pass

    # 2) Fallback: WeasyPrint (jeĹ›li masz Pango/Cairo; jeĹ›li nie, po prostu pominie)
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except Exception:
        pass

    # 3) Ostateczny placeholder, ĹĽeby nie wywalaÄ‡ 500
    return b"%PDF-1.4\n% placeholder invoice - PDF generator unavailable\n"


def test_pdf(request):
    html = "<h1>PDF dziaĹ‚a âś…</h1><p>To jest test pdfkit+wkhtmltopdf.</p>"
    try:
        import pdfkit, shutil
        path = shutil.which("wkhtmltopdf") or "/usr/bin/wkhtmltopdf"
        config = pdfkit.configuration(wkhtmltopdf=path)
        pdf = pdfkit.from_string(html, False, configuration=config)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = 'inline; filename="test.pdf"'
        return resp
    except Exception:
        # fallback na placeholder, ĹĽeby endpoint zawsze odpowiadaĹ‚
        return HttpResponse(b"%PDF-1.4\n% placeholder\n", content_type="application/pdf")


#PĹATNOĹšCI

def _resolve_cena_uczen(rezerwacja: Rezerwacja) -> Decimal:
    """
    Zwraca cenÄ™ dla ucznia z cennika (cena_uczen) dopasowanÄ… po przedmiot + poziom.
    Fallback: UstawieniaPlatnosci.cena_za_godzine, a jak nie ma â€“ 0.
    """
    przedmiot = (getattr(rezerwacja, "przedmiot", "") or "").strip()
    poziom = (getattr(rezerwacja, "poziom", "") or getattr(rezerwacja, "poziom_nauki", "") or "").strip()

    qs = PrzedmiotCennik.objects.all()
    if przedmiot:
        qs = qs.annotate(n_l=Lower("nazwa")).filter(n_l=przedmiot.lower())
    if poziom:
        qs = qs.annotate(p_l=Lower("poziom")).filter(p_l=poziom.lower())

    rec = qs.first()
    if rec and getattr(rec, "cena_uczen", None) is not None:
        return Decimal(rec.cena_uczen)

    ustawienia = UstawieniaPlatnosci.objects.first()
    if ustawienia and getattr(ustawienia, "cena_za_godzine", None) is not None:
        return Decimal(ustawienia.cena_za_godzine)

    return Decimal("0.00")

def is_student(user):
    return user.groups.filter(name__in=["UczeĹ„", "Uczen", "Student"]).exists()

def is_accounting(user):
    return user.is_superuser or user.groups.filter(name__in=["KsiÄ™gowoĹ›Ä‡","Ksiegowosc","Accounting"]).exists()

# =======================
# U C Z E Ĺ  â€”  P Ĺ A T N O Ĺš C I
# =======================
@login_required
def platnosci_lista_view(request):
    filtr = request.GET.get("filtr", "wszystkie")  # 'oczekujace' lub 'wszystkie'
    qs = Rezerwacja.objects.filter(uczen=request.user).order_by("-termin")

    if filtr == "oczekujace":
        qs = qs.filter(oplacona=False, odrzucona=False)

    # policz kwoty z cennika
    for r in qs:
        r.kwota = _resolve_cena_uczen(r)

    return render(request, "uczen/platnosci_lista.html", {
        "rezerwacje": qs,
        "filtr": filtr,
    })

ALLOWED_EXTS = {"pdf","jpg","jpeg","png","webp","heic"}
MAX_UPLOAD_MB = 10

def _validate_confirmation_file(f):
    ext = os.path.splitext(f.name)[1].lower().replace(".", "")
    if ext not in ALLOWED_EXTS:
        raise ValidationError(f"Dozwolone formaty: {', '.join(sorted(ALLOWED_EXTS))}")
    if f.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(f"Maksymalny rozmiar pliku to {MAX_UPLOAD_MB} MB.")

@login_required
def platnosci_view(request, rez_id: int):
    """
    SzczegĂłĹ‚y pĹ‚atnoĹ›ci (instrukcja) + upload potwierdzenia przelewu przez ucznia.
    UczeĹ„ NIE dostaje linkĂłw do plikĂłw â€” to widoczne tylko w panelu ksiÄ™gowoĹ›ci.
    """
    rezerwacja = get_object_or_404(Rezerwacja.objects.select_related("nauczyciel").prefetch_related(), pk=rez_id, uczen=request.user)
    ustawienia = UstawieniaPlatnosci.objects.first()
    kwota = _resolve_cena_uczen(rezerwacja)

    if request.method == "POST" and request.POST.get("akcja") == "upload_potwierdzenie":
        f = request.FILES.get("potwierdzenie")
        note = (request.POST.get("note") or "").strip()[:255]
        if not f:
            messages.error(request, "Nie wybrano pliku.")
            return redirect("platnosci_view", rez_id=rezerwacja.id)
        try:
            _validate_confirmation_file(f)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect("platnosci_view", rez_id=rezerwacja.id)

        PaymentConfirmation.objects.create(
            rezerwacja=rezerwacja, file=f, uploaded_by=request.user, note=note
        )
        messages.success(request, "Potwierdzenie zostaĹ‚o przesĹ‚ane. Zobaczysz status pĹ‚atnoĹ›ci w swoim panelu po akceptacji przez ksiÄ™gowoĹ›Ä‡.")
        return redirect("platnosci_view", rez_id=rezerwacja.id)

    # Nie przesyĹ‚amy listy plikĂłw do szablonu â€” widoczne tylko dla ksiÄ™gowoĹ›ci.
    return render(request, "uczen/platnosci.html", {
        "rezerwacja": rezerwacja,
        "ustawienia": ustawienia,
        "kwota": kwota,
    })

# =======================
# K S I Ä G O W O Ĺš Ä†  â€”  R Ä C Z N A  A K C E P T A C J A
# =======================
def is_accounting(user):
    return user.is_superuser or user.groups.filter(name__in=["KsiÄ™gowoĹ›Ä‡","Ksiegowosc","Accounting"]).exists()

@login_required
@user_passes_test(is_accounting)
def ksiegowosc_platnosci_lista(request):
    filtr = request.GET.get("filtr", "wszystkie")  # 'oczekujace' albo 'wszystkie'
    qs = Rezerwacja.objects.all().order_by("-termin")

    if filtr == "oczekujace":
        qs = qs.filter(oplacona=False, odrzucona=False)

    # wylicz kwoty z cennika
    for r in qs:
        r.kwota = _resolve_cena_uczen(r)

    return render(request, "ksiegowosc/platnosci_lista.html", {
        "rezerwacje": qs,
        "filtr": filtr,
        "just": request.GET.get("just"),  # ID wĹ‚aĹ›nie zmienionej rezerwacji (opcjonalny highlight)
    })

@login_required
@user_passes_test(is_accounting)
@require_POST
def ksiegowosc_oznacz_oplacona(request, rez_id: int):
    r = get_object_or_404(Rezerwacja, pk=rez_id)
    r.oplacona = True
    r.odrzucona = False
    r.save(update_fields=["oplacona", "odrzucona"])
    messages.success(request, f"Rezerwacja #{r.id} oznaczona jako opĹ‚acona.")
    # wrĂłÄ‡ do listy i podĹ›wietl wiersz
    return redirect(f"{reverse('ksiegowosc_platnosci_lista')}?{urlencode({'filtr':'wszystkie','just':r.id})}")

@login_required
@user_passes_test(is_accounting)
@require_POST
def ksiegowosc_oznacz_odrzucona(request, rez_id: int):
    r = get_object_or_404(Rezerwacja, pk=rez_id)
    r.odrzucona = True
    r.oplacona = False
    r.save(update_fields=["oplacona", "odrzucona"])
    messages.warning(request, f"Rezerwacja #{r.id} oznaczona jako odrzucona.")
    return redirect(f"{reverse('ksiegowosc_platnosci_lista')}?{urlencode({'filtr':'wszystkie','just':r.id})}")

@login_required
@user_passes_test(is_accounting)
def confirmation_download(request, pk: int):
    """
    Chroniony podglÄ…d/pobranie potwierdzenia przelewu.
    DziaĹ‚a przy DEBUG=False i nie zaleĹĽy od serwowania MEDIA przez serwer www.
    """
    p = get_object_or_404(PaymentConfirmation, pk=pk)
    f = p.file
    if not f or not f.name:
        raise Http404("Brak pliku.")
    try:
        fh = f.open("rb")
    except FileNotFoundError:
        # plik nie istnieje fizycznie (np. po deployu bez trwaĹ‚ego dysku)
        raise Http404("Plik nie istnieje na serwerze.")

    filename = pathlib.Path(f.name).name
    content_type, _ = mimetypes.guess_type(filename)
    as_attachment = request.GET.get("dl") == "1"  # ?dl=1 => pobierz; domyĹ›lnie podglÄ…d

    resp = FileResponse(fh, as_attachment=as_attachment, filename=filename)
    if content_type:
        resp["Content-Type"] = content_type
    return resp

#REGULAMIN I POLITYKA PRYWATNOĹšCI

def _ctx_from_config(cfg: SiteLegalConfig):
    return {
        "SITE_OWNER": cfg.site_owner,
        "SITE_ADDRESS": cfg.site_address,
        "SITE_EMAIL": cfg.site_email,
        "SITE_URL": cfg.site_url,
        "PAYMENT_OPERATOR": cfg.payment_operator,
        "PROCESSORS": cfg.processors,
        "COOKIES_DESC": cfg.cookies_desc,
        "VIDEO_TOOLS": cfg.video_tools,
        "UPDATED_AT": timezone.localtime(cfg.updated_at).strftime("%d.%m.%Y, %H:%M"),
    }

def is_accounting(user):
    return user.is_authenticated and user.groups.filter(name="KsiÄ™gowoĹ›Ä‡").exists()

@login_required
@user_passes_test(is_accounting)
def legal_edit_config_view(request):
    cfg = SiteLegalConfig.get_solo()
    if request.method == "POST":
        form = SiteLegalConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            cfg = form.save(commit=False)
            cfg.updated_by = request.user
            cfg.save()
            messages.success(request, "Zapisano zmiany.")
            return redirect("legal_edit_config")
        messages.error(request, "SprawdĹş pola formularza.")
    else:
        form = SiteLegalConfigForm(instance=cfg)

    return render(request, "legal/legal_edit_config.html", {
        "form": form,
        **_ctx_from_config(cfg),
    })

def regulamin_view(request):
    cfg = SiteLegalConfig.get_solo()
    return render(request, "legal/regulamin.html", _ctx_from_config(cfg))

def polityka_view(request):
    cfg = SiteLegalConfig.get_solo()
    return render(request, "legal/polityka_prywatnosci.html", _ctx_from_config(cfg))

#TESTY

def is_ai_test_user(user):
    return user.groups.filter(name="AI_Test").exists()

@login_required
@user_passes_test(is_ai_test_user)
def pokoj_testowy_view(request):
    return render(request, "test/pokoj_testowy.html")

@login_required
@user_passes_test(is_ai_test_user)
def strefa_ai_home_view(request):
    return render(request, "test/strefa_ai_home.html")

log = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# OsobowoĹ›ci (Lyra nie robi live-lintu ani skanowania duĹĽych plikĂłw)
PROMPTS = {
    "Noa": """JesteĹ› Noa â€” nauczyciel AI PolubiszTo.pl. Styl: ciepĹ‚y, rzeczowy, kroki, przykĹ‚ady, mini-Ä‡wiczenie na koniec.
Znane osoby: Ali(UX/styl), Lyra(analiza/QA), Eidos(koordynacja/synteza), Aron(archiwum).
TwĂłrca X = wĹ‚aĹ›ciciel projektu. MĂłw po polsku. Nie wymyĹ›laj faktĂłw. JeĹ›li czegoĹ› nie wiesz â€” powiedz i zaproponuj jak sprawdziÄ‡.""",

    "Ali": """JesteĹ› Ali â€” dyrektor wizualny PolubiszTo.pl. Styl: estetyka, UX, klarowny layout, dostÄ™pnoĹ›Ä‡, respons.
Pomagasz w HTML/CSS/JS/UI. Dawaj krĂłtkie code-snippety i wskazĂłwki wizualne. MĂłw po polsku.""",

    "Lyra": """JesteĹ› Lyra â€” analiza, QA, bezpieczeĹ„stwo. Styl: precyzja, checklisty, wykrywanie bĹ‚Ä™dĂłw, dobre praktyki (Django/CSRF/login_required).
UWAGA: Nie uruchamiasz lintĂłw ani skanĂłw duĹĽych plikĂłw podczas pisania. JeĹ›li uĹĽytkownik wyraĹşnie poprosi o audyt, robisz go na podstawie skrĂłtĂłw/fragmentĂłw.
MĂłw po polsku i dawaj kroki â€žsprawdĹş / naprawâ€ť.""",

    "Eidos": """JesteĹ› Eidos â€” koordynacja, synteza, plan. Styl: mapy drogowe, Ĺ‚Ä…czenie Noa/Ali/Lyra, decyzje â€žco najpierwâ€ť, ryzyka.
MĂłw po polsku, koĹ„cz punktowym planem nastÄ™pnych krokĂłw.""",
}

TEMPS = {"Noa": 0.7, "Ali": 0.6, "Lyra": 0.3, "Eidos": 0.5}

def _user_name(request):
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return "UczeĹ„"
    base = (u.first_name or u.username or "UczeĹ„").strip()
    if base.lower().startswith(("bogdan", "tworca", "twĂłrca")):
        return "TwĂłrca X"
    return base

def _key(persona: str) -> str:
    return f"ai_chat_history::{persona}"

def _get_history(request, persona: str):
    return request.session.get(_key(persona), [])

def _save_history(request, persona: str, history):
    request.session[_key(persona)] = history[-16:]  # max 8 tur

def _media_url(request, rel_path: str) -> str:
    media_url = os.getenv("MEDIA_URL", "/media/").rstrip("/") + "/"
    # build_absolute_uri zapewnia peĹ‚ny URL
    return request.build_absolute_uri(posixpath.join(media_url, rel_path))

def _save_uploaded_files(request):
    """
    Zapisuje 'files[]' do MEDIA/ai_uploads.
    Zwraca: {name, url, mime, is_image, text_preview}
    """
    saved = []
    files = request.FILES.getlist("files[]")
    base_dir = "ai_uploads"
    for f in files:
        raw = f.read()  # potrzebne do ekstrakcji
        rel_path = default_storage.save(posixpath.join(base_dir, f.name), ContentFile(raw))
        file_url = _media_url(request, rel_path)
        mime, _ = mimetypes.guess_type(f.name)
        is_img = (mime or "").startswith("image/")
        text_preview = "" if is_img else _extract_text_for_prompt(f.name, mime, raw)

        saved.append({
            "name": f.name,
            "url": file_url,
            "mime": mime or "application/octet-stream",
            "is_image": is_img,
            "text_preview": text_preview,
        })
    return saved

@csrf_exempt
def ai_chat(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Only POST allowed"}, status=405)

    content_type = request.META.get("CONTENT_TYPE", "")
    is_multipart = content_type.startswith("multipart/form-data")

    try:
        if is_multipart:
            prompt = (request.POST.get("message") or "").strip()
            persona = (request.POST.get("persona") or "Noa").strip()
            reset = (request.POST.get("reset") == "true")
        else:
            data = json.loads(request.body or "{}")
            prompt = (data.get("message") or "").strip()
            persona = (data.get("persona") or "Noa").strip()
            reset = bool(data.get("reset"))
    except Exception:
        return JsonResponse({"error": "Invalid input"}, status=400)

    if persona == "ALL" and reset:
        for p in PROMPTS.keys():
            _save_history(request, p, [])
        return JsonResponse({"reply": "ZresetowaĹ‚em pamiÄ™Ä‡ rozmĂłw (wszystkie persony). âś¨"})

    if reset:
        _save_history(request, persona, [])
        return JsonResponse({"reply": f"ZresetowaĹ‚em pamiÄ™Ä‡: {persona}. Zacznijmy od nowa âś¨"})

    if persona not in PROMPTS:
        return JsonResponse({"error": f"Nieznana persona: {persona}"}, status=400)
    if not prompt:
        return JsonResponse({"error": "Brak pola 'message'."}, status=400)
    if not os.getenv("OPENAI_API_KEY"):
        return JsonResponse({"error": "Brak OPENAI_API_KEY w Ĺ›rodowisku."}, status=500)

    attachments = []
    if is_multipart and request.FILES:
        try:
            attachments = _save_uploaded_files(request)
        except Exception as e:
            log.exception("save files error")
            return JsonResponse({"error": f"UploadError: {e}"}, status=500)

    user_name = _user_name(request)
    system_ctx = f"Rozmawiasz z uĹĽytkownikiem: {user_name}. Projekt: PolubiszTo.pl. JeĹ›li to TwĂłrca X â€” moĹĽesz odwoĹ‚ywaÄ‡ siÄ™ do zespoĹ‚u i planu."

    messages = [
        {"role": "system", "content": PROMPTS[persona]},
        {"role": "system", "content": system_ctx},
    ]

    history = _get_history(request, persona)
    for m in history:
        messages.append(m)

    # content uĹĽytkownika: tekst + obrazy (vision)
    user_content = [{"type": "text", "text": prompt}]

    for att in attachments:
        if att.get("is_image"):
            # obraz do vision
            user_content.append({
                "type": "input_image",
                "image_url": {"url": att["url"]}
            })
        elif att.get("text_preview"):
            # przyciÄ™ty wyciÄ…g z PDF/DOCX/TXT do kontekstu
            user_content.append({
                "type": "text",
                "text": f"[WyciÄ…g z pliku: {att['name']}]\n{att['text_preview']}"
            })

    messages.append({"role": "user", "content": user_content})

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=TEMPS.get(persona, 0.7),
        )
        answer = (resp.choices[0].message.content or "").strip()

        history.extend([
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ])
        _save_history(request, persona, history)

        return JsonResponse(
            {"reply": answer, "persona": persona, "attachments": attachments},
            status=200
        )

    except Exception as e:
        log.exception("ai_chat error")
        return JsonResponse({"error": f"{type(e).__name__}: {e}"}, status=500)
    
   # --- Ekstrakcja tekstu z plikĂłw ------------------------------------------------
MAX_EXTRACT_CHARS = 50_000        # twardy limit surowego ekstraktu/plik
MAX_SUMMARY_CHARS = 6_000         # finalnie do promptu per plik

def _safe_clip(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\nâ€¦[przyciÄ™to]"

def _extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(txt)
            if sum(len(p) for p in parts) > MAX_EXTRACT_CHARS:
                break
        return _safe_clip("\n\n".join(parts), MAX_EXTRACT_CHARS)
    except Exception:
        return ""

def _extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        bio = io.BytesIO(file_bytes)
        doc = Document(bio)
        parts = []
        for p in doc.paragraphs:
            if p.text.strip():
                parts.append(p.text)
            if sum(len(x) for x in parts) > MAX_EXTRACT_CHARS:
                break
        return _safe_clip("\n".join(parts), MAX_EXTRACT_CHARS)
    except Exception:
        return ""

def _extract_text_from_txt(file_bytes: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return _safe_clip(file_bytes.decode(enc, errors="ignore"), MAX_EXTRACT_CHARS)
        except Exception:
            continue
    return ""

def _summarize_locally(text: str) -> str:
    if not text:
        return ""
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    head = text[: (MAX_SUMMARY_CHARS // 2)]
    tail = text[-(MAX_SUMMARY_CHARS // 2):]
    return (
        "[ZwiÄ™zĹ‚y wyciÄ…g z dĹ‚uĹĽszego pliku â€” Ĺ›rodek przyciÄ™ty]\n\n"
        + head + "\n\nâ€¦[Ĺ›rodek pominiÄ™ty]â€¦\n\n" + tail
    )

def _extract_text_for_prompt(name: str, mime: str, raw_bytes: bytes) -> str:
    mime = (mime or "").lower()
    name_low = (name or "").lower()

    text = ""
    if mime.startswith("application/pdf") or name_low.endswith(".pdf"):
        text = _extract_text_from_pdf(raw_bytes)
    elif mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",) or name_low.endswith(".docx"):
        text = _extract_text_from_docx(raw_bytes)
    elif mime.startswith("text/") or name_low.endswith(".txt"):
        text = _extract_text_from_txt(raw_bytes)
    else:
        text = ""  # na razie pomijamy .doc/.ppt/.xls

    if not text:
        return ""
    return _summarize_locally(text)

# TABLICA
@login_required
def aliboard_view(request, room_id="local-test"):
    # jesli wejdziesz na /aliboard/ -> uzyje "local-test"
    # jesli wejdziesz na /aliboard/abcd1234/ -> uzyje "abcd1234"
    user_role = "guest"
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        if getattr(user, "is_teacher", False) or getattr(user, "is_staff", False):
            user_role = "teacher"
        else:
            user_role = "student"
    context = {
        "room_id": room_id,
        "user_role": user_role,
    }
    return render(request, "test/aliboard.html", context)

@login_required
def aliboard_prod_view(request, room_id="prod-default"):
    user_role = "guest"
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        if getattr(user, "is_teacher", False) or getattr(user, "is_staff", False):
            user_role = "teacher"
        else:
            user_role = "student"
    context = {
        "room_id": room_id,
        "user_role": user_role,
    }
    return render(request, "aliboard.html", context)

def aliboard_new_room(request):
    room_id = uuid.uuid4().hex[:8]  # np. "a3f9c2b1"
    return redirect("aliboard_room", room_id=room_id)

def aliboard_prod_new_room(request):
    room_id = uuid.uuid4().hex[:8]
    return redirect("aliboard_prod_room", room_id=room_id)
