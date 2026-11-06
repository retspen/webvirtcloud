from django.conf import settings
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerSplitView,
)
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound

from appsettings.views import appsettings
from console.views import console
from instances.views import index


@extend_schema(exclude=True)
@api_view(["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"])
def api_not_found(request):
    """An API URL that names nothing: JSON, after the API's authentication, as
    every other API answer. Only one with a trailing slash: one without is
    redirected to it first."""
    raise NotFound


urlpatterns = [
    path("", index, name="index"),
    path("admin/", include(("admin.urls", "admin"), namespace="admin")),
    path("accounts/", include("accounts.urls")),
    path("appsettings/", appsettings, name="appsettings"),
    path("computes/", include("computes.urls")),
    path("console/<int:compute_id>/<str:uuid>/", console, name="console"),
    path("datasource/", include("datasource.urls")),
    path("instances/", include("instances.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("logs/", include("logs.urls")),
    path("jobs/", include("operations.urls")),
    path('api/v1/', include("webvirtcloud.urls-api")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    re_path(r"^swagger\.(?P<format>json|yaml)$", SpectacularAPIView.as_view(), name="schema-json"),
    path("swagger/", SpectacularSwaggerSplitView.as_view(url_name="schema"), name="schema-swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="schema-redoc"),
    re_path(r"^api/(?:.*/)?$", api_not_found),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [
            path("__debug__/", include(debug_toolbar.urls)),
        ]
    except ImportError:
        pass

