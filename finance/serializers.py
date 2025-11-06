# backend/finance/serializers.py

from rest_framework import serializers
from .models import Goal, Transaction, Product, Order

# --- SERIALIZER FOR LISTING GOALS (FIXED) ---
# We removed 'read_only_fields' so current_amount is always sent
class GoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Goal
        fields = ['id', 'owner', 'name', 'target_amount', 'current_amount', 'created_at']

# --- NEW SERIALIZER FOR CREATING GOALS ---
class GoalCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Goal
        fields = ['name', 'target_amount']

# --- TRANSACTION SERIALIZER (FIXED) ---
class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        # Added 'order' and 'transaction_type'
        fields = [
            'id', 'goal', 'order', 'transaction_type', 'amount', 
            'mpesa_receipt_number', 'transaction_date', 'status'
        ]

# --- PRODUCT SERIALIZER (Correct) ---
class ProductSerializer(serializers.ModelSerializer):
    is_unlocked = serializers.SerializerMethodField()
    is_already_unlocked = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'required_koin_score', 
            'is_unlocked','is_already_unlocked','vendor_name', 'vendor_location'
        ]
    
    def get_is_unlocked(self, obj):
        user = self.context['request'].user
        return user.koin_score >= obj.required_koin_score

    def get_is_already_unlocked(self, obj):
        user = self.context['request'].user
        return Order.objects.filter(user=user, product=obj).exists()

# --- ORDER CREATE SERIALIZER (Correct) ---
class OrderCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()

    def validate_product_id(self, value):
        if not Product.objects.filter(id=value).exists():
            raise serializers.ValidationError("Product with this ID does not exist.")
        return value

# --- ORDER SERIALIZER (Correct) ---
class OrderSerializer(serializers.ModelSerializer):
    product = ProductSerializer()
  
    class Meta:
        model = Order
        fields = [
            'id', 'user', 'product', 'total_amount', 'down_payment', 
            'amount_financed','amount_paid', 'status', 'order_date','pickup_qr_code'
        ]