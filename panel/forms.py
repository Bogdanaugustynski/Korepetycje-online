from django import forms
from .models import Profil
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User

class ProfilForm(forms.ModelForm):
    class Meta:
        model = Profil
        fields = ['numer_telefonu', 'tytul_naukowy', 'poziom_nauczania', 'opis']
        widgets = {
            'poziom_nauczania': forms.CheckboxSelectMultiple,
            'opis': forms.Textarea(attrs={'rows': 4}),
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

