# backend/finance/views.py

import os
import requests
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
from .permissions import IsOwner # <-- IMPORT THIS
from rest_framework.generics import RetrieveUpdateDestroyAPIView

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
class GoalDetailView(RetrieveUpdateDestroyAPIView):
    """
    Handles retrieving, updating, and deleting a single goal.
    """
    queryset = Goal.objects.all()
    serializer_class = GoalSerializer
    # --- Use BOTH permissions ---
    # 1. Must be logged in
    # 2. Must be the owner of this goal
    permission_classes = [IsAuthenticated, IsOwner]
    
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
    Handles ALL callbacks from PayHero and routes them
    to the correct application.
    """
    def post(self, request, *args, **kwargs):
        # Get data from 'response' object
        callback_data = request.data.get('response', {})
        external_reference = callback_data.get('ExternalReference')

        if not external_reference:
            print("Callback received without ExternalReference")
            return Response({"message": "Invalid callback."}, status=status.HTTP_400_BAD_REQUEST)

        # --- THE ROUTING LOGIC ---
        try:
            if external_reference.startswith('kampus_koin-'):
                # This is for our app. Process it.
                print(f"Processing Kampus Koin callback: {external_reference}")
                self.process_kampus_koin_payment(callback_data)
            
            else:
                # This is for your OTHER app. Forward it.
                print(f"Forwarding callback to other app: {external_reference}")
                self.forward_to_other_app(request.data)
                
        except Exception as e:
            # Don't crash the server if one stream fails
            print(f"General callback processing error: {e}")

        # Always return 200 OK to PayHero so it stops sending
        return Response({"message": "Callback processed or forwarded"}, status=status.HTTP_200_OK)


    def process_kampus_koin_payment(self, callback_data):
        """
        This is the logic we already wrote for Kampus Koin.
        """
        try:
            external_reference = callback_data.get('ExternalReference')
            parts = external_reference.split('-')
            tx_type = parts[1]
            object_id = int(parts[2])
            
            if callback_data.get('ResultCode') != 0:
                print(f"Kampus Koin transaction failed. Ref: {external_reference}")
                return

            amount_decimal = Decimal(str(callback_data.get('Amount')))
            receipt_number = callback_data.get('Receipt')
            
            if Transaction.objects.filter(mpesa_receipt_number=receipt_number).exists():
                print(f"Duplicate Kampus Koin callback. Ref: {receipt_number}")
                return
            
            if tx_type == 'DEPOSIT':
                with transaction.atomic():
                    goal = Goal.objects.get(id=object_id)
                    user = goal.owner
                    goal.current_amount = F('current_amount') + amount_decimal
                    goal.save()
                    koin_to_add = int((amount_decimal / 100) * 15)
                    user.koin_score = F('koin_score') + koin_to_add
                    user.save()
                    Transaction.objects.create(
                        owner=user, goal=goal, transaction_type='DEPOSIT',
                        amount=amount_decimal, mpesa_receipt_number=receipt_number,
                        transaction_date=timezone.now(), checkout_request_id=external_reference,
                        status='completed'
                    )

            elif tx_type == 'REPAYMENT':
                with transaction.atomic():
                    order = Order.objects.get(id=object_id)
                    user = order.user
                    Order.objects.filter(id=order.id).update(
                        amount_paid=F('amount_paid') + amount_decimal
                    )
                    order.refresh_from_db()
                    if order.amount_paid >= order.amount_financed and order.status != 'PAID':
                        order.status = 'PAID'
                        order.save()
                        User.objects.filter(id=user.id).update(
                            koin_score=F('koin_score') + 1000
                        )
                    Transaction.objects.create(
                        owner=user, order=order, transaction_type='REPAYMENT',
                        amount=amount_decimal, mpesa_receipt_number=receipt_number,
                        transaction_date=timezone.now(), checkout_request_id=external_reference,
                        status='completed'
                    )
        except Exception as e:
            # Log the specific error
            print(f"Error in process_kampus_koin_payment: {e}")
            # We re-throw the exception so the main handler can see it
            raise

    def forward_to_other_app(self, data):
        """
        Forwards the entire callback payload to your other app.
        """
        other_app_url = os.getenv('OTHER_APP_CALLBACK_URL')
        if not other_app_url:
            print("OTHER_APP_CALLBACK_URL is not set. Cannot forward callback.")
            return

        try:
            # Forward the original, raw data
            # We use verify=False to match your 'rejectUnauthorized: false'
            requests.post(other_app_url, json=data, timeout=5, verify=False)
            print("Successfully forwarded callback.")
        except requests.exceptions.RequestException as e:
            print(f"Failed to forward callback to {other_app_url}: {e}")

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