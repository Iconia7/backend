# users/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    # We'll use the email as the unique identifier instead of the username.
    email = models.EmailField(unique=True)

    # A field for the student's full name for easier display.
    name = models.CharField(max_length=255)

    # A field for the adm no. 
    adm_no = models.CharField(max_length=100, blank=True, null=True)

    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)

    # It will store the user's financial discipline score.
    koin_score = models.IntegerField(default=0)

    # use the 'email' field for login.
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'name'] # 'username' is still needed for Django admin commands

    def __str__(self):
        return self.email