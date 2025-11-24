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
    active_order = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'required_koin_score', 
            'is_unlocked', 'is_already_unlocked', 'active_order',
            'vendor_name', 'vendor_location'
        ]
    
    def get_is_unlocked(self, obj):
        user = self.context['request'].user
        if not user or not user.is_authenticated:
            return False
        return user.koin_score >= obj.required_koin_score

    def get_is_already_unlocked(self, obj):
        # Local import to avoid circular error
        from .models import Order 
        user = self.context['request'].user
        if not user or not user.is_authenticated:
            return False
        return Order.objects.filter(user=user, product=obj).exists()
    
    def get_active_order(self, obj):
        # 1. STOP RECURSION: If we are already inside a nested product, stop.
        if self.context.get('skip_active_order'):
            return None

        # Local import
        from .models import Order
        user = self.context['request'].user
        
        # Safety check
        if not user or not user.is_authenticated:
            return None

        order = Order.objects.filter(user=user, product=obj).first()
        
        if order:
            # 2. Create a context that says "Don't fetch active_order again"
            nested_context = self.context.copy()
            nested_context['skip_active_order'] = True
            
            # 3. Serialize the nested product fully using THIS serializer
            # This ensures 'id', 'price', 'vendor_name' etc are all present and correct.
            product_data = ProductSerializer(obj, context=nested_context).data

            return {
                'id': order.id,
                'pickup_qr_code': order.pickup_qr_code,
                'down_payment': str(order.down_payment),
                'amount_financed': str(order.amount_financed),
                'amount_paid': str(order.amount_paid),
                'status': order.status,
                'order_date': order.order_date.isoformat() if order.order_date else None,
                'product': product_data, # <--- NOW CONTAINS FULL DATA
                'user': None # Explicitly send None for user to match your Flutter model
            }
        return None

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