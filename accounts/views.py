from admin.decorators import superuser_only
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from instances.models import Instance

from accounts.forms import EmailOTPForm, ProfileForm, UserSSHKeyForm
from accounts.models import *

from . import forms
from .utils import get_user_totp_device, send_email_with_otp


def profile(request):
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
    profile_form = ProfileForm(request.POST or None, instance=request.user)
    ssh_key_form = UserSSHKeyForm()

    if profile_form.is_valid():
        profile_form.save()
        messages.success(request, _("Profile updated"))
        return redirect("accounts:profile")

    return render(
        request,
        "profile.html",
        {
            "publickeys": publickeys,
            "profile_form": profile_form,
            "ssh_key_form": ssh_key_form,
        },
    )


def ssh_key_create(request):
    key_form = UserSSHKeyForm(request.POST or None, user=request.user)
    if key_form.is_valid():
        key_form.save()
        messages.success(request, _("SSH key added"))
        return redirect("accounts:profile")

    return render(
        request,
        "common/form.html",
        {
            "form": key_form,
            "title": _("Add SSH key"),
        },
    )


def ssh_key_delete(request, pk):
    ssh_key = get_object_or_404(UserSSHKey, pk=pk, user=request.user)
    if request.method == "POST":
        ssh_key.delete()
        messages.success(request, _("SSH key deleted"))
        return redirect("accounts:profile")

    return render(
        request,
        "common/confirm_delete.html",
        {
            "object": ssh_key,
            "title": _("Delete SSH key"),
        },
    )


@superuser_only
def account(request, user_id):
    user = User.objects.get(id=user_id)
    user_insts = UserInstance.objects.filter(user_id=user_id)
    instances = Instance.objects.all().order_by("name")
    publickeys = UserSSHKey.objects.filter(user_id=user_id)

    return render(
        request,
        "account.html",
        {
            "user": user,
            "user_insts": user_insts,
            "instances": instances,
            "publickeys": publickeys,
            "otp_enabled": settings.OTP_ENABLED,
        },
    )


@permission_required("accounts.change_password", raise_exception=True)
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)

    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # Important!
        messages.success(request, _("Password Changed"))
        return redirect("accounts:profile")

    return render(request, "accounts/change_password_form.html", {"form": form})


@superuser_only
def user_instance_create(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    form = forms.UserInstanceForm(request.POST or None, initial={"user": user})
    if form.is_valid():
        form.save()
        return redirect(reverse("accounts:account", args=[user.id]))

    return render(
        request,
        "common/form.html",
        {
            "form": form,
            "title": _("Create User Instance"),
        },
    )


@superuser_only
def user_instance_update(request, pk):
    user_instance = get_object_or_404(UserInstance, pk=pk)
    form = forms.UserInstanceForm(request.POST or None, instance=user_instance)
    if form.is_valid():
        form.save()
        return redirect(reverse("accounts:account", args=[user_instance.user.id]))

    return render(
        request,
        "common/form.html",
        {
            "form": form,
            "title": _("Update User Instance"),
        },
    )


@superuser_only
def user_instance_delete(request, pk):
    user_instance = get_object_or_404(UserInstance, pk=pk)
    if request.method == "POST":
        user = user_instance.user
        user_instance.delete()
        next = request.GET.get("next", None)
        if next:
            return redirect(next)
        else:
            return redirect(reverse("accounts:account", args=[user.id]))

    return render(
        request,
        "common/confirm_delete.html",
        {"object": user_instance},
    )


def email_otp(request):
    form = EmailOTPForm(request.POST or None)
    if form.is_valid():
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(email=form.cleaned_data["email"])
        except UserModel.DoesNotExist:
            pass
        else:
            device = get_user_totp_device(user)
            send_email_with_otp(user, device)

        messages.success(
            request, _("OTP Sent to %(email)s") % {"email": form.cleaned_data["email"]}
        )
        return redirect("accounts:login")

    return render(
        request,
        "accounts/email_otp_form.html",
        {
            "form": form,
            "title": _("Email OTP"),
        },
    )


@superuser_only
def admin_email_otp(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    device = get_user_totp_device(user)
    if user.email != "":
        send_email_with_otp(user, device)
        messages.success(
            request, _("OTP QR code was emailed to user %(user)s") % {"user": user}
        )
    else:
        messages.error(request, _("User email not set, failed to send QR code"))
    return redirect("accounts:account", user.id)
