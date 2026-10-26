import logging
import os
from datetime import timedelta

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
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.apps import admin_password_path
from logs.audit import audit, audit_vm, changed_fields, failed, snapshot

from accounts.forms import ApiTokenForm, EmailOTPForm, ProfileForm, UserSSHKeyForm
from accounts.models import ApiToken, User, UserAttributes, UserInstance, UserSSHKey

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
            "api_tokens": ApiToken.objects.filter(user=request.user),
            "api_token_form": ApiTokenForm(),
        },
    )


@require_POST
@never_cache
def api_token_create(request):
    """A REST API token, shown once: only its digest is kept. It is made in
    a session that passed the login, and its OTP when OTP is on."""
    form = ApiTokenForm(request.POST)
    if not form.is_valid():
        return render(request, "common/form.html", {"form": form, "title": _("Create an API token")})
    ApiToken.objects.filter(user=request.user, expiry__lt=timezone.now()).delete()
    if ApiToken.objects.filter(user=request.user).count() >= ApiToken.LIMIT:
        form.add_error(None, _("A user has at most %(limit)s API tokens: delete one first.") % {"limit": ApiToken.LIMIT})
        return render(request, "common/form.html", {"form": form, "title": _("Create an API token")})
    name, days = form.cleaned_data["name"], form.cleaned_data["days"]
    with audit(request, None, f"API token {name}", "add"):
        _token, key = ApiToken.objects.create(request.user, expiry=timedelta(days=days) if days else None, name=name)
    return render(request, "api_token_created.html", {"name": name, "key": key})


def api_token_delete(request, token_key, user_id=None):
    """Delete one of the user's own tokens or, given user_id, a superuser
    deletes one of that user's."""
    if user_id is None:
        token = get_object_or_404(ApiToken, token_key=token_key, user=request.user)
        subject = f"API token {token.name}"
        back = reverse("accounts:profile")
    elif request.user.is_superuser:
        token = get_object_or_404(ApiToken, token_key=token_key, user_id=user_id)
        subject = f"API token {token.name} of {token.user.username}"
        back = reverse("accounts:account", args=[user_id])
    else:
        raise PermissionDenied
    if request.method == "POST":
        with audit(request, None, subject, "delete"):
            token.delete()
        messages.success(request, _("API token deleted"))
        return redirect(back + "#apitokens")

    return render(
        request,
        "common/confirm_delete.html",
        {
            "object": subject,
            "title": _("Delete API token"),
            "consequence": _("Scripts and tools that use it can no longer reach the API."),
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
    user = get_object_or_404(User, id=user_id)
    user_insts = UserInstance.objects.filter(user_id=user_id).select_related("instance")
    publickeys = UserSSHKey.objects.filter(user_id=user_id)

    return render(
        request,
        "account.html",
        {
            "user": user,
            "user_insts": user_insts,
            "publickeys": publickeys,
            "api_tokens": ApiToken.objects.filter(user_id=user_id),
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
        with audit_vm(request, instance, f"add owner {form.cleaned_data['user'].username}"):
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
        with audit_vm(request, instance, "change owner") as entry:
            form.save()
            fields = changed_fields(before, snapshot(user_instance))
            entry.action = f"change owner {user_instance.user.username}: " + ", ".join(fields)
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
        with audit_vm(request, instance, f"remove owner {user.username}"):
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
