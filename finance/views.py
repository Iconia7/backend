# finance/views.py

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
    GoalSerializer, TransactionSerializer, ProductSerializer, 
    OrderCreateSerializer, OrderSerializer
)
from .mpesa_utils import get_mpesa_access_token, initiate_stk_push

# --- GoalListCreateView (No Change) ---
class GoalListCreateView(ListCreateAPIView):
    serializer_class = GoalSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Goal.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

class OrderListView(ListAPIView):
    """
    API endpoint to list all financed orders for the logged-in user.
    """
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by('-order_date')

# --- DepositView (UPDATED) ---
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

        access_token = get_mpesa_access_token()
        if not access_token:
            return Response({"error": "Could not get M-Pesa access token."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # We pass the goal_id as the AccountReference for our *new* logic
        mpesa_response = initiate_stk_push(phone_number, amount, access_token, goal_id)
        
        if not mpesa_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        response_code = mpesa_response.get('ResponseCode')
        if response_code == "0":
            checkout_request_id = mpesa_response.get('CheckoutRequestID')
            
            # --- UPDATE ---
            Transaction.objects.create(
                owner=user,
                goal=goal, # Link to the goal
                checkout_request_id=checkout_request_id,
                status='pending',
                amount=Decimal(amount),
                transaction_type='DEPOSIT' # Set the type
            )
            # -------------
            return Response({"message": "STK push initiated successfully. Please enter your PIN."}, status=status.HTTP_200_OK)
        else:
            return Response({"error": mpesa_response.get('ResponseDescription')}, status=status.HTTP_400_BAD_REQUEST)

# --- MpesaCallbackView (UPDATED) ---
class MpesaCallbackView(APIView):
    """
    Handles the M-Pesa callback for BOTH deposits and repayments.
    """
    def post(self, request, *args, **kwargs):
        data = request.data
        stk_callback = data.get('Body', {}).get('stkCallback', {})

        checkout_request_id = stk_callback.get('CheckoutRequestID')
        if not checkout_request_id:
            print("Callback received without CheckoutRequestID")
            return Response({"message": "Invalid callback."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # We can't use a single transaction.atomic() block because
            # we need to read the data *after* it has been updated.
            
            # 1. Find the pending transaction
            pending_tx = Transaction.objects.get(
                checkout_request_id=checkout_request_id
            )

            if pending_tx.status == 'completed':
                return Response({"message": "Duplicate callback received."}, status=status.HTTP_200_OK)
            
            # Around line 113 - after getting pending_tx
            print(f"DEBUG: Transaction type: {pending_tx.transaction_type}")
            print(f"DEBUG: Goal ID: {pending_tx.goal_id}")
            print(f"DEBUG: Order ID: {pending_tx.order_id}")

            # 2. Check for a failed M-Pesa transaction
            result_code = stk_callback.get('ResultCode')
            if result_code != 0:
                pending_tx.status = 'failed'
                pending_tx.save()
                print(f"Transaction failed with code {result_code}: {stk_callback.get('ResultDesc')}")
                return Response({"message": "Failed transaction callback received."}, status=status.HTTP_200_OK)

            # --- IF THE TRANSACTION WAS SUCCESSFUL ---
            metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
            meta_dict = {item['Name']: item['Value'] for item in metadata if 'Value' in item}

            amount = meta_dict.get('Amount')
            receipt_number = meta_dict.get('MpesaReceiptNumber')
            amount_decimal = Decimal(str(amount))
            user = pending_tx.owner

            # 3. Update the transaction to 'completed'
            # We do this first to log the successful payment
            pending_tx.amount = amount_decimal
            pending_tx.mpesa_receipt_number = receipt_number
            pending_tx.transaction_date = timezone.now()
            pending_tx.status = 'completed'
            pending_tx.save()

            # 4. --- CHECK THE TRANSACTION TYPE ---
            if pending_tx.transaction_type == 'DEPOSIT':
                print(f"DEBUG: Processing DEPOSIT for goal {pending_tx.goal_id}")
                print(f"DEBUG: Amount to add: {amount_decimal}")
                # It's a GOAL DEPOSIT
                with transaction.atomic():
                    Goal.objects.filter(id=pending_tx.goal_id).update(
                        current_amount=F('current_amount') + amount_decimal
                    )
                    
                    koin_to_add = int((amount_decimal / 100) * 15)
                    User.objects.filter(id=user.id).update(
                        koin_score=F('koin_score') + koin_to_add
                    )

            elif pending_tx.transaction_type == 'REPAYMENT':
                # It's an ORDER REPAYMENT
                with transaction.atomic():
                    # --- THIS IS THE CORRECTED LOGIC ---
                    # 1. Atomically update the order's amount_paid
                    Order.objects.filter(id=pending_tx.order_id).update(
                        amount_paid=F('amount_paid') + amount_decimal
                    )
                    
                    # 2. Get the fully updated order from the database
                    order = Order.objects.get(id=pending_tx.order_id)
                    
                    # 3. Check if the order is now fully paid
                    if order.amount_paid >= order.amount_financed and order.status != 'PAID':
                        order.status = 'PAID'
                        order.save() # Save the new status
                        
                        # 4. Reward the user for paying it off
                        User.objects.filter(id=user.id).update(
                            koin_score=F('koin_score') + 1000
                        )
                    # ----------------------------------

        except Transaction.DoesNotExist:
            print(f"Callback received for unknown CheckoutRequestID: {checkout_request_id}")
        except Exception as e:
            print(f"An error occurred while processing callback: {e}")
            
        return Response({"message": "Callback processed successfully"}, status=status.HTTP_200_OK)

# --- TransactionListView (No Change) ---
class TransactionListView(ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Transaction.objects.filter(owner=self.request.user).order_by('-created_at')

# --- ProductListView (No Change) ---
class ProductListView(ListAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]

class RepayView(APIView):
    """
    Handles initiating an M-Pesa STK push for repaying an order.
    """
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

        access_token = get_mpesa_access_token()
        if not access_token:
            return Response({"error": "Could not get M-Pesa access token."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # We'll pass the order_id as the AccountReference
        mpesa_response = initiate_stk_push(phone_number, amount, access_token, order_id)
        
        if not mpesa_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        response_code = mpesa_response.get('ResponseCode')
        if response_code == "0":
            checkout_request_id = mpesa_response.get('CheckoutRequestID')
            
            # Create a PENDING transaction linked to the ORDER
            Transaction.objects.create(
                owner=user,
                order=order, # Link to the order
                checkout_request_id=checkout_request_id,
                status='pending',
                amount=Decimal(amount),
                transaction_type='REPAYMENT' # Set the type
            )
            return Response({"message": "Repayment STK push initiated. Please enter your PIN."}, status=status.HTTP_200_OK)
        else:
            return Response({"error": mpesa_response.get('ResponseDescription')}, status=status.HTTP_400_BAD_REQUEST)    

# --- OrderCreateView (No Change) ---
class OrderCreateView(CreateAPIView):
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
        output_serializer = self.get_serializer(order)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)