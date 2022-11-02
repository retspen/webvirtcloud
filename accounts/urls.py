from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from django_otp.forms import OTPAuthenticationForm

from . import views

app_name = "accounts"

urlpatterns = [
    path("logout/", LogoutView.as_view(template_name="logout.html"), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("profile/<int:user_id>/", views.account, name="account"),
    path("change_password/", views.change_password, name="change_password"),
    path(
        "user_instance/create/<int:user_id>/",
        views.user_instance_create,
        name="user_instance_create",
    ),
    path(
        "user_instance/<int:pk>/update/",
        views.user_instance_update,
        name="user_instance_update",
    ),
    path(
        "user_instance/<int:pk>/delete/",
        views.user_instance_delete,
        name="user_instance_delete",
    ),
    path("ssh_key/create/", views.ssh_key_create, name="ssh_key_create"),
    path("ssh_key/<int:pk>/delete/", views.ssh_key_delete, name="ssh_key_delete"),
]

if settings.OTP_ENABLED:
    urlpatterns += [
        path(
            "login/",
            LoginView.as_view(
                template_name="accounts/otp_login.html",
                authentication_form=OTPAuthenticationForm,
            ),
            name="login",
        ),
        path("email_otp/", views.email_otp, name="email_otp"),
        path(
            "admin_email_otp/<int:user_id>/",
            views.admin_email_otp,
            name="admin_email_otp",
        ),
    ]
else:
    urlpatterns += (
        path("login/", LoginView.as_view(template_name="login.html"), name="login"),
    )
