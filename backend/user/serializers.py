from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User

from rest_framework import status
from rest_framework.response import Response
from rest_framework import serializers
from rest_auth.registration.views import RegisterView
from rest_auth.views import LoginView
from allauth.account import app_settings as allauth_settings


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        fields = ('id', 'email', 'username', 'first_name', 'last_name', 'date_joined', 'last_login', 'is_active')
        model = User



class SignUpView(RegisterView):

    def get_response_data(self, user):
        if allauth_settings.EMAIL_VERIFICATION == \
                allauth_settings.EmailVerificationMethod.MANDATORY:
            return {"detail": _("Verification e-mail sent.")}
        serializer = UserSerializer(user)
        data = {
            'user': serializer.data,
            'session': self.request.session.session_key,
            'token': self.token
        }
        return data


class SignInView(LoginView):

    def get_response(self):
        serializer_class = self.get_response_serializer()
        serializer = UserSerializer(self.user)
        data = {
            'user': serializer.data,
            'session': self.request.session.session_key,
            'token': self.token
        }
        serializer = serializer_class(instance=data,
                                     context={'request': self.request})

        return Response(serializer.data, status=status.HTTP_200_OK)
