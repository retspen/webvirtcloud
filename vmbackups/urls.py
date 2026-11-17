from django.urls import path

from . import views

app_name = "vmbackups"

urlpatterns = [
    path("", views.index, name="index"),
    path("<uuid:uuid>/delete/", views.delete, name="delete"),
    path("<uuid:uuid>/restore/", views.restore, name="restore"),
    path("<uuid:uuid>/restore-over/", views.restore_over, name="restore_over"),
    path("<uuid:uuid>/restore-disk/", views.restore_disk, name="restore_disk"),
    path("schedules/", views.policies, name="policies"),
    path("schedules/new/", views.policy_new, name="policy_new"),
    path("schedules/<int:policy_id>/", views.policy, name="policy"),
    path("targets/", views.targets, name="targets"),
    path("targets/new/", views.target_new, name="target_new"),
    path("targets/<int:target_id>/", views.target, name="target"),
    path("vm/<int:instance_id>/create/", views.create, name="create"),
]
