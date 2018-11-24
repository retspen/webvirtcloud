from __future__ import unicode_literals

from django.contrib.auth.models import User

from rest_framework.generics import RetrieveUpdateAPIView, ListAPIView
from .serializers import UserSerializer


class UsersView(ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer


class UserView(RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    queryset = User.objects.all()

    def get_object(self):
        return self.queryset.get(pk=self.request.user.id)
