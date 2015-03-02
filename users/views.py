from django.shortcuts import render
from django.contrib.auth.models import User


def users(request):
    """
    :param request:
    :return:
    """

    users = User.objects.filter(is_staff=False, is_superuser=False)

    return render(request, 'users.html', locals())

def user(request, user_id):
    """
    :param request:
    :return:
    """

    user = User.objects.get(id=user_id)

    return render(request, 'user.html', locals())