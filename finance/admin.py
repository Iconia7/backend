# finance/admin.py

from django.contrib import admin
from .models import Goal, Transaction, Product,Order

# Register your models here.
admin.site.register(Goal)
admin.site.register(Transaction)
admin.site.register(Product) 
admin.site.register(Order)