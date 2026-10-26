from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views
from .forms import LoginForm
from .otp import SingleDeviceOTPForm

app_name = "accounts"

urlpatterns = [
    path("logout/", LogoutView.as_view(template_name="logout.html"), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("profile/<int:user_id>/", views.account, name="account"),
    path("profile/<int:user_id>/api_token/<str:token_key>/delete/", views.api_token_delete,
         name="account_api_token_delete"),
    path("profile/<int:user_id>/ssh_key/<int:pk>/delete/", views.ssh_key_delete, name="account_ssh_key_delete"),
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
    path("api_token/create/", views.api_token_create, name="api_token_create"),
    path("api_token/created/", views.api_token_created, name="api_token_created"),
    path("api_token/<str:token_key>/delete/", views.api_token_delete, name="api_token_delete"),
    path("email_otp/", views.email_otp, name="email_otp"),
    path(
        "admin_email_otp/<int:user_id>/",
        views.admin_email_otp,
        name="admin_email_otp",
    ),
]

if settings.OTP_ENABLED:
    urlpatterns += [
        path(
            "login/",
            LoginView.as_view(
                template_name="accounts/otp_login.html",
                authentication_form=SingleDeviceOTPForm,
                redirect_authenticated_user=True,
            ),
            name="login",
        ),
    ]
else:
    urlpatterns += (
        path("login/", LoginView.as_view(template_name="login.html", authentication_form=LoginForm,
                                           redirect_authenticated_user=True), name="login"),
    )
