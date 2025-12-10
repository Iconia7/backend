import json
import uuid
import os
import firebase_admin
from firebase_admin import credentials, messaging, initialize_app
from rest_framework.generics import ListCreateAPIView, ListAPIView, CreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from .permissions import IsOwner
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from decimal import Decimal
import requests

from .models import Goal, Transaction, Product, User, Order, VendorPayout
from .serializers import (
    GoalSerializer, GoalCreateSerializer, TransactionSerializer, ProductSerializer, 
    OrderCreateSerializer, OrderSerializer, FCMTokenSerializer
)
from .payhero_utils import initiate_payhero_push

# --- 1. FIREBASE INITIALIZATION ---
if not firebase_admin._apps:
    firebase_creds_env = os.environ.get('FIREBASE_CREDENTIALS')
    
    if firebase_creds_env:
        cred_dict = json.loads(firebase_creds_env)
        cred = credentials.Certificate(cred_dict)
    elif os.path.exists("serviceAccountKey.json"):
        cred = credentials.Certificate("serviceAccountKey.json")
    else:
        print("WARNING: Firebase credentials not found. Notifications will fail.")
        cred = None

    if cred:
        initialize_app(cred)

def send_fcm_notification(user, title, body, data=None):
    """
    Helper function to send 'Data-Only' messages.
    """
    if not user.fcm_token:
        print(f"User {user.email} has no FCM token. Skipping notification.")
        return

    if data is None:
        data = {}

    data['title'] = title
    data['body'] = body
    
    data_payload = {k: str(v) for k, v in data.items()}

    try:
        message = messaging.Message(
            data=data_payload,
            token=user.fcm_token,
        )
        response = messaging.send(message)
        print('Successfully sent Data message:', response)
    except Exception as e:
        print('Error sending message:', e)

# --- 2. NEW VIEW: Update FCM Token ---
class UpdateFCMTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FCMTokenSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            user.fcm_token = serializer.validated_data['fcm_token']
            user.save()
            return Response({"message": "FCM token updated"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# --- EXISTING VIEWS ---
class GoalListCreateView(ListCreateAPIView):
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
    queryset = Goal.objects.all()
    serializer_class = GoalSerializer
    permission_classes = [IsAuthenticated, IsOwner]

class OrderListView(ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by('-order_date')

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
                amount=Decimal(amount),
                checkout_request_id=external_reference,
                status='pending'
            )
        except Exception as e:
            print(f"Error creating pending transaction: {e}")
            return Response({"error": "Transaction error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        payhero_response = initiate_payhero_push(phone_number, amount, external_reference)
        if not payhero_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"message": "STK push initiated successfully. Please enter your PIN."}, status=status.HTTP_200_OK)

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
                amount=Decimal(amount),
                checkout_request_id=external_reference,
                status='pending'
            )
        except Exception as e:
            print(f"Error creating pending transaction: {e}")
            return Response({"error": "Transaction error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        payhero_response = initiate_payhero_push(phone_number, amount, external_reference)
        if not payhero_response:
            return Response({"error": "Failed to initiate STK push."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"message": "Repayment STK push initiated. Please enter your PIN."}, status=status.HTTP_200_OK)    

# --- 3. CALLBACK VIEW ---
class PaymentCallbackView(APIView):
    def post(self, request, *args, **kwargs):
        print(f"DEBUG: Raw PayHero Payload: {request.data}")

        callback_data = request.data.get('response')
        if not callback_data:
            callback_data = request.data

        external_reference = callback_data.get('ExternalReference') or callback_data.get('User_Reference')
        
        if not external_reference:
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
            existing_transaction = Transaction.objects.filter(checkout_request_id=external_reference).first()
            
            if existing_transaction and existing_transaction.status == 'completed':
                print(f"Duplicate completed transaction ignored: {external_reference}")
                return

            parts = external_reference.split('-')
            tx_type = parts[1].upper() 
            object_id = int(parts[2])
            
            # Handle Failure
            if callback_data.get('ResultCode') != 0 and callback_data.get('Status') != 'Success':
                print(f"Kampus Koin transaction failed at MPESA. Ref: {external_reference}")
                if existing_transaction:
                    existing_transaction.status = 'failed'
                    existing_transaction.save()
                    
                    send_fcm_notification(
                        existing_transaction.owner,
                        "Transaction Failed ⚠️",
                        f"Your {tx_type.lower()} request could not be completed."
                    )
                return

            amount_decimal = Decimal(str(callback_data.get('Amount')))
            receipt_number = callback_data.get('Receipt') or callback_data.get('MpesaReceiptNumber') or callback_data.get('MPESA_Reference')

            if tx_type == 'DEPOSIT':
                with transaction.atomic():
                    goal = Goal.objects.get(id=object_id)
                    user = goal.owner
                    
                    goal.current_amount += amount_decimal
                    koin_to_add = int((amount_decimal / 100) * 15)
                    user.koin_score += koin_to_add
                    
                    goal.save()
                    user.save()
                    
                    if existing_transaction:
                        existing_transaction.status = 'completed'
                        existing_transaction.mpesa_receipt_number = receipt_number
                        existing_transaction.transaction_date = timezone.now()
                        existing_transaction.save()
                    else:
                        Transaction.objects.create(
                            owner=user, goal=goal, transaction_type='DEPOSIT',
                            amount=amount_decimal, mpesa_receipt_number=receipt_number,
                            transaction_date=timezone.now(), 
                            checkout_request_id=external_reference,
                            status='completed'
                        )
                    
                    # TRIGGER NOTIFICATION: DEPOSIT SUCCESS
                    send_fcm_notification(
                        user,
                        "Deposit Received! 💰",
                        f"Ksh. {amount_decimal:,.0f} has been deposited successfully and added to '{goal.name}'.",
                        data={"type": "deposit", "goal_id": str(goal.id), "amount": str(amount_decimal), "goal_name": goal.name}
                    )
                    print(f"Successfully processed deposit for goal {goal.id}")

            elif tx_type == 'REPAYMENT':
                with transaction.atomic():
                    order = Order.objects.get(id=object_id)
                    user = order.user
                    
                    order.amount_paid += amount_decimal
                    
                    if order.amount_paid >= order.amount_financed and order.status != 'PAID':
                        order.status = 'PAID'
                        user.koin_score += 1000 
                        user.save()
                    
                    order.save()
                    
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
                    
                    # TRIGGER NOTIFICATION: REPAYMENT SUCCESS
                    send_fcm_notification(
                        user,
                        "Repayment Confirmed! ✅",
                        f"Ksh. {amount_decimal:,.0f} received for repayment of {order.product.name}.",
                        data={"type": "repayment", "order_id": str(order.id)}
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

class TransactionListView(ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return Transaction.objects.filter(owner=self.request.user).order_by('-created_at')

class ProductListView(ListAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]

# --- 4. UPDATED ORDER CREATE VIEW (Smart Deduction) ---
class OrderCreateView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderCreateSerializer 
    
    def create(self, request, *args, **kwargs):
        input_serializer = OrderCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        
        product_id = input_serializer.validated_data['product_id']
        product = Product.objects.get(id=product_id)
        user = request.user
        
        # New optional fields from frontend: support both single ID or multiple IDs
        specific_goal_id = request.data.get('goal_id') 
        specific_goal_ids = request.data.get('goal_ids', [])

        # Normalize specific_goal_id into the list if present
        if specific_goal_id and not specific_goal_ids:
            specific_goal_ids = [specific_goal_id]

        if user.koin_score < product.required_koin_score:
            raise ValidationError("Your Koin Score is not high enough to unlock this item.")

        if Order.objects.filter(user=user, product=product).exists():
            raise ValidationError("You have already unlocked this item.")

        down_payment = product.price * Decimal('0.25')

        with transaction.atomic():
            # STRATEGY A: Specific Goals Deduction (Multi-select or Single)
            if specific_goal_ids:
                # Fetch only the selected goals belonging to user
                selected_goals = Goal.objects.filter(id__in=specific_goal_ids, owner=user).order_by('created_at')
                
                # Check total funds in selected goals
                total_selected_savings = selected_goals.aggregate(Sum('current_amount'))['current_amount__sum'] or Decimal('0.00')
                
                if total_selected_savings < down_payment:
                    shortfall = down_payment - total_selected_savings
                    raise ValidationError(f"Selected goals have insufficient funds. Total selected: KES {total_selected_savings:,.2f}. Required: KES {down_payment:,.2f}. Shortfall: KES {shortfall:,.2f}.")

                remaining_to_deduct = down_payment
                
                for goal in selected_goals:
                    if remaining_to_deduct <= 0:
                        break
                    
                    if goal.current_amount >= remaining_to_deduct:
                        goal.current_amount -= remaining_to_deduct
                        goal.save()
                        remaining_to_deduct = 0
                    else:
                        remaining_to_deduct -= goal.current_amount
                        goal.current_amount = Decimal('0.00')
                        goal.save()

            # STRATEGY B: General Savings Deduction (The Old/Fallback UX)
            else:
                total_savings = Goal.objects.filter(owner=user).aggregate(Sum('current_amount'))['current_amount__sum'] or Decimal('0.00')

                if total_savings < down_payment:
                    shortfall = down_payment - total_savings
                    raise ValidationError(f"Insufficient savings. Down payment is KES {down_payment:,.2f}. You need KES {shortfall:,.2f} more.")

                remaining_to_deduct = down_payment
                user_goals = Goal.objects.filter(owner=user, current_amount__gt=0).order_by('created_at')

                for goal in user_goals:
                    if remaining_to_deduct <= 0:
                        break
                    
                    if goal.current_amount >= remaining_to_deduct:
                        goal.current_amount -= remaining_to_deduct
                        goal.save()
                        remaining_to_deduct = 0
                    else:
                        remaining_to_deduct -= goal.current_amount
                        goal.current_amount = Decimal('0.00')
                        goal.save()

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
        
        output_serializer = OrderSerializer(order, context={'request': request})
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
class VerifyPickupView(APIView):
    permission_classes = [AllowAny] 

    def post(self, request, *args, **kwargs):
        qr_code = request.data.get('pickup_qr_code')
        if not qr_code:
            return Response({"error": "QR code is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            order = Order.objects.get(pickup_qr_code=qr_code)
        except (Order.DoesNotExist, ValidationError):
            return Response({"error": "Invalid or expired QR code."}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'READY_FOR_PICKUP':
            return Response({
                "error": "Order already processed",
                "current_status": order.status
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            order.status = 'COMPLETED' 
            order.save()
            
            VendorPayout.objects.create(
                order=order,
                vendor_name=order.product.vendor_name or "Unknown Vendor",
                amount=order.total_amount, 
                mpesa_transaction_id=f"PAYOUT-{uuid.uuid4().hex[:8].upper()}" 
            )

        # TRIGGER NOTIFICATION: PICKUP SUCCESS
        send_fcm_notification(
            order.user,
            "Pickup Verified! ✅",
            f"Enjoy your {order.product.name}! Repayment period starts now."
        )

        return Response({
            "success": True,
            "message": "Pickup Confirmed",
            "product": order.product.name,
            "customer": order.user.email,
            "amount_credited": str(order.total_amount)
        }, status=status.HTTP_200_OK)