from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("ukryty_admin/", admin.site.urls),
    path('', include('panel.urls')),
    path("", include("zajecia.urls_webrtc")),
]
from django.conf import settings
from django.conf.urls.static import static

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
