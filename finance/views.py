# backend/finance/views.py

from rest_framework.generics import ListCreateAPIView, ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from decimal import Decimal

from .models import Goal, Transaction, Product, User, Order
from .serializers import (
    GoalSerializer, GoalCreateSerializer, TransactionSerializer, ProductSerializer, 
    OrderCreateSerializer, OrderSerializer
)
# --- Import our new PayHero utility ---
from .payhero_utils import initiate_payhero_push
 
# --- GoalListCreateView (Unchanged) ---
class GoalListCreateView(ListCreateAPIView):
    # ... (code is the same)
    permission_classes = [IsAuthenticated]
    serializer_class = GoalSerializer 
    def get_queryset(self):
        return Goal.objects.filter(owner=self.request.user)
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return GoalCreateSerializer
        return super().get_serializer_class()
    def create(self, request, *args, **kwargs):
        create_serializer = self.get_serializer(data=request.data)
        create_serializer.is_valid(raise_exception=True)
        self.perform_create(create_serializer)
        response_serializer = GoalSerializer(create_serializer.instance)
        headers = self.get_success_headers(response_serializer.data)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

# --- OrderListView (Unchanged) ---
class OrderListView(ListAPIView):
    # ... (code is the same)
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by('-order_date')

# --- DepositView (UPDATED FOR PAYHERO) ---
class DepositView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        phone_number = user.phone_number
        amount = request.data.get('amount')
        goal_id = request.data.get('goal_id')

        if not all([phone_number, amount, goal_id]):
            return Response({"error": "Phone number, amount, and goal_id are required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            goal = Goal.objects.get(id=goal_id, owner=user)
        except Goal.DoesNotExist:
            return Response({"error": "Goal not found or does not belong to user."}, status=status.HTTP_404_NOT_FOUND)

        if goal.current_amount >= goal.target_amount:
            return Response({"error": "This savings goal is already complete."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create a unique reference, just like your JS code
        external_reference = f"kampus_koin-deposit-{goal.id}-{int(timezone.now().timestamp())}"

        # Call our new PayHero function
        payhero_response = initiate_payhero_push(phone_number, amount, external_reference)
        
        if not payhero_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # We no longer create a 'pending' transaction.
        # PayHero's response is all we need.
        return Response({"message": "STK push initiated successfully. Please enter your PIN."}, status=status.HTTP_200_OK)

# --- RepayView (UPDATED FOR PAYHERO) ---
class RepayView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        phone_number = user.phone_number
        amount = request.data.get('amount')
        order_id = request.data.get('order_id')

        if not all([phone_number, amount, order_id]):
            return Response({"error": "Phone number, amount, and order_id are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = Order.objects.get(id=order_id, user=user)
        except Order.DoesNotExist:
            return Response({"error": "Order not found or does not belong to user."}, status=status.HTTP_404_NOT_FOUND)
        
        if order.status == 'PAID':
            return Response({"error": "This order is already fully paid."}, status=status.HTTP_400_BAD_REQUEST)

        # Create a unique reference
        external_reference = f"kampus_koin-repayment-{order.id}-{int(timezone.now().timestamp())}"

        # Call our new PayHero function
        payhero_response = initiate_payhero_push(phone_number, amount, external_reference)
        
        if not payhero_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({"message": "Repayment STK push initiated. Please enter your PIN."}, status=status.HTTP_200_OK)

# --- PaymentCallbackView (REPLACES MpesaCallbackView) ---
class PaymentCallbackView(APIView):
    """
    Handles the callback from PayHero for BOTH deposits and repayments.
    """
    def post(self, request, *args, **kwargs):
        # Get data from 'response' object, like in your JS code
        callback_data = request.data.get('response', {})
        
        external_reference = callback_data.get('ExternalReference')
        if not external_reference:
            print("Callback received without ExternalReference")
            return Response({"message": "Invalid callback."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Parse our custom reference string
            parts = external_reference.split('-')
            tx_type = parts[1]
            object_id = int(parts[2])
            
            # Check if transaction was successful
            if callback_data.get('ResultCode') != 0:
                print(f"Transaction failed or was cancelled. Ref: {external_reference}")
                return Response({"message": "Failed transaction callback received."}, status=status.HTTP_200_OK)

            # --- IF THE TRANSACTION WAS SUCCESSFUL ---
            amount_decimal = Decimal(str(callback_data.get('Amount')))
            receipt_number = callback_data.get('Receipt') # PayHero might call this 'Receipt' or 'MpesaReceiptNumber'
            
            # Check if we already processed this
            if Transaction.objects.filter(mpesa_receipt_number=receipt_number).exists():
                return Response({"message": "Duplicate callback received."}, status=status.HTTP_200_OK)
            
            if tx_type == 'DEPOSIT':
                with transaction.atomic():
                    goal = Goal.objects.get(id=object_id)
                    user = goal.owner
                    
                    goal.current_amount = F('current_amount') + amount_decimal
                    goal.save()
                    
                    koin_to_add = int((amount_decimal / 100) * 15)
                    user.koin_score = F('koin_score') + koin_to_add
                    user.save()
                    
                    # Create the COMPLETED transaction now
                    Transaction.objects.create(
                        owner=user,
                        goal=goal,
                        transaction_type='DEPOSIT',
                        amount=amount_decimal,
                        mpesa_receipt_number=receipt_number,
                        transaction_date=timezone.now(),
                        checkout_request_id=external_reference, # We'll store this here
                        status='completed'
                    )

            elif tx_type == 'REPAYMENT':
                with transaction.atomic():
                    order = Order.objects.get(id=object_id)
                    user = order.user

                    order.amount_paid = F('amount_paid') + amount_decimal
                    order.save()
                    
                    # Check if paid off
                    order.refresh_from_db()
                    if order.amount_paid >= order.amount_financed and order.status != 'PAID':
                        order.status = 'PAID'
                        order.save()
                        user.koin_score = F('koin_score') + 1000
                        user.save()
                    
                    # Create the COMPLETED transaction now
                    Transaction.objects.create(
                        owner=user,
                        order=order,
                        transaction_type='REPAYMENT',
                        amount=amount_decimal,
                        mpesa_receipt_number=receipt_number,
                        transaction_date=timezone.now(),
                        checkout_request_id=external_reference,
                        status='completed'
                    )
        
        except Exception as e:
            print(f"An error occurred while processing callback: {e}")
            
        return Response({"message": "Callback processed successfully"}, status=status.HTTP_200_OK)

# --- TransactionListView, ProductListView, OrderCreateView (All Unchanged) ---
class TransactionListView(ListAPIView):
    # ... (code is the same)
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Transaction.objects.filter(owner=self.request.user).order_by('-created_at')

class ProductListView(ListAPIView):
    # ... (code is the same)
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]

class OrderCreateView(CreateAPIView):
    # ... (code is the same)
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer 
    def create(self, request, *args, **kwargs):
        input_serializer = OrderCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        product_id = input_serializer.validated_data['product_id']
        product = Product.objects.get(id=product_id)
        user = request.user
        if user.koin_score < product.required_koin_score:
            raise ValidationError("Your Koin Score is not high enough to unlock this item. Keep saving!")
        with transaction.atomic():
            down_payment = product.price * Decimal('0.25')
            amount_financed = product.price - down_payment
            order = Order.objects.create(
                user=user,
                product=product,
                total_amount=product.price,
                down_payment=down_payment,
                amount_financed=amount_financed
            )
            User.objects.filter(id=user.id).update(
                koin_score = F('koin_score') - product.required_koin_score
            )
            user.refresh_from_db()
        output_serializer = OrderSerializer(order)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)