"""webvirtcloud URL Configuration
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings

from rest_framework_swagger.views import get_swagger_view

admin.site.site_header = "Webvirtcloud"

api_urlpatterns = [
    path("rest-auth/registration/", include("rest_auth.registration.urls")),
    path("rest-auth/", include("rest_auth.urls")),
    path("user/", include("user.urls"))
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_urlpatterns)),
]

if settings.DEBUG:
    schema_view = get_swagger_view(title="Webvirtcloud API")
    urlpatterns += [path('docs/', schema_view)]