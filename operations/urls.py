from django.urls import path

from . import views

app_name = "operations"
urlpatterns = [
    path("", views.jobs, name="jobs"),
    path("<uuid:pk>/", views.job, name="job"),
    path("<uuid:pk>/cancel/", views.cancel, name="cancel"),
    path("<uuid:pk>/resolve/", views.resolve, name="resolve"),
]
