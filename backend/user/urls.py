from django.urls import path

from .views import *

urlpatterns = [
    path('', UserView.as_view(), name="user_view"),
]