# panel/templatetags/filelinks.py
from django import template
from django.urls import reverse

register = template.Library()

@register.filter
def file_link(filefield):
    """
    Zwraca bezpieczny URL do pliku:
    - jeśli storage udostępnia publiczny .url -> używa go
    - w innym wypadku -> zwraca link do naszego widoku pobierania
    """
    if not filefield:
        return ""
    try:
        url = filefield.url  # może rzucić ValueError przy FileSystemStorage bez MEDIA_URL
        if url:
            return url
    except Exception:
        pass
    # fallback: serwujemy przez nasz widok
    return reverse("pobierz_plik", args=[getattr(filefield, "instance", None).pk, filefield.name])
