# users/serializers.py

from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'password', 'adm_no', 'phone_number','koin_score']

        extra_kwargs = {
            'password': {'write_only': True}, # Password should not be returned in API responses
            'koin_score': {'read_only': True} # Koin score cannot be set during registration
        }

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = self.Meta.model(**validated_data)

        # Set the username to the email before saving
        if 'email' in validated_data:
            instance.username = validated_data['email']

        if password is not None:
            instance.set_password(password)

        instance.save()
        return instance
    
class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # Allow updating name and phone number
        fields = ['name', 'phone_number'] 
        
    def validate_phone_number(self, value):
        # Add basic validation if needed
        if value and len(value) < 10:
             raise serializers.ValidationError("Phone number is too short.")
        return value    