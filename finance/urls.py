# finance/urls.py

from django.urls import path
from .views import GoalListCreateView, DepositView, MpesaCallbackView, OrderListView, RepayView, TransactionListView, ProductListView,OrderCreateView

urlpatterns = [
    path('goals/', GoalListCreateView.as_view(), name='goal-list-create'),
    path('deposit/', DepositView.as_view(), name='deposit'),
    path('payment-callback/', MpesaCallbackView.as_view(), name='payment-callback'),
    path('transactions/', TransactionListView.as_view(), name='transaction-list'),
    path('products/', ProductListView.as_view(), name='product-list'),
    path('orders/unlock/', OrderCreateView.as_view(), name='order-create'),
    path('repay/', RepayView.as_view(), name='repay'),
    path('orders/', OrderListView.as_view(), name='order-list'),
]