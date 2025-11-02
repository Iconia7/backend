# users/views.py

from rest_framework.generics import CreateAPIView
from rest_framework.generics import CreateAPIView, RetrieveAPIView 
from rest_framework.permissions import IsAuthenticated 
from .models import User
from .serializers import UserSerializer

class RegisterView(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class MeView(RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated] 

    def get_object(self):
        return self.request.user    