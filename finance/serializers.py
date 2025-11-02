# finance/serializers.py

from rest_framework import serializers
from .models import Goal, Transaction, Product,Order

class GoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Goal
        fields = ['id', 'owner', 'name', 'target_amount', 'current_amount', 'created_at']

        read_only_fields = ['owner', 'current_amount']

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        # List all the fields you want to show the user
        fields = ['id', 'goal', 'amount', 'mpesa_receipt_number', 'transaction_date', 'status']

class ProductSerializer(serializers.ModelSerializer):
    is_unlocked = serializers.SerializerMethodField()
    class Meta:
        model = Product
        # List the fields you want to show in the API
        fields = ['id', 'name', 'description', 'price', 'required_koin_score', 'is_unlocked']
    
    def get_is_unlocked(self, obj):
        """
        Checks if the user's Koin Score is high enough to unlock the product.
        'obj' is the Product instance being serialized.
        """
        # Get the user from the context that the view provides
        user = self.context['request'].user
        return user.koin_score >= obj.required_koin_score

class OrderCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()

    def validate_product_id(self, value):
        """
        Check that the product exists.
        """
        if not Product.objects.filter(id=value).exists():
            raise serializers.ValidationError("Product with this ID does not exist.")
        return value

# This serializer is for displaying the created order
class OrderSerializer(serializers.ModelSerializer):
    # Display the product name instead of just its ID
    product = serializers.StringRelatedField() 

    class Meta:
        model = Order
        fields = [
            'id', 'user', 'product', 'total_amount', 'down_payment', 
            'amount_financed','amount_paid', 'status', 'order_date'
        ]    