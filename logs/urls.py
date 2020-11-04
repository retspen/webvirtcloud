from django.urls import path

from . import views

urlpatterns = [
    path("vm_logs/<vname>/", views.vm_logs, name="vm_logs"),
]
