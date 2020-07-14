import os

import sass
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.validators import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from accounts.models import *
from admin.decorators import superuser_only
from appsettings.models import AppSettings
from instances.models import Instance

from . import forms


def profile(request):
    error_messages = []
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)

    if request.method == 'POST':
        if 'username' in request.POST:
            username = request.POST.get('username', '')
            email = request.POST.get('email', '')
            user.first_name = username
            user.email = email
            request.user.save()
            return HttpResponseRedirect(request.get_full_path())
        if 'keyname' in request.POST:
            keyname = request.POST.get('keyname', '')
            keypublic = request.POST.get('keypublic', '')
            for key in publickeys:
                if keyname == key.keyname:
                    msg = _("Key name already exist")
                    error_messages.append(msg)
                if keypublic == key.keypublic:
                    msg = _("Public key already exist")
                    error_messages.append(msg)
            if '\n' in keypublic or '\r' in keypublic:
                msg = _("Invalid characters in public key")
                error_messages.append(msg)
            if not error_messages:
                addkeypublic = UserSSHKey(user_id=request.user.id, keyname=keyname, keypublic=keypublic)
                addkeypublic.save()
                return HttpResponseRedirect(request.get_full_path())
        if 'keydelete' in request.POST:
            keyid = request.POST.get('keyid', '')
            delkeypublic = UserSSHKey.objects.get(id=keyid)
            delkeypublic.delete()
            return HttpResponseRedirect(request.get_full_path())
    return render(request, 'profile.html', locals())


@superuser_only
def account(request, user_id):
    error_messages = []
    user = User.objects.get(id=user_id)
    user_insts = UserInstance.objects.filter(user_id=user_id)
    instances = Instance.objects.all().order_by('name')
    publickeys = UserSSHKey.objects.filter(user_id=user_id)

    return render(request, 'account.html', locals())


@permission_required('accounts.change_password', raise_exception=True)
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Important!
            messages.success(request, _('Password Changed'))
            return redirect('profile')
        else:
            messages.error(request, _('Wrong Data Provided'))
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'accounts/change_password_form.html', {'form': form})


@superuser_only
def user_instance_create(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    form = forms.UserInstanceForm(request.POST or None, initial={'user': user})
    if form.is_valid():
        form.save()
        return redirect(reverse('account', args=[user.id]))

    return render(
        request,
        'common/form.html',
        {
            'form': form,
            'title': _('Create User Instance'),
        },
    )


@superuser_only
def user_instance_update(request, pk):
    user_instance = get_object_or_404(UserInstance, pk=pk)
    form = forms.UserInstanceForm(request.POST or None, instance=user_instance)
    if form.is_valid():
        form.save()
        return redirect(reverse('account', args=[user_instance.user.id]))

    return render(
        request,
        'common/form.html',
        {
            'form': form,
            'title': _('Update User Instance'),
        },
    )


@superuser_only
def user_instance_delete(request, pk):
    user_instance = get_object_or_404(UserInstance, pk=pk)
    if request.method == 'POST':
        user = user_instance.user
        user_instance.delete()
        next = request.GET.get('next', None)
        if next:
            return redirect(next)
        else:
            return redirect(reverse('account', args=[user.id]))

    return render(
        request,
        'common/confirm_delete.html',
        {'object': user_instance},
    )
