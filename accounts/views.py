from django.core.validators import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from accounts.forms import UserAddForm
from accounts.models import *
from admin.decorators import superuser_only
from appsettings.models import AppSettings
from instances.models import Instance

import sass
import os

def profile(request):
    """
    :param request:
    :return:
    """

    error_messages = []
    # user = User.objects.get(id=request.user.id)
    publickeys = UserSSHKey.objects.filter(user_id=request.user.id)

    if request.method == 'POST':
        if 'username' in request.POST:
            username = request.POST.get('username', '')
            email = request.POST.get('email', '')
            user.first_name = username
            user.email = email
            request.user.save()
            return HttpResponseRedirect(request.get_full_path())
        if 'oldpasswd' in request.POST:
            oldpasswd = request.POST.get('oldpasswd', '')
            password1 = request.POST.get('passwd1', '')
            password2 = request.POST.get('passwd2', '')
            if not password1 or not password2:
                error_messages.append("Passwords didn't enter")
            if password1 and password2 and password1 != password2:
                error_messages.append("Passwords don't match")
            if not request.user.check_password(oldpasswd):
                error_messages.append("Old password is wrong!")
            if not error_messages:
                request.user.set_password(password1)
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
    """
    :param request:
    :param user_id:
    :return:
    """

    error_messages = []
    user = User.objects.get(id=user_id)
    user_insts = UserInstance.objects.filter(user_id=user_id)
    instances = Instance.objects.all().order_by('name')
    publickeys = UserSSHKey.objects.filter(user_id=user_id)

    if request.method == 'POST':
        if 'delete' in request.POST:
            user_inst = request.POST.get('user_inst', '')
            del_user_inst = UserInstance.objects.get(id=user_inst)
            del_user_inst.delete()
            return HttpResponseRedirect(request.get_full_path())
        if 'permission' in request.POST:
            user_inst = request.POST.get('user_inst', '')
            inst_vnc = request.POST.get('inst_vnc', '')
            inst_change = request.POST.get('inst_change', '')
            inst_delete = request.POST.get('inst_delete', '')
            edit_user_inst = UserInstance.objects.get(id=user_inst)
            edit_user_inst.is_change = bool(inst_change)
            edit_user_inst.is_delete = bool(inst_delete)
            edit_user_inst.is_vnc = bool(inst_vnc)
            edit_user_inst.save()
            return HttpResponseRedirect(request.get_full_path())
        if 'add' in request.POST:
            inst_id = request.POST.get('inst_id', '')

            if AppSettings.objects.get(key="ALLOW_INSTANCE_MULTIPLE_OWNER").value == 'True':
                check_inst = UserInstance.objects.filter(instance_id=int(inst_id), user_id=int(user_id))
            else:
                check_inst = UserInstance.objects.filter(instance_id=int(inst_id))

            if check_inst:
                msg = _("Instance already added")
                error_messages.append(msg)
            else:
                add_user_inst = UserInstance(instance_id=int(inst_id), user_id=int(user_id))
                add_user_inst.save()
                return HttpResponseRedirect(request.get_full_path())

    return render(request, 'account.html', locals())
