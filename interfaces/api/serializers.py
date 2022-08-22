
from rest_framework import serializers
from interfaces.models import Interfaces


class InterfacesSerializer(serializers.ModelSerializer):
        
    class Meta:
        model = Interfaces
        fields = ['name', 'type', 'state', 'mac'] 

