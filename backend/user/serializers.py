from rest_framework import serializers

from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        fields = ('id', 'email', 'username', 'first_name', 'last_name', 'date_joined', 'last_login', 'is_active')
        model = User
