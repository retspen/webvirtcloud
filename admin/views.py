from accounts.models import Instance, UserAttributes, UserInstance
from appsettings.settings import app_settings
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from logs.models import Logs

from . import forms
from .decorators import superuser_only


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
    form = forms.GroupForm(request.POST or None, instance=group)
    if form.is_valid():
        form.save()
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
        group.delete()
        return redirect("admin:group_list")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": group},
    )


@superuser_only
def user_list(request):
    users = User.objects.all()
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
        user = user_form.save()
        password = user_form.cleaned_data["password"]
        user.set_password(password)
        user.save()
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
    user_form = forms.UserForm(request.POST or None, instance=user)
    attributes_form = forms.UserAttributesForm(
        request.POST or None, instance=attributes
    )
    if user_form.is_valid() and attributes_form.is_valid():
        user_form.save()
        attributes_form.save()
        next = request.GET.get("next")
        return redirect(next or "admin:user_list")

    return render(
        request,
        "admin/user_form.html",
        {
            "user_form": user_form,
            "attributes_form": attributes_form,
            "title": _("Update User"),
        },
    )


@superuser_only
def user_update_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = AdminPasswordChangeForm(user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Important!
            messages.success(
                request, _("Password changed for %(user)s") % {"user": user.username}
            )
            return redirect("admin:user_list")
        else:
            messages.error(request, _("Wrong Data Provided"))
    else:
        form = AdminPasswordChangeForm(user)

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
    if request.method == "POST":
        user.delete()
        return redirect("admin:user_list")

    return render(
        request,
        "common/confirm_delete.html",
        {"object": user},
    )


@superuser_only
def user_block(request, pk):
    user: User = get_object_or_404(User, pk=pk)
    user.is_active = False
    user.save()
    return redirect("admin:user_list")


@superuser_only
def user_unblock(request, pk):
    user: User = get_object_or_404(User, pk=pk)
    user.is_active = True
    user.save()
    return redirect("admin:user_list")


@superuser_only
def logs(request):
    l = Logs.objects.order_by("-date")
    paginator = Paginator(l, int(app_settings.LOGS_PER_PAGE))
    page = request.GET.get("page", 1)
    logs = paginator.page(page)
    return render(request, "admin/logs.html", {"logs": logs})


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
