from datetime import timedelta

from accounts.models import ApiToken, Instance, UserAttributes, UserInstance
from appsettings.settings import app_settings
from computes.utils import lock_ownership
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import Group, Permission, User
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.views.decorators.debug import sensitive_post_parameters
from instances.models import InstanceTombstone
from instances.report import workbook
from logs.audit import audit, changed_fields, snapshot
from logs.models import Logs
from vrtManager import util

from . import forms
from .decorators import superuser_only


def form_seen(*snapshots):
    """The fingerprint of what an edit form shows (snapshot()s), which it sends
    back: a form opened before another administrator's change would undo it.
    A password or a login of the user is no change of the form."""
    shown = [sorted((key, sorted(value) if isinstance(value, frozenset) else value)
                    for key, value in snap.items() if key not in ("password", "last_login")) for snap in snapshots]
    return util.digest(repr(shown))


STALE = _("%(name)s was changed meanwhile: here it is as it is now; make your change again")


def group_snapshot(group):
    """snapshot() of a group with its members, which are a reverse relation snapshot() does not see."""
    return snapshot(group) | {"users": frozenset(group.user_set.values_list("pk", flat=True))}


@superuser_only
def group_list(request):
    groups = Group.objects.annotate(members=Count("user", distinct=True), perms=Count("permissions", distinct=True)).order_by("name")
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
        "admin/group_form.html",
        {
            "form": form,
            "title": _("Create Group"),
        },
    )


@superuser_only
def group_update(request, pk):
    group = get_object_or_404(Group, pk=pk)
    subject, before = f"Group {group.name}", group_snapshot(group)
    seen = form_seen(before)
    if request.method == "POST" and request.POST.get("seen") != seen:
        messages.error(request, STALE % {"name": group.name})
        return redirect(request.get_full_path())
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
        "admin/group_form.html",
        {
            "form": form,
            "group": group,
            "seen": seen,
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
    # the clone permission, given to the user or to a group of the user: one
    # query for the list, not a has_perm (two queries) a user
    clone = Permission.objects.filter(content_type__app_label="instances", codename="clone_instances")
    users = User.objects.annotate(
        api_tokens=Count("auth_token_set", filter=live),
        can_clone=Exists(clone.filter(Q(user=OuterRef("pk")) | Q(group__user=OuterRef("pk")))),
    ).prefetch_related("groups")
    return render(
        request,
        "admin/user_list.html",
        {
            "users": users,
            "title": _("Users"),
        },
    )


@sensitive_post_parameters()
@superuser_only
def user_create(request):
    user_form = forms.UserCreateForm(request.POST or None)
    attributes_form = forms.UserAttributesForm(request.POST or None)
    if user_form.is_valid() and attributes_form.is_valid():
        with audit(request, None, f"User {user_form.cleaned_data['username']}", "add") as entry, transaction.atomic():
            # the form's one-owner check of the default VMs again, with the inserts in one step
            lock_ownership()
            user_form.full_clean()
            entry.skip = not user_form.is_valid()
            if user_form.is_valid():
                user = user_form.save()
                attributes = attributes_form.save(commit=False)
                attributes.user = user
                attributes.save()
                UserInstance.objects.bulk_create(UserInstance(user=user, instance=instance)
                                                 for instance in user_form.default_instances)
        if user_form.is_valid():
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


@sensitive_post_parameters()
@superuser_only
def user_update(request, pk):
    user = get_object_or_404(User, pk=pk)
    attributes, attributes_created = UserAttributes.objects.get_or_create(user=user)
    subject = f"User {user.username}"
    before, before_attributes = snapshot(user), snapshot(attributes)
    seen = form_seen(before, before_attributes)
    if request.method == "POST" and request.POST.get("seen") != seen:
        messages.error(request, STALE % {"name": user.username})
        return redirect(request.get_full_path())
    user_form = forms.UserForm(request.POST or None, instance=user)
    attributes_form = forms.UserAttributesForm(
        request.POST or None, instance=attributes
    )
    valid = user_form.is_valid() and attributes_form.is_valid()
    if valid and user == request.user and not (user_form.cleaned_data["is_active"] and user_form.cleaned_data["is_superuser"]):
        user_form.add_error(None, OWN_ACCOUNT)
        valid = False
    if valid:
        with audit(request, None, subject, "change") as entry, transaction.atomic():
            user_form.save()
            attributes_form.save()
            if not user.is_active:  # as user_block
                ApiToken.objects.filter(user=user).delete()
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
            "seen": seen,
            "title": _("Update User"),
        },
    )


@sensitive_post_parameters()
@superuser_only
def user_update_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = forms.AdminPasswordForm(user, request.POST)
        valid = form.is_valid()
        if valid and user == request.user and not form.cleaned_data["set_usable_password"]:
            form.add_error(None, OWN_ACCOUNT)
            valid = False
        if valid:
            with audit(request, None, f"User {user.username}", "set password"), transaction.atomic():
                user = form.save()
                UserAttributes.objects.update_or_create(
                    user=user, defaults={"must_change_password": form.cleaned_data["must_change_password"]})
                # a reset closes a taken-over account: its tokens would outlive the old password
                ApiToken.objects.filter(user=user).delete()
            update_session_auth_hash(request, user)  # Important!
            messages.success(
                request, _("Password changed for %(user)s") % {"user": user.username}
            )
            return redirect("admin:user_list")
    else:
        form = forms.AdminPasswordForm(user)

    return render(request, "admin/user_password_form.html", {"form": form, "edited_user": user})


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
    with audit(request, None, f"User {user.username}", "block") as entry, transaction.atomic():
        entry.skip = not user.is_active  # already blocked
        user.is_active = False
        user.save()
        # an unblock must not bring back the tokens of someone who took the account over
        ApiToken.objects.filter(user=user).delete()
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


# rows in one Logs download: the workbook is built in memory
EXPORT_ROWS = 100000


def _logs(request):
    """The Logs rows the search and the failed-only box choose, newest first,
    and the query that chooses them again."""
    rows = Logs.objects.order_by("-date", "-id")
    text = request.GET.get("q", "").strip()
    failed = bool(request.GET.get("failed"))
    if text:
        rows = rows.filter(Q(user__icontains=text) | Q(host__icontains=text) | Q(instance__icontains=text)
                           | Q(instance_uuid__icontains=text) | Q(message__icontains=text) | Q(ip__icontains=text))
    if failed:
        rows = rows.filter(success=False)
    query = urlencode([(key, value) for key, value in (("q", text), ("failed", "1" if failed else "")) if value])
    return rows, text, failed, query


def _result(success):
    return _("Unknown") if success is None else _("Done") if success else _("Failed")


@superuser_only
def logs(request):
    rows, text, failed, query = _logs(request)
    logs = Paginator(rows, int(app_settings.LOGS_PER_PAGE)).get_page(request.GET.get("page"))
    # a VM's rows link to it while it is in the panel
    vms = dict(Instance.objects.filter(uuid__in={log.instance_uuid for log in logs if log.instance_uuid})
               .values_list("uuid", "pk"))
    for log in logs:
        log.vm_pk = vms.get(log.instance_uuid)
    return render(request, "admin/logs.html", {"logs": logs, "q": text, "failed": failed, "query": query,
                                               "time_zone": timezone.get_current_timezone_name()})


@superuser_only
def logs_export(request):
    """The rows the Logs page shows for the same search, every page of them,
    as an Excel workbook."""
    rows, text, failed, _query = _logs(request)
    zone = timezone.get_current_timezone_name()
    header = [f"Date ({zone})", "User", "Host", "VM", "VM UUID", "Message", "Result", "IP"]
    # tuples, not model objects: up to EXPORT_ROWS of them are held at once
    logs = list(rows.values_list("date", "user", "host", "instance", "instance_uuid", "message", "success", "ip")
                [:EXPORT_ROWS + 1])
    data = [[timezone.localtime(date).strftime("%Y-%m-%d %H:%M:%S"), user, host, instance, uuid, message,
             str(_result(success)), ip or ""]
            for date, user, host, instance, uuid, message, success, ip in logs[:EXPORT_ROWS]]
    notes = [f"Search: {text}" if text else "Search: none", "Failed only" if failed else "All results",
             f"Rows: {len(data)}", f"Times in {zone}"]
    if len(logs) > EXPORT_ROWS:
        notes.append(f"Only the newest {EXPORT_ROWS} rows: narrow the search for the others")
    response = HttpResponse(workbook("Logs", header, data, "About", notes),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    name = f"webvirtcloud-logs-{timezone.localtime():%Y%m%d-%H%M%S}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


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
        with audit(request, tombstone.host or None, f"Removed VM {tombstone.name} ({tombstone.uuid})", "delete",
                   instance=tombstone.name, uuid=tombstone.uuid):
            tombstone.delete()
        messages.success(request, _("Removed VM %(name)s deleted") % {"name": tombstone.name})
        return redirect("admin:tombstone_list")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": tombstone,
         "consequence": _("Its owners no longer get the VM back if its UUID shows up again.")},
    )

