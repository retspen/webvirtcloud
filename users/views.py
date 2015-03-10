from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from users.models import UserInstance
from users.forms import UserAddForm


def users(request):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    error_messages = []
    users = User.objects.filter(is_staff=False, is_superuser=False)

    if request.method == 'POST':
        if 'create' in request.POST:
            form = UserAddForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
            else:
                for msg_err in form.errors.values():
                    error_messages.append(msg_err.as_text())
            if not error_messages:
                new_user = User.objects.create_user(data['name'], None, data['password'])
                new_user.save()
                return HttpResponseRedirect(request.get_full_path())

    return render(request, 'users.html', locals())

def user(request, user_id):
    """
    :param request:
    :return:
    """

    if not request.user.is_authenticated():
        return HttpResponseRedirect(reverse('index'))

    if not request.user.is_superuser:
        return HttpResponseRedirect(reverse('index'))

    user = User.objects.get(id=user_id)
    user_insts = UserInstance.objects.filter(user_id=user_id)

    if request.method == 'POST':
        if 'delete' in request.POST:
            user_inst = request.POST.get('user_inst', '')
            del_user_inst = UserInstance.objects.get(id=user_inst)
            del_user_inst.delete()
            return HttpResponseRedirect(request.get_full_path())
        if 'edit' in request.POST:
            user_inst = request.POST.get('user_inst', '')
            inst_block = request.POST.get('inst_block', '')
            inst_change = request.POST.get('inst_change', '')
            inst_delete = request.POST.get('inst_delete', '')
            edit_user_inst = UserInstance.objects.get(id=user_inst)
            edit_user_inst.is_block = bool(inst_block)
            edit_user_inst.is_change = bool(inst_change)
            edit_user_inst.is_delete = bool(inst_delete)
            edit_user_inst.save()
            return HttpResponseRedirect(request.get_full_path())

    return render(request, 'user.html', locals())