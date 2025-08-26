import json
from django.contrib.auth.models import User
from collections import defaultdict
from django.shortcuts import render
from .models import WolnyTermin
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.http import JsonResponse
from django.utils.dateparse import parse_date, parse_time
from django.core.files.storage import FileSystemStorage
from datetime import datetime
from django.contrib.auth import authenticate, login
from django.utils.timezone import now
from datetime import timedelta
from .models import Rezerwacja
from django.contrib.auth import logout
from .models import Profil
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Group
from .models import UstawieniaPlatnosci
from django.shortcuts import render, redirect
from django.core.exceptions import PermissionDenied
from django.contrib.auth import authenticate, login, logout
from panel.models import PrzedmiotCennik
from panel.models import StawkaNauczyciela, PrzedmiotCennik, Profil
from asgiref.sync import async_to_sync
from django.shortcuts import render, get_object_or_404
from django.http import FileResponse, Http404
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import OnlineStatus
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse

def public_test(request):
    return HttpResponse("PUBLIC OK")

def test_publiczny(request):
    return HttpResponse("PUBLIC OK")


def strona_glowna_view(request):
    return render(request, 'index.html')

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

    # as_attachment – plik pobiera się zamiast otwierać w przeglądarce
    return FileResponse(rezerwacja.plik.open("rb"), as_attachment=True)

def logout_view(request):
    logout(request)
    return redirect('login')  # 'login' to name widoku logowania w urls.py

def is_accounting(user):
    return user.groups.filter(name='Księgowość').exists()

def check_online_status(request, rezerwacja_id):
    try:
        rezerwacja = Rezerwacja.objects.get(pk=rezerwacja_id)
        user = request.user
        if user == rezerwacja.uczen:
            last_seen = rezerwacja.ostatnia_aktywność_nauczyciela
        elif user == rezerwacja.nauczyciel:
            last_seen = rezerwacja.ostatnia_aktywność_ucznia
        else:
            return JsonResponse({"online": False})

        online = last_seen and (now() - last_seen) < timedelta(seconds=30)
        return JsonResponse({"online": online})
    except Rezerwacja.DoesNotExist:
        return JsonResponse({"online": False})


@csrf_exempt
@login_required
def ping_online_status(request):
    if request.method == "POST":
        rezerwacja_id = request.POST.get("rezerwacja_id")
        if not rezerwacja_id:
            return JsonResponse({"error": "Brak ID rezerwacji"}, status=400)

        status, created = OnlineStatus.objects.get_or_create(
            user=request.user,
            rezerwacja_id=rezerwacja_id
        )
        status.last_ping = now()
        status.save()
        return JsonResponse({"status": "ping zapisany"})
    return JsonResponse({"error": "Tylko POST"}, status=405)

@login_required
def check_online_status(request, rezerwacja_id):
    try:
        rezerwacja = Rezerwacja.objects.get(id=rezerwacja_id)
    except Rezerwacja.DoesNotExist:
        return JsonResponse({"error": "Nie znaleziono rezerwacji"}, status=404)

    # Ustal drugą stronę (jeśli jesteś nauczycielem, szukamy ucznia i odwrotnie)
    if request.user == rezerwacja.uczen:
        other_user = rezerwacja.nauczyciel
    elif request.user == rezerwacja.nauczyciel:
        other_user = rezerwacja.uczen
    else:
        return JsonResponse({"error": "Brak dostępu do tej rezerwacji"}, status=403)

    try:
        online_status = OnlineStatus.objects.get(user=other_user, rezerwacja_id=rezerwacja_id)
        is_online = (now() - online_status.last_ping).total_seconds() < 15
    except OnlineStatus.DoesNotExist:
        is_online = False

    return JsonResponse({"online": is_online})


@login_required
def podwyzki_nauczyciele_view(request):
    if not is_accounting(request.user):
        raise PermissionDenied

    nauczyciele = User.objects.filter(profil__is_teacher=True).order_by('last_name')

    if request.method == "POST":
        nauczyciel_id = request.POST.get("nauczyciel_id")
        przedmiot = request.POST.get("przedmiot")
        poziom = request.POST.get("poziom")
        nowa_stawka = request.POST.get("stawka")

        if nauczyciel_id and przedmiot and poziom and nowa_stawka:
            nauczyciel = User.objects.get(id=nauczyciel_id)
            stawka_obj, _ = StawkaNauczyciela.objects.get_or_create(
                nauczyciel=nauczyciel,
                przedmiot=przedmiot,
                poziom=poziom
            )
            stawka_obj.stawka = nowa_stawka
            stawka_obj.save()

    cennik = PrzedmiotCennik.objects.all()
    stawki = StawkaNauczyciela.objects.all()
    nauczyciele_dane = []

    for nauczyciel in nauczyciele:
        profil = nauczyciel.profil
        przedmioty_raw = profil.przedmioty.split(',') if profil.przedmioty else []
        przedmioty = [p.strip() for p in przedmioty_raw if p.strip()]
        poziomy_raw = profil.poziom_nauczania.split(',') if profil.poziom_nauczania else []
        poziomy = [p.strip() for p in poziomy_raw if p.strip()]

        kombinacje = [(przedmiot, poziom) for przedmiot in przedmioty for poziom in poziomy]

        dane = []
        for przedmiot, poziom in kombinacje:
            stawka_indywidualna = stawki.filter(nauczyciel=nauczyciel, przedmiot=przedmiot, poziom=poziom).first()
            stawka = stawka_indywidualna.stawka if stawka_indywidualna else cennik.filter(nazwa=przedmiot, poziom=poziom).first()
            dane.append({
                "przedmiot": przedmiot,
                "poziom": poziom,
                "stawka": stawka.stawka if hasattr(stawka, 'stawka') else '',
            })

        nauczyciele_dane.append({
            "nauczyciel": nauczyciel,
            "stawki": dane
        })

    return render(request, 'ksiegowosc/podwyzki_nauczyciele.html', {
        'nauczyciele_dane': nauczyciele_dane
    })

@login_required
def virtual_room(request):
    return render(request, 'virtual_room.html')

@require_POST
@login_required
def dodaj_material_po_zajeciach(request, rezerwacja_id):
    rezerwacja = get_object_or_404(Rezerwacja, id=rezerwacja_id)
    if request.user != rezerwacja.nauczyciel:
        return HttpResponseForbidden("Brak dostępu.")

    if 'material' in request.FILES:
        rezerwacja.material_po_zajeciach = request.FILES['material']
        rezerwacja.save()

    return redirect('moj_plan_zajec')


@login_required
def zajecia_online_view(request, rezerwacja_id):
    rezerwacja = get_object_or_404(Rezerwacja, id=rezerwacja_id)
    user = request.user
    teraz = now()

    # Obsługa formularza POST (zapis linku Excalidraw przez nauczyciela)
    if request.method == 'POST' and user == rezerwacja.nauczyciel:
        link = request.POST.get('excalidraw_link')
        if link:
            rezerwacja.excalidraw_link = link
            rezerwacja.save()
            return redirect('zajecia_online', rezerwacja_id=rezerwacja.id)

    # Sprawdzenie dostępu — jeśli to NIE testowy pokój
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
        # Dla pokoju testowego (np. ID=1), dostęp mają tylko nauczyciel i uczeń tej rezerwacji
        if user != rezerwacja.uczen and user != rezerwacja.nauczyciel:
            return HttpResponseForbidden("Brak dostępu do tej tablicy.")

    # Render strony
    return render(request, 'zajecia_online.html', {
        'rezerwacja': rezerwacja,
        'is_teacher': user == rezerwacja.nauczyciel,
        'room_id': f"room-{rezerwacja.id}"
    })


@login_required
def sync_note_changes(request):
    if request.method == 'POST':
        data = request.POST.get('data')
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'virtual_room',
            {
                'type': 'note_sync',
                'message': data
            }
        )
        return JsonResponse({'status': 'success'})

async def note_sync(event):
    message = event['message']
    await self.send(text_data=message)

@login_required
def cennik_view(request):
    if not is_accounting(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        if 'zapisz_id' in request.POST:
            try:
                przedmiot_id = int(request.POST.get('zapisz_id'))
                cena = float(request.POST.get('cena'))
                przedmiot = PrzedmiotCennik.objects.get(pk=przedmiot_id)
                przedmiot.cena = cena
                przedmiot.save()
            except Exception as e:
                print("Błąd zapisu:", e)

        elif 'usun_id' in request.POST:
            try:
                przedmiot_id = int(request.POST.get('usun_id'))
                PrzedmiotCennik.objects.get(pk=przedmiot_id).delete()
            except Exception as e:
                print("Błąd usuwania:", e)

        elif 'dodaj_przedmiot' in request.POST:
            try:
                nazwa = request.POST.get('nazwa')
                poziom = request.POST.get('poziom')
                cena = float(request.POST.get('nowa_cena'))
                PrzedmiotCennik.objects.create(nazwa=nazwa, poziom=poziom, cena=cena)
            except Exception as e:
                print("Błąd dodawania:", e)

    przedmioty = PrzedmiotCennik.objects.all().order_by('nazwa', 'poziom')
    return render(request, 'ksiegowosc/cennik.html', {'przedmioty': przedmioty})

@login_required
def wyplaty_nauczycieli_view(request):
    if not is_accounting(request.user):
        raise PermissionDenied

    # Pobieramy aktualną stawkę z bazy (domyślnie 100 zł/h)
    ustawienia = UstawieniaPlatnosci.objects.first()
    cena = ustawienia.cena_za_godzine if ustawienia else 100

    nauczyciele = User.objects.filter(groups__name='Nauczyciel')
    dane = []

    for nauczyciel in nauczyciele:
        liczba_zajec = Rezerwacja.objects.filter(nauczyciel=nauczyciel).count()
        do_wyplaty = liczba_zajec * cena
        dane.append({
            'imie': nauczyciel.first_name,
            'nazwisko': nauczyciel.last_name,
            'liczba_zajec': liczba_zajec,
            'stawka': cena,
            'do_wyplaty': do_wyplaty,
        })

    return render(request, 'ksiegowosc/wyplaty_nauczycieli.html', {
        'nauczyciele': dane
    })

@login_required
def panel_nauczyciela_view(request):
    if not hasattr(request.user, 'profil') or not request.user.profil.is_teacher:
        return redirect('login')  # lub np. 'panel_ucznia', jeśli chcesz przekierować ucznia

    return render(request, 'panel_nauczyciela.html')

@login_required
def edytuj_cene_view(request):
    try:
        ustawienia = UstawieniaPlatnosci.objects.get(id=1)
    except UstawieniaPlatnosci.DoesNotExist:
        ustawienia = UstawieniaPlatnosci(id=1)
    
    if request.method == "POST":
        ustawienia.cena_za_godzine = request.POST.get("cena").replace(',', '.')
        ustawienia.numer_telefonu = request.POST.get("telefon")
        ustawienia.numer_konta = request.POST.get("konto")
        ustawienia.wlasciciel_konta = request.POST.get("wlasciciel")
        ustawienia.save()
        return redirect("panel_ksiegowosc")

    return render(request, "ksiegowosc/edytuj_cene.html", {"ustawienia": ustawienia})


@login_required
def moje_rezerwacje_ucznia_view(request):
    rezerwacje = Rezerwacja.objects.filter(uczen=request.user).select_related('nauczyciel')
    return render(request, 'moje_rezerwacje_ucznia.html', {'rezerwacje': rezerwacje})

@login_required
def moje_konto_view(request):
    profil = request.user.profil
    user = request.user

    if request.method == "POST":
        user.first_name = request.POST.get("first_name", user.first_name)
        user.last_name = request.POST.get("last_name", user.last_name)
        profil.numer_telefonu = request.POST.get("numer_telefonu", profil.numer_telefonu)

        tytuly = request.POST.getlist("tytul_naukowy")
        profil.tytul_naukowy = ",".join(tytuly)

        poziomy = request.POST.getlist("poziom_nauczania")
        profil.poziom_nauczania = ",".join(poziomy)

        przedmioty = request.POST.getlist("przedmioty")
        profil.przedmioty = ",".join(przedmioty)

        profil.opis = request.POST.get("opis", profil.opis)

        user.save()
        profil.save()

        return redirect('panel_nauczyciela')

    # pobierz cennik (stawki dla nauczyciela)
    cennik = PrzedmiotCennik.objects.all().order_by('nazwa', 'poziom')

    return render(request, "moje_konto.html", {
        "profil": profil,
        "user": user,
        "cennik": cennik
    })


@login_required
def dostepne_terminy_view(request):
    terminy = WolnyTermin.objects.select_related('nauczyciel').all()
    return render(request, 'uczen/dostepne_terminy.html', {'terminy': terminy})

@login_required
def pobierz_material_po_zajeciach(request, id):
    rez = get_object_or_404(Rezerwacja, id=id)

    if request.user not in (rez.nauczyciel, rez.uczen):
        raise Http404("Brak dostępu")

    if not rez.material_po_zajeciach:
        raise Http404("Plik nie istnieje")

    return FileResponse(rez.material_po_zajeciach.open("rb"), as_attachment=True)


def archiwum_rezerwacji_view(request):
    rok_tem = timezone.now() - timedelta(days=365)
    rezerwacje = Rezerwacja.objects.filter(
        nauczyciel=request.user,
        termin__lt=timezone.now(),
        termin__gte=rok_tem
    ).select_related('uczen')

    archiwum = {}
    for r in rezerwacje:
        miesiac = r.termin.strftime('%Y-%m')
        archiwum.setdefault(miesiac, {}).setdefault(r.uczen, []).append(r)

    return render(request, 'nauczyciel/archiwum_rezerwacji.html', {'archiwum': archiwum})


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
            # sprawdzamy kolejność
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
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        Profil.objects.create(user=user, is_teacher=False, numer_telefonu=phone)
        return redirect("login")

    return render(request, "register.html")

@login_required
def panel_ucznia_view(request):
    if not hasattr(request.user, 'profil') or request.user.profil.is_teacher:
        return redirect('login')  # lub 'panel_nauczyciela'

    return render(request, 'panel_ucznia.html', {'terminy': WolnyTermin.objects.all()})
    
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
                godzina=datetime.strptime(godzina, "%H:%M").time()
            )
        return JsonResponse({"status": "ok"})

    return JsonResponse({"error": "Invalid method"}, status=405)

@login_required
def stawki_nauczyciela_view(request):
    if not hasattr(request.user, 'profil') or not request.user.profil.is_teacher:
        return redirect('login')

    from panel.models import PrzedmiotCennik
    cennik = PrzedmiotCennik.objects.all().order_by('nazwa', 'poziom')

    return render(request, 'stawki_nauczyciela.html', {'cennik': cennik})

@login_required
def moj_plan_zajec_view(request):
    rezerwacje = Rezerwacja.objects.filter(
        nauczyciel=request.user,
        termin__gte=datetime.now()
    ).select_related('uczen')
    return render(request, 'moj_plan_zajec.html', {'rezerwacje': rezerwacje})

def wybierz_godziny_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        wybrane_daty = data.get('terminy', [])

        for wpis in wybrane_daty:
            data_str = wpis.get('data')
            godziny = wpis.get('godziny', [])

            for godzina_str in godziny:
                WolnyTermin.objects.create(
                    nauczyciel=request.user,
                    data=parse_date(data_str),
                    godzina=parse_time(godzina_str)
                )

        return JsonResponse({'status': 'success'})

    return render(request, 'wybierz_dzien_i_godzine_w_ktorej_poprowadzisz_korepetycje.html')

@login_required
def zmien_haslo_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # zapobiega wylogowaniu po zmianie hasła
            return redirect('moje_rezerwacje_ucznia')  # lub inna strona po zmianie hasła
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'zmien_haslo.html', {'form': form})
    
@staff_member_required
def panel_admina_view(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        numer_telefonu = request.POST.get('numer_telefonu')

        if User.objects.filter(username=email).exists():
            return render(request, 'admin_panel.html', {'error': 'Użytkownik już istnieje!'})

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        Profil.objects.create(user=user, is_teacher=True, numer_telefonu=numer_telefonu)

    nauczyciele = Profil.objects.filter(is_teacher=True)
    return render(request, 'admin_panel.html', {'nauczyciele': nauczyciele})

def tylko_ksiegowosc(user):
    return user.groups.filter(name='Księgowość').exists()

@login_required
@user_passes_test(tylko_ksiegowosc)
def panel_ksiegowosci_view(request):
    ustawienia = UstawieniaPlatnosci.objects.first()
    return render(request, 'ksiegowosc/panel_ksiegowosc.html', {'ustawienia': ustawienia})

@login_required
def pobierz_terminy_view(request):
    terminy = WolnyTermin.objects.filter(nauczyciel=request.user)
    lista = [{
        'data': t.data.strftime('%Y-%m-%d'),
        'godzina': t.godzina.strftime('%H:%M')
    } for t in terminy]
    return JsonResponse({'terminy': lista})

@login_required
def change_password_view(request):
    """
    Bezpieczna zmiana hasła przy użyciu wbudowanego PasswordChangeForm.
    Dostępna tylko dla zalogowanego użytkownika.
    """
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()                           # zapisuje nowe (zahaszowane) hasło
            update_session_auth_hash(request, form.user)   # nie wylogowuje użytkownika
            messages.success(request, "Hasło zostało pomyślnie zmienione.")
            # wracamy do panelu nauczyciela lub innej strony:
            return redirect("panel_nauczyciela")
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, "teacher_change_password.html", {"form": form})

@login_required
def panel_ucznia_view(request):
    terminy = WolnyTermin.objects.all().select_related('nauczyciel')
    return render(request, 'panel_ucznia.html', {'terminy': terminy})

from django.shortcuts import get_object_or_404
from .models import Rezerwacja, WolnyTermin
from django.core.files.storage import FileSystemStorage

@login_required
def zarezerwuj_zajecia_view(request):
    if request.method == 'GET':
        termin_id = request.GET.get('termin_id')
        termin = get_object_or_404(WolnyTermin, id=termin_id)
        return render(request, 'zarezerwuj_formularz.html', {'termin': termin})

    elif request.method == 'POST':
        termin_id = request.POST.get('termin_id')
        temat = request.POST.get('temat')
        plik = request.FILES.get('plik')
        termin = get_object_or_404(WolnyTermin, id=termin_id)

        # Zapisujemy termin jako datetime
        termin_datetime = datetime.combine(termin.data, termin.godzina)

        Rezerwacja.objects.create(
            uczen=request.user,
            nauczyciel=termin.nauczyciel,
            termin=termin_datetime,
            temat=temat,
            plik=plik
        )

        termin.delete()  # usuwamy wolny termin, bo został zarezerwowany
        return redirect('panel_ucznia')

    return HttpResponseRedirect('/')
