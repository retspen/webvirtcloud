from django.conf import settings
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from appsettings.views import appsettings
from console.views import console
from instances.views import index

# Fallback for existing installations where REST_FRAMEWORK.DEFAULT_SCHEMA_CLASS is not configured in settings.py
user_rf = getattr(settings, "REST_FRAMEWORK", None)
if not user_rf or "DEFAULT_SCHEMA_CLASS" not in user_rf:
    try:
        from rest_framework.settings import api_settings
        from drf_spectacular.openapi import AutoSchema

        api_settings.DEFAULT_SCHEMA_CLASS = AutoSchema
    except (ImportError, AttributeError):
        pass

urlpatterns = [
    path("", index, name="index"),
    path("admin/", include(("admin.urls", "admin"), namespace="admin")),
    path("accounts/", include("accounts.urls")),
    path("appsettings/", appsettings, name="appsettings"),
    path("computes/", include("computes.urls")),
    path("console/", console, name="console"),
    path("datasource/", include("datasource.urls")),
    path("instances/", include("instances.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("logs/", include("logs.urls")),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('api/v1/', include("webvirtcloud.urls-api")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    re_path(r"^swagger\.(?P<format>json|yaml)$", SpectacularAPIView.as_view(), name="schema-json"),
    path("swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="schema-swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="schema-redoc"),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [
            path("__debug__/", include(debug_toolbar.urls)),
        ]
    except ImportError:
        pass

