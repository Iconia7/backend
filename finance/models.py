# finance/models.py
import uuid
from django.db import models
from users.models import User 

class Goal(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='goals')

    # The name of the goal, e.g., "New Laptop"
    name = models.CharField(max_length=255)

    target_amount = models.DecimalField(max_digits=10, decimal_places=2)

    # The amount the user has saved so far for this goal.
    current_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # Automatically records when the goal was created.
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.owner.email})"

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Goal Deposit'),
        ('REPAYMENT', 'Order Repayment'),
    ]
    owner = models.ForeignKey('users.User', on_delete=models.CASCADE)
    goal = models.ForeignKey('Goal', on_delete=models.CASCADE, null=True, blank=True)
    # Add a new optional field for the order
    order = models.ForeignKey('Order', on_delete=models.CASCADE, null=True, blank=True)
    # Add a type field
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, default='DEPOSIT')

    # We make these nullable, as they will be filled in *after* the callback
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mpesa_receipt_number = models.CharField(max_length=50, null=True, blank=True, unique=True)
    transaction_date = models.DateTimeField(null=True, blank=True)

    # This is our key for linking the request and the callback
    checkout_request_id = models.CharField(max_length=100, unique=True) # Must be unique

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending') # Default is now pending
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.mpesa_receipt_number or self.checkout_request_id}"

class Product(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    required_koin_score = models.IntegerField(default=1000)
    vendor_name = models.CharField(max_length=255, blank=True, null=True)
    vendor_location = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name   

class Order(models.Model):
    STATUS_CHOICES = [
        ('READY_FOR_PICKUP', 'Ready for Pickup'),
        ('COMPLETED', 'Repayment in Progress'),
        ('PAID', 'Fully Paid'),
    ]

    # The user who made the order
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    # The product that was ordered
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    # Financial details at the time of the order
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    down_payment = models.DecimalField(max_digits=10, decimal_places=2)
    amount_financed = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='READY_FOR_PICKUP')
    order_date = models.DateTimeField(auto_now_add=True)
    pickup_qr_code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    def __str__(self):
        return f"Order #{self.id} - {self.product.name} for {self.user.email}"
    
class VendorPayout(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE)
    vendor_name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    mpesa_transaction_id = models.CharField(max_length=50, blank=True, null=True) # For the B2C receipt
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payout for {self.order.product.name} to {self.vendor_name}"   
         