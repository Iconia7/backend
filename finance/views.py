# backend/finance/views.py

import uuid
from rest_framework.generics import ListCreateAPIView, ListAPIView, CreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated,AllowAny
from .permissions import IsOwner
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum
import requests
import os

from .models import Goal, Transaction, Product, User, Order, VendorPayout
from .serializers import (
    GoalSerializer, GoalCreateSerializer, TransactionSerializer, ProductSerializer, 
    OrderCreateSerializer, OrderSerializer
)
from .payhero_utils import initiate_payhero_push

# --- GoalListCreateView (FIXED) ---
class GoalListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    
    # By default, use the FULL serializer for GET requests
    serializer_class = GoalSerializer 

    def get_queryset(self):
        return Goal.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def get_serializer_class(self):
        # When we are CREATING (POST), use the simple Create serializer
        if self.request.method == 'POST':
            return GoalCreateSerializer
        # Otherwise (GET), use the default full GoalSerializer
        return super().get_serializer_class()
    
    def create(self, request, *args, **kwargs):
        # Use the 'create' serializer for INCOMING data
        create_serializer = self.get_serializer(data=request.data)
        create_serializer.is_valid(raise_exception=True)
        self.perform_create(create_serializer)
        
        # Use the 'list' serializer for the OUTGOING response
        response_serializer = GoalSerializer(create_serializer.instance)
        
        headers = self.get_success_headers(response_serializer.data)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

# --- GoalDetailView (Correct) ---
class GoalDetailView(RetrieveUpdateDestroyAPIView):
    """
    Handles retrieving, updating, and deleting a single goal.
    """
    queryset = Goal.objects.all()
    serializer_class = GoalSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    
# --- OrderListView (Correct) ---
class OrderListView(ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by('-order_date')

# --- DepositView (Correct) ---
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
        external_reference = f"kampus_koin-deposit-{goal.id}-{int(timezone.now().timestamp())}"
        try:
            Transaction.objects.create(
                owner=user,
                goal=goal,
                transaction_type='DEPOSIT',
                amount=Decimal(amount), # Store the amount
                checkout_request_id=external_reference,
                status='pending'
            )
        except Exception as e:
            print(f"Error creating pending transaction: {e}")
            return Response({"error": "A transaction error occurred. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        payhero_response = initiate_payhero_push(phone_number, amount, external_reference)
        if not payhero_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"message": "STK push initiated successfully. Please enter your PIN."}, status=status.HTTP_200_OK)

# --- RepayView (Correct) ---
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
        external_reference = f"kampus_koin-repayment-{order.id}-{int(timezone.now().timestamp())}"
        try:
            Transaction.objects.create(
                owner=user,
                order=order,
                transaction_type='REPAYMENT',
                amount=Decimal(amount), # Store the amount
                checkout_request_id=external_reference,
                status='pending'
            )
        except Exception as e:
            print(f"Error creating pending transaction: {e}")
            return Response({"error": "A transaction error occurred. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        payhero_response = initiate_payhero_push(phone_number, amount, external_reference)
        if not payhero_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"message": "Repayment STK push initiated. Please enter your PIN."}, status=status.HTTP_200_OK)    

# --- PaymentCallbackView (Correct) ---
class PaymentCallbackView(APIView):
    """
    Handles ALL callbacks from PayHero.
    Debugs the payload, handles key variations, and prevents duplicates.
    """
    def post(self, request, *args, **kwargs):
        print(f"DEBUG: Raw PayHero Payload: {request.data}")

        callback_data = request.data.get('response')
        if not callback_data:
            callback_data = request.data

        # --- FIX 1: Handle different key names for the reference ---
        external_reference = callback_data.get('ExternalReference')
        if not external_reference:
            external_reference = callback_data.get('User_Reference')
        
        if not external_reference:
            print("ERROR: Callback received without ExternalReference or User_Reference")
            # Return 200 OK so PayHero stops sending this bad payload
            return Response({"message": "Invalid callback structure."}, status=status.HTTP_200_OK)

        try:
            if external_reference.startswith('kampus_koin-'):
                print(f"Processing Kampus Koin callback: {external_reference}")
                self.process_kampus_koin_payment(callback_data, external_reference)
            else:
                print(f"Forwarding callback to other app: {external_reference}")
                self.forward_to_other_app(request.data)
                
        except Exception as e:
            print(f"General callback processing error: {e}")

        return Response({"message": "Callback processed or forwarded"}, status=status.HTTP_200_OK)

    def process_kampus_koin_payment(self, callback_data, external_reference):
        try:
            # --- FIX START: LOGIC UPDATE ---
            # check if this transaction exists
            existing_transaction = Transaction.objects.filter(checkout_request_id=external_reference).first()
            
            # If it exists and is ALREADY completed, stop (true duplicate)
            if existing_transaction and existing_transaction.status == 'completed':
                print(f"Duplicate completed transaction ignored: {external_reference}")
                return

            # If it doesn't exist, or it exists but is 'pending', we proceed.
            # -------------------------------

            parts = external_reference.split('-')
            tx_type = parts[1].upper() 
            object_id = int(parts[2])
            
            print(f"DEBUG: Type={tx_type}, ID={object_id}")

            # Handle PayHero result codes (0 usually means success)
            if callback_data.get('ResultCode') != 0 and callback_data.get('Status') != 'Success':
                print(f"Kampus Koin transaction failed at MPESA. Ref: {external_reference}")
                # Optional: Mark existing pending transaction as failed
                if existing_transaction:
                    existing_transaction.status = 'failed'
                    existing_transaction.save()
                return

            amount_decimal = Decimal(str(callback_data.get('Amount')))
            
            # Handle different receipt keys
            receipt_number = callback_data.get('Receipt') or callback_data.get('MpesaReceiptNumber') or callback_data.get('MPESA_Reference')

            if tx_type == 'DEPOSIT':
                with transaction.atomic():
                    goal = Goal.objects.get(id=object_id)
                    user = goal.owner
                    
                    # 1. Update Goal and User
                    goal.current_amount += amount_decimal
                    koin_to_add = int((amount_decimal / 100) * 15)
                    user.koin_score += koin_to_add
                    
                    goal.save()
                    user.save()
                    
                    # 2. Update existing OR Create new transaction
                    if existing_transaction:
                        existing_transaction.status = 'completed'
                        existing_transaction.mpesa_receipt_number = receipt_number
                        existing_transaction.transaction_date = timezone.now()
                        existing_transaction.save()
                    else:
                        # Fallback if DepositView failed to create it but Push went through
                        Transaction.objects.create(
                            owner=user, goal=goal, transaction_type='DEPOSIT',
                            amount=amount_decimal, mpesa_receipt_number=receipt_number,
                            transaction_date=timezone.now(), 
                            checkout_request_id=external_reference,
                            status='completed'
                        )
                    print(f"Successfully processed deposit for goal {goal.id}")

            elif tx_type == 'REPAYMENT':
                with transaction.atomic():
                    order = Order.objects.get(id=object_id)
                    user = order.user
                    
                    # 1. Update Order
                    order.amount_paid += amount_decimal
                    
                    if order.amount_paid >= order.amount_financed and order.status != 'PAID':
                        order.status = 'PAID'
                        user.koin_score += 1000 
                        user.save()
                    
                    order.save()
                    
                    # 2. Update existing OR Create new transaction
                    if existing_transaction:
                        existing_transaction.status = 'completed'
                        existing_transaction.mpesa_receipt_number = receipt_number
                        existing_transaction.transaction_date = timezone.now()
                        existing_transaction.save()
                    else:
                        Transaction.objects.create(
                            owner=user, order=order, transaction_type='REPAYMENT',
                            amount=amount_decimal, mpesa_receipt_number=receipt_number,
                            transaction_date=timezone.now(), 
                            checkout_request_id=external_reference,
                            status='completed'
                        )
                    print(f"Successfully processed repayment for order {order.id}")
        
        except Exception as e:
            print(f"Error in process_kampus_koin_payment: {e}")

    def forward_to_other_app(self, data):
        other_app_url = os.getenv('OTHER_APP_CALLBACK_URL')
        if not other_app_url:
            return
        try: 
            requests.post(other_app_url, json=data, timeout=5, verify=False)
        except Exception as e:
            print(f"Forwarding error: {e}")

# --- TransactionListView, ProductListView, OrderCreateView (All Correct) ---
class TransactionListView(ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Transaction.objects.filter(owner=self.request.user).order_by('-created_at')

class ProductListView(ListAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]

class OrderCreateView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderCreateSerializer 
    
    def create(self, request, *args, **kwargs):
        input_serializer = OrderCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        
        product_id = input_serializer.validated_data['product_id']
        product = Product.objects.get(id=product_id)
        user = request.user

        # 1. Koin Score Validation
        if user.koin_score < product.required_koin_score:
            raise ValidationError("Your Koin Score is not high enough to unlock this item.")

        # 2. Duplicate Check
        if Order.objects.filter(user=user, product=product).exists():
            raise ValidationError("You have already unlocked this item.")

        # 3. Calculate Down Payment
        down_payment = product.price * Decimal('0.25')

        with transaction.atomic():
            # 4. Check Total Savings
            total_savings = Goal.objects.filter(owner=user).aggregate(Sum('current_amount'))['current_amount__sum'] or Decimal('0.00')

            if total_savings < down_payment:
                # Calculate how much more they need
                shortfall = down_payment - total_savings
                raise ValidationError(f"Insufficient savings. Down payment is KES {down_payment:,.2f}. You need KES {shortfall:,.2f} more.")

            # 5. Deduct funds from Goals (FIFO or Proportional)
            # Here we deduct from available goals until the down payment is covered
            remaining_to_deduct = down_payment
            user_goals = Goal.objects.filter(owner=user, current_amount__gt=0).order_by('created_at')

            for goal in user_goals:
                if remaining_to_deduct <= 0:
                    break
                
                if goal.current_amount >= remaining_to_deduct:
                    # Goal has enough to cover the rest
                    goal.current_amount -= remaining_to_deduct
                    goal.save()
                    remaining_to_deduct = 0
                else:
                    # Take everything from this goal and move to next
                    remaining_to_deduct -= goal.current_amount
                    goal.current_amount = Decimal('0.00')
                    goal.save()

            # 6. Create Order
            amount_financed = product.price - down_payment
            order = Order.objects.create(
                user=user,
                product=product,
                total_amount=product.price,
                down_payment=down_payment,
                amount_financed=amount_financed
            )

            # 7. Deduct Koin Score
            User.objects.filter(id=user.id).update(
                koin_score = F('koin_score') - product.required_koin_score
            )
            user.refresh_from_db()
        
        output_serializer = OrderSerializer(order, context={'request': request})
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
class VerifyPickupView(APIView):
    """
    Endpoint for Vendor App to scan QR, verify order, and trigger payout.
    """
    permission_classes = [AllowAny] # In real world, IsVendor permission

    def post(self, request, *args, **kwargs):
        qr_code = request.data.get('pickup_qr_code')
        if not qr_code:
            return Response({"error": "QR code is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Find the order by the unique QR code
            order = Order.objects.get(pickup_qr_code=qr_code)
        except (Order.DoesNotExist, ValidationError):
            return Response({"error": "Invalid or expired QR code."}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'READY_FOR_PICKUP':
            return Response({
                "error": "Order already processed",
                "current_status": order.status
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # 1. Change status to COMPLETED (This starts the user's repayment phase)
            order.status = 'COMPLETED' 
            order.save()
            
            # 2. Simulate Payout to Vendor
            # In a real app, this would trigger a B2C M-Pesa API call
            VendorPayout.objects.create(
                order=order,
                vendor_name=order.product.vendor_name or "Unknown Vendor",
                amount=order.total_amount, # We pay the vendor the full price
                mpesa_transaction_id=f"PAYOUT-{uuid.uuid4().hex[:8].upper()}" # Fake receipt
            )

        # Return details to the Vendor App so they can see what they just scanned
        return Response({
            "success": True,
            "message": "Pickup Confirmed",
            "product": order.product.name,
            "customer": order.user.email,
            "amount_credited": str(order.total_amount)
        }, status=status.HTTP_200_OK)