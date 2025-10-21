from django import forms
from .models import Profil
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import SiteLegalConfig

class UserBasicForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]


class ProfilForm(forms.ModelForm):
    class Meta:
        model = Profil
        fields = [
            # stare pola
            'numer_telefonu', 'tytul_naukowy', 'poziom_nauczania', 'opis',
            # nowe dane ucznia
            'extra_phone', 'city', 'address_line', 'birth_date',
            # dane opiekuna
            'guardian_name', 'guardian_email', 'guardian_phone',
            # zgody i prywatność
            'marketing_email', 'marketing_sms', 'gdpr_edu_consent', 'recording_consent',
        ]
        widgets = {
            'opis': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Krótki opis lub informacje dodatkowe...'}),
            'address_line': forms.TextInput(attrs={'placeholder': 'Ulica, numer domu/mieszkania'}),
            'city': forms.TextInput(attrs={'placeholder': 'Miasto'}),
            'accessibility_notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Uwagi dotyczące nauki, potrzeb edukacyjnych itp.'}),
        }
        labels = {
            'numer_telefonu': 'Numer telefonu',
            'extra_phone': 'Drugi numer telefonu (opcjonalnie)',
            'city': 'Miasto',
            'address_line': 'Adres zamieszkania',
            'guardian_name': 'Imię i nazwisko opiekuna',
            'guardian_email': 'E-mail opiekuna',
            'guardian_phone': 'Telefon opiekuna',
            'marketing_email': 'Zgoda na kontakt e-mail',
            'marketing_sms': 'Zgoda na kontakt SMS',
            'gdpr_edu_consent': 'Zgoda na przetwarzanie danych edukacyjnych',
            'accessibility_notes': 'Uwagi o potrzebach edukacyjnych',
        }



from .models import Profil  # dopasuj, jeśli Profil jest w innej appce

class StudentAccountForm(forms.ModelForm):
    # Pola z User
    first_name = forms.CharField(label="Imię", max_length=150, required=True)
    last_name  = forms.CharField(label="Nazwisko", max_length=150, required=True)
    email      = forms.EmailField(label="E-mail", required=True)

    # Pole „telefon” w formularzu (niezależne od nazwy w modelu)
    telefon    = forms.CharField(label="Telefon", max_length=32, required=False)

    class Meta:
        model  = User
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Wczytaj profil i ustaw initial zgodnie z tym, co *istnieje* w modelu
        if self.user:
            profil, _ = Profil.objects.get_or_create(user=self.user)
            # Obsługa dwóch możliwych nazw w modelu:
            tel_val = ""
            if hasattr(profil, "telefon"):
                tel_val = getattr(profil, "telefon", "") or ""
            elif hasattr(profil, "numer_telefonu"):
                tel_val = getattr(profil, "numer_telefonu", "") or ""
            self.fields["telefon"].initial = tel_val

    def save(self, commit=True):
        user = super().save(commit=commit)
        profil, _ = Profil.objects.get_or_create(user=user)
        tel_form = self.cleaned_data.get("telefon", "")

        # Zapisz do właściwego pola w modelu
        if hasattr(profil, "telefon"):
            profil.telefon = tel_form
        elif hasattr(profil, "numer_telefonu"):
            profil.numer_telefonu = tel_form
        else:
            # Awaryjnie – jeśli kiedyś zmienisz nazwę po raz trzeci, wiesz gdzie poprawić ;)
            pass

        profil.save()
        return user



class StudentPasswordChangeForm(PasswordChangeForm):
    old_password  = forms.CharField(label="Obecne hasło", widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="Nowe hasło", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Powtórz nowe hasło", widget=forms.PasswordInput)

class SiteLegalConfigForm(forms.ModelForm):
    class Meta:
        model = SiteLegalConfig
        fields = [
            "site_owner", "site_address", "site_email", "site_url",
            "payment_operator", "processors", "cookies_desc", "video_tools",
        ]
        widgets = {
            "site_owner": forms.TextInput(attrs={"class": "inp"}),
            "site_address": forms.TextInput(attrs={"class": "inp"}),
            "site_email": forms.EmailInput(attrs={"class": "inp"}),
            "site_url": forms.TextInput(attrs={"class": "inp"}),
            "payment_operator": forms.TextInput(attrs={"class": "inp"}),
            "processors": forms.Textarea(attrs={"class": "inp", "rows": 2}),
            "cookies_desc": forms.Textarea(attrs={"class": "inp", "rows": 2}),
            "video_tools": forms.Textarea(attrs={"class": "inp", "rows": 2}),
        }