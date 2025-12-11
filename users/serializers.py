# users/serializers.py

from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    profile_picture = serializers.SerializerMethodField()
    class Meta:
        model = User
        # Added 'profile_picture' to fields
        fields = ['id', 'email', 'name', 'password', 'adm_no', 'phone_number','koin_score', 'profile_picture']

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
    
    def get_profile_picture(self, obj):
        if obj.profile_picture:
            # This ensures we get the full https://res.cloudinary... URL
            return obj.profile_picture.url 
        return None
    
class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # Added 'profile_picture' to fields so it can be updated
        fields = ['id', 'email', 'name', 'phone_number', 'koin_score', 'profile_picture'] 
        
        # We specify which ones are strictly NOT editable
        read_only_fields = ['id', 'email', 'koin_score'] 
        
    def validate_phone_number(self, value):
        if value and len(value) < 10:
             raise serializers.ValidationError("Phone number is too short.")
        return value