from django.urls import path

from . import views

app_name = "vmbackups"

urlpatterns = [
    path("", views.index, name="index"),
    path("<uuid:uuid>/delete/", views.delete, name="delete"),
    path("targets/", views.targets, name="targets"),
    path("targets/<int:target_id>/", views.target, name="target"),
    path("vm/<int:instance_id>/create/", views.create, name="create"),
]
