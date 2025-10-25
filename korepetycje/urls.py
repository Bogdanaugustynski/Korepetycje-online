from django.contrib import admin
from django.urls import path, include
from django.contrib.staticfiles.storage import staticfiles_storage
from django.views.generic.base import RedirectView
from django.http import HttpResponse  


urlpatterns = [
    path("ukryty_admin/", admin.site.urls),
    path('', include('panel.urls')),
    path("favicon.ico", lambda request: HttpResponse(status=204)),
]
from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

