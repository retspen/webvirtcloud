from datetime import timedelta

from accounts.models import Instance, UserAttributes, UserInstance
from appsettings.settings import app_settings
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from instances.models import InstanceTombstone
from logs.audit import audit, changed_fields, snapshot
from logs.models import Logs

from . import forms
from .decorators import superuser_only


def group_snapshot(group):
    """snapshot() of a group with its members, which are a reverse relation snapshot() does not see."""
    return snapshot(group) | {"users": frozenset(group.user_set.values_list("pk", flat=True))}


@superuser_only
def group_list(request):
    groups = Group.objects.all()
    return render(
        request,
        "admin/group_list.html",
        {
            "groups": groups,
        },
    )


@superuser_only
def group_create(request):
    form = forms.GroupForm(request.POST or None)
    if form.is_valid():
        with audit(request, None, f"Group {form.cleaned_data['name']}", "add"):
            form.save()
        return redirect("admin:group_list")

    return render(
        request,
        "common/form.html",
        {
            "form": form,
            "title": _("Create Group"),
        },
    )


@superuser_only
def group_update(request, pk):
    group = get_object_or_404(Group, pk=pk)
    subject, before = f"Group {group.name}", group_snapshot(group)
    form = forms.GroupForm(request.POST or None, instance=group)
    if form.is_valid():
        with audit(request, None, subject, "change") as entry:
            form.save()
            fields = changed_fields(before, group_snapshot(group))
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields
        return redirect("admin:group_list")

    return render(
        request,
        "common/form.html",
        {
            "form": form,
            "title": _("Update Group"),
        },
    )


@superuser_only
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        with audit(request, None, f"Group {group.name}", "delete"):
            group.delete()
        return redirect("admin:group_list")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": group, "consequence": _("Its members stay but lose the permissions it gave them.")},
    )


# an administrator who blocks, deletes or demotes their own account is out of
# these pages at once, and may have been the last one
OWN_ACCOUNT = _("You cannot block, delete or demote your own account")


@superuser_only
def user_list(request):
    # API tokens that still work: an expired one is deleted only at the user's next create
    live = Q(auth_token_set__expiry__isnull=True) | Q(auth_token_set__expiry__gt=timezone.now())
    users = User.objects.annotate(api_tokens=Count("auth_token_set", filter=live))
    return render(
        request,
        "admin/user_list.html",
        {
            "users": users,
            "title": _("Users"),
        },
    )


@superuser_only
def user_create(request):
    user_form = forms.UserCreateForm(request.POST or None)
    attributes_form = forms.UserAttributesForm(request.POST or None)
    if user_form.is_valid() and attributes_form.is_valid():
        with audit(request, None, f"User {user_form.cleaned_data['username']}", "add"), transaction.atomic():
            user = user_form.save()
            attributes = attributes_form.save(commit=False)
            attributes.user = user
            attributes.save()
            add_default_instances(user)
        return redirect("admin:user_list")

    return render(
        request,
        "admin/user_form.html",
        {
            "user_form": user_form,
            "attributes_form": attributes_form,
            "title": _("Create User"),
        },
    )


@superuser_only
def user_update(request, pk):
    user = get_object_or_404(User, pk=pk)
    attributes, attributes_created = UserAttributes.objects.get_or_create(user=user)
    subject = f"User {user.username}"
    before, before_attributes = snapshot(user), snapshot(attributes)
    user_form = forms.UserForm(request.POST or None, instance=user)
    attributes_form = forms.UserAttributesForm(
        request.POST or None, instance=attributes
    )
    valid = user_form.is_valid() and attributes_form.is_valid()
    if valid and user == request.user and not (user_form.cleaned_data["is_active"] and user_form.cleaned_data["is_superuser"]):
        user_form.add_error(None, OWN_ACCOUNT)
        valid = False
    if valid:
        with audit(request, None, subject, "change") as entry:
            user_form.save()
            attributes_form.save()
            fields = set(changed_fields(before, snapshot(user))) | set(changed_fields(before_attributes, snapshot(attributes)))
            fields = sorted(fields - {"password", "last_login"})
            entry.action = "change " + ", ".join(fields)
            entry.skip = not fields
        next_url = request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(next_url)
        return redirect("admin:user_list")

    return render(
        request,
        "admin/user_form.html",
        {
            "user_form": user_form,
            "attributes_form": attributes_form,
            "edited_user": user,
            "title": _("Update User"),
        },
    )


@superuser_only
def user_update_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = forms.AdminPasswordForm(user, request.POST)
        if form.is_valid():
            with audit(request, None, f"User {user.username}", "set password"), transaction.atomic():
                user = form.save()
                UserAttributes.objects.update_or_create(
                    user=user, defaults={"must_change_password": form.cleaned_data["must_change_password"]})
            update_session_auth_hash(request, user)  # Important!
            messages.success(
                request, _("Password changed for %(user)s") % {"user": user.username}
            )
            return redirect("admin:user_list")
        else:
            messages.error(request, _("Wrong Data Provided"))
    else:
        form = forms.AdminPasswordForm(user)

    return render(
        request,
        "accounts/change_password_form.html",
        {
            "form": form,
            "user": user.username,
        },
    )


@superuser_only
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, OWN_ACCOUNT)
        return redirect("admin:user_list")
    if request.method == "POST":
        with audit(request, None, f"User {user.username}", "delete"):
            user.delete()
        return redirect("admin:user_list")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": user,
         "consequence": _("Their access to VMs, SSH keys and settings go; the VMs themselves stay.")},
    )


@require_POST
@superuser_only
def user_block(request, pk):
    user: User = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, OWN_ACCOUNT)
        return redirect("admin:user_list")
    with audit(request, None, f"User {user.username}", "block") as entry:
        entry.skip = not user.is_active  # already blocked
        user.is_active = False
        user.save()
    return redirect("admin:user_list")


@require_POST
@superuser_only
def user_unblock(request, pk):
    user: User = get_object_or_404(User, pk=pk)
    with audit(request, None, f"User {user.username}", "unblock") as entry:
        entry.skip = user.is_active  # not blocked
        user.is_active = True
        user.save()
    return redirect("admin:user_list")


@superuser_only
def logs(request):
    paginator = Paginator(Logs.objects.order_by("-date", "-id"), int(app_settings.LOGS_PER_PAGE))
    logs = paginator.get_page(request.GET.get("page"))
    return render(request, "admin/logs.html", {"logs": logs})


@superuser_only
def tombstone_list(request):
    """The owners kept for VMs that vanished from their compute, in case the
    same UUID comes back."""
    tombstones = list(InstanceTombstone.objects.order_by("-removed"))
    ids = {owner["user"] for tombstone in tombstones for owner in tombstone.owners}
    names = dict(User.objects.filter(id__in=ids).values_list("id", "username"))
    retention = timedelta(days=getattr(settings, "INSTANCE_OWNERSHIP_RETENTION_DAYS", 30))
    for tombstone in tombstones:
        tombstone.owner_names = [names.get(owner["user"], _("deleted user")) for owner in tombstone.owners]
        tombstone.expires = tombstone.removed + retention
    return render(request, "admin/tombstone_list.html", {"tombstones": tombstones})


@superuser_only
def tombstone_delete(request, pk):
    tombstone = get_object_or_404(InstanceTombstone, pk=pk)
    if request.method == "POST":
        with audit(request, None, f"Removed VM {tombstone.name} ({tombstone.uuid})", "delete"):
            tombstone.delete()
        return redirect("admin:tombstone_list")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": tombstone,
         "consequence": _("Its owners no longer get the VM back if its UUID shows up again.")},
    )


def add_default_instances(user):
    """
    Adds instances listed in NEW_USER_DEFAULT_INSTANCES to user
    """
    existing_instances = UserInstance.objects.filter(user=user)
    if not existing_instances:
        for instance_name in settings.NEW_USER_DEFAULT_INSTANCES:
            instance = Instance.objects.get(name=instance_name)
            user_instance = UserInstance(user=user, instance=instance)
            user_instance.save()
