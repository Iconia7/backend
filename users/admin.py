# users/admin.py

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

# Get your custom User model
User = get_user_model()

# Register your User model with the UserAdmin class
admin.site.register(User, UserAdmin)