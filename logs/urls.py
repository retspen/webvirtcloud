from django.urls import path

from . import views

urlpatterns = [
    path("vm_logs/<int:pk>/", views.vm_logs, name="vm_logs"),
]
