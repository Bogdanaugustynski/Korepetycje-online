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

    # Pole z Profil
    telefon    = forms.CharField(label="Telefon", max_length=32, required=False)
    # Jeśli w modelu masz inną nazwę (np. numer_telefonu), podmień w __init__ i save().

    class Meta:
        model  = User
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user:
            profil, _ = Profil.objects.get_or_create(user=self.user)
            # ZMIEŃ TUTAJ jeżeli masz inną nazwę:
            self.fields["telefon"].initial = getattr(profil, "telefon", "")

    def save(self, commit=True):
        user = super().save(commit=commit)
        profil, _ = Profil.objects.get_or_create(user=user)
        # ZMIEŃ TUTAJ jeżeli masz inną nazwę:
        profil.telefon = self.cleaned_data.get("telefon", "")
        profil.save()
        return user


class StudentPasswordChangeForm(PasswordChangeForm):
    old_password  = forms.CharField(label="Obecne hasło", widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="Nowe hasło", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Powtórz nowe hasło", widget=forms.PasswordInput)

