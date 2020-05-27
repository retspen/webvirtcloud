
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import ugettext_lazy as _

from appsettings.models import AppSettings
from accounts.models import UserAttributes
from logs.models import Logs

from . import forms
from .decorators import superuser_only


@superuser_only
def group_list(request):
    groups = Group.objects.all()
    return render(
        request,
        'admin/group_list.html',
        {
            'groups': groups,
        },
    )


@superuser_only
def group_create(request):
    form = forms.GroupForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('admin:group_list')
    return render(
        request,
        'admin/common/form.html',
        {
            'form': form,
            'title': _('Create Group'),
        },
    )


@superuser_only
def group_update(request, pk):
    group = get_object_or_404(Group, pk=pk)
    form = forms.GroupForm(request.POST or None, instance=group)
    if form.is_valid():
        form.save()
        return redirect('admin:group_list')

    return render(
        request,
        'admin/common/form.html',
        {
            'form': form,
            'title': _('Update Group'),
        },
    )


@superuser_only
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        group.delete()
        return redirect('admin:group_list')

    return render(
        request,
        'admin/common/confirm_delete.html',
        {'object': group},
    )


@superuser_only
def user_list(request):
    users = User.objects.all()
    return render(
        request,
        'admin/user_list.html',
        {
            'users': users,
            'title': _('Users'),
        },
    )


@superuser_only
def user_create(request):
    user_form = forms.UserCreateForm(request.POST or None)
    attributes_form = forms.UserAttributesForm(request.POST or None)
    if user_form.is_valid() and attributes_form.is_valid():
        user = user_form.save()
        password = user_form.cleaned_data['password']
        user.set_password(password)
        user.save()
        attributes = attributes_form.save(commit=False)
        attributes.user = user
        attributes.save()
        return redirect('admin:user_list')

    return render(
        request,
        'admin/user_form.html',
        {
            'user_form': user_form,
            'attributes_form': attributes_form,
            'title': _('Create User')
        },
    )


@superuser_only
def user_update(request, pk):
    user = get_object_or_404(User, pk=pk)
    attributes = UserAttributes.objects.get(user=user)
    user_form = forms.UserForm(request.POST or None, instance=user)
    attributes_form = forms.UserAttributesForm(request.POST or None, instance=attributes)
    if user_form.is_valid() and attributes_form.is_valid():
        user_form.save()
        attributes_form.save()
        return redirect('admin:user_list')

    return render(
        request,
        'admin/user_form.html',
        {
            'user_form': user_form,
            'attributes_form': attributes_form,
            'title': _('Update User')
        },
    )


@superuser_only
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        user.delete()
        return redirect('admin:user_list')

    return render(
        request,
        'admin/common/confirm_delete.html',
        {'object': user},
    )


@superuser_only
def user_block(request, pk):
    user: User = get_object_or_404(User, pk=pk)
    user.is_active = False
    user.save()
    return redirect('admin:user_list')


@superuser_only
def user_unblock(request, pk):
    user: User = get_object_or_404(User, pk=pk)
    user.is_active = True
    user.save()
    return redirect('admin:user_list')


@superuser_only
def logs(request):
    l = Logs.objects.order_by('-date')
    paginator = Paginator(l, int(AppSettings.objects.get(key="LOGS_PER_PAGE").value))
    page = request.GET.get('page', 1)
    logs = paginator.page(page)
    return render(request, 'admin/logs.html', {'logs': logs})
