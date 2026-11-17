from django.urls import path

from . import views

app_name = "vmbackups"

urlpatterns = [
    path("targets/", views.targets, name="targets"),
    path("targets/<int:target_id>/", views.target, name="target"),
]
