from django import forms
from .models import Profil

class ProfilForm(forms.ModelForm):
    class Meta:
        model = Profil
        fields = ['numer_telefonu', 'tytul_naukowy', 'poziom_nauczania', 'opis']
        widgets = {
            'poziom_nauczania': forms.CheckboxSelectMultiple,
            'opis': forms.Textarea(attrs={'rows': 4}),
        }
