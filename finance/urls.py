# finance/urls.py

from django.urls import path
from .views import GoalDetailView, GoalListCreateView, DepositView, OrderListView, PaymentCallbackView, RepayView, TransactionListView, ProductListView,OrderCreateView,VerifyPickupView

urlpatterns = [
    path('goals/', GoalListCreateView.as_view(), name='goal-list-create'),
    path('goals/<int:pk>/', GoalDetailView.as_view(), name='goal-detail'),
    path('deposit/', DepositView.as_view(), name='deposit'),
    path('payment-callback/', PaymentCallbackView.as_view(), name='payment-callback'),
    path('transactions/', TransactionListView.as_view(), name='transaction-list'),
    path('products/', ProductListView.as_view(), name='product-list'),
    path('orders/unlock/', OrderCreateView.as_view(), name='order-create'),
    path('repay/', RepayView.as_view(), name='repay'),
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('orders/verify-pickup/', VerifyPickupView.as_view(), name='verify-pickup'),
]