# backend/finance/management/commands/create_prod_superuser.py

import os
from django.core.management.base import BaseCommand
from users.models import User  # Make sure to import your custom User model

class Command(BaseCommand):
    help = 'Creates a superuser non-interactively, reading from env variables'

    def handle(self, *args, **options):
        email = os.getenv('DJANGO_SUPERUSER_EMAIL')
        password = os.getenv('DJANGO_SUPERUSER_PASSWORD')
        name = os.getenv('DJANGO_SUPERUSER_NAME', 'Admin') # Optional name

        if not email or not password:
            self.stdout.write(self.style.ERROR(
                'DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD must be set in env.'
            ))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(
                f"Superuser with email '{email}' already exists. Skipping."
            ))
            return

        User.objects.create_superuser(
            email=email,
            name=name,
            password=password
        )

        self.stdout.write(self.style.SUCCESS(
            f"Successfully created superuser '{email}'"
        ))