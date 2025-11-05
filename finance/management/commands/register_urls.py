# finance/management/commands/register_urls.py

from django.core.management.base import BaseCommand
from finance.payhero_utils import register_mpesa_urls

class Command(BaseCommand):
    help = 'Registers the M-Pesa Confirmation and Validation URLs with Daraja'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Attempting to register M-Pesa URLs...'))
        register_mpesa_urls()
        self.stdout.write(self.style.SUCCESS('URL registration process finished.'))