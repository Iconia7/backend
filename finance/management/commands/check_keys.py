# finance/management/commands/check_keys.py

import os
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Checks if the M-Pesa environment variables are loaded'

    def handle(self, *args, **options):
        key = os.getenv('MPESA_CONSUMER_KEY')
        secret = os.getenv('MPESA_CONSUMER_SECRET')
        shortcode = os.getenv('MPESA_BUSINESS_SHORTCODE')
        passkey = os.getenv('MPESA_PASSKEY')

        self.stdout.write(self.style.SUCCESS('--- Checking M-Pesa Keys ---'))

        if key:
            self.stdout.write(f"MPESA_CONSUMER_KEY: ...{key[-4:]} (Loaded)")
        else:
            self.stdout.write(self.style.ERROR("MPESA_CONSUMER_KEY: NOT FOUND"))

        if secret:
            self.stdout.write(f"MPESA_CONSUMER_SECRET: ...{secret[-4:]} (Loaded)")
        else:
            self.stdout.write(self.style.ERROR("MPESA_CONSUMER_SECRET: NOT FOUND"))

        if shortcode:
            self.stdout.write(f"MPESA_BUSINESS_SHORTCODE: {shortcode} (Loaded)")
        else:
            self.stdout.write(self.style.ERROR("MPESA_BUSINESS_SHORTCODE: NOT FOUND"))

        if passkey:
            self.stdout.write(f"MPESA_PASSKEY: ...{passkey[-4:]} (Loaded)")
        else:
            self.stdout.write(self.style.ERROR("MPESA_PASSKEY: NOT FOUND"))

        self.stdout.write(self.style.SUCCESS('------------------------------'))