import logging
import os

from admin.decorators import superuser_only
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.core.cache import cache
from django.http import Http404
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.apps import admin_password_path
from instances.models import Instance
from logs.audit import audit, changed_fields, failed, snapshot

from accounts.forms import EmailOTPForm, ProfileForm, UserSSHKeyForm
from accounts.models import User, UserAttributes, UserInstance, UserSSHKey

from . import forms
from .utils import get_existing_totp_device, get_user_totp_device, send_email_with_otp


def profile(request):
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)
    before = snapshot(request.user)
    profile_form = ProfileForm(request.POST or None, instance=request.user)
    ssh_key_form = UserSSHKeyForm()

    if profile_form.is_valid():
        with audit(request, None, f"User {request.user.username}", "change") as entry:
            profile_form.save()
            fields = changed_fields(before, snapshot(request.user))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields
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
        with audit(request, None, f"SSH key {key_form.cleaned_data['keyname']}", "add"):
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
        with audit(request, None, f"SSH key {ssh_key.keyname}", "delete"):
            ssh_key.delete()
        messages.success(request, _("SSH key deleted"))
        return redirect("accounts:profile")

    return render(
        request,
        "common/confirm_delete.html",
        {
            "object": ssh_key,
            "title": _("Delete SSH key"),
            "consequence": _("VMs that already have it keep it; VMs created from now on do not get it."),
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


@login_required
def change_password(request):
    must_change = UserAttributes.objects.filter(
        user=request.user, must_change_password=True
    ).exists()
    if not must_change and not request.user.has_perm("accounts.change_password"):
        raise PermissionDenied
    form = PasswordChangeForm(request.user, request.POST or None)

    if form.is_valid():
        with audit(request, None, f"User {request.user.username}", "change password"), transaction.atomic():
            user = form.save()
            UserAttributes.objects.filter(user=user).update(must_change_password=False)
        update_session_auth_hash(request, user)
        request.session.pop("must_change_password", None)
        if must_change and not UserAttributes.objects.filter(must_change_password=True).exists():
            try:
                os.remove(admin_password_path())
            except FileNotFoundError:
                pass
            except OSError:
                logging.getLogger(__name__).warning("Could not remove the generated admin password file")
        messages.success(request, _("Password Changed"))
        return redirect("accounts:profile")

    return render(request, "accounts/change_password_form.html", {"form": form})


@superuser_only
def user_instance_create(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    form = forms.UserInstanceForm(request.POST or None, initial={"user": user})
    if form.is_valid():
        instance = form.cleaned_data["instance"]
        subject = f"VM {instance.name} owner {form.cleaned_data['user'].username}"
        with audit(request, instance.compute, subject, "add", instance=instance.name):
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
    instance, before = user_instance.instance, snapshot(user_instance)
    form = forms.UserInstanceForm(request.POST or None, instance=user_instance)
    if form.is_valid():
        subject = f"VM {instance.name} owner {user_instance.user.username}"
        with audit(request, instance.compute, subject, "change", instance=instance.name) as entry:
            form.save()
            fields = changed_fields(before, snapshot(user_instance))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields
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
        user, instance = user_instance.user, user_instance.instance
        with audit(request, instance.compute, f"VM {instance.name} owner {user.username}", "remove",
                   instance=instance.name):
            user_instance.delete()
        next_url = request.GET.get("next", None)
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect(reverse("accounts:account", args=[user.id]))

    return render(
        request,
        "common/confirm_delete.html",
        {"object": user_instance,
         "consequence": _("The user loses access to this VM; the VM itself is not changed.")},
    )


# a user gets at most one OTP mail per this many seconds
EMAIL_OTP_INTERVAL = 300


@login_not_required
def email_otp(request):
    """
    "Lost OTP?": mail the OTP QR code to the user with this address. Open to
    anyone, so it mails only one exact, active match, at most once per
    EMAIL_OTP_INTERVAL, and answers the same in every case.
    """
    if not settings.OTP_ENABLED:
        raise Http404
    form = EmailOTPForm(request.POST or None)
    if form.is_valid():
        users = list(get_user_model().objects.filter(email__iexact=form.cleaned_data["email"], is_active=True)[:2])
        # the cache is per process: with several workers the bound is per worker
        if len(users) == 1 and cache.add(f"email_otp:{users[0].pk}", True, EMAIL_OTP_INTERVAL):
            user = users[0]
            # resend only to a user who already enrolled: creating a device here
            # would let anyone who knows an email force OTP on that account
            device = get_existing_totp_device(user)
            if device is not None:
                try:
                    send_email_with_otp(user, device)
                except Exception:
                    logging.getLogger(__name__).exception("Could not mail the OTP QR code to user %s", user.pk)

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


@require_POST
@superuser_only
def admin_email_otp(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    subject = f"User {user.username}"
    if user.email != "":
        with audit(request, None, subject, "mail OTP QR code"):
            send_email_with_otp(user, get_user_totp_device(user))
        messages.success(
            request, _("OTP QR code was emailed to user %(user)s") % {"user": user}
        )
    else:
        failed(request, None, subject, "mail OTP QR code", "no email address")
        messages.error(request, _("User email not set, failed to send QR code"))
    return redirect("accounts:account", user.id)
