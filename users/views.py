# users/views.py

# 1. Import RetrieveUpdateAPIView
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView 
from rest_framework.permissions import IsAuthenticated 
# Import Parsers for File Uploads
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .models import User
# 2. Import the new Update Serializer
from .serializers import UserSerializer, UserUpdateSerializer 

class RegisterView(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

# 3. Change class to RetrieveUpdateAPIView so it handles PATCH requests
class MeView(RetrieveUpdateAPIView): 
    queryset = User.objects.all()
    permission_classes = [IsAuthenticated] 
    
    # NEW: Add parsers to handle both JSON and File Uploads (Multipart)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    # 4. Add this logic to swap serializers
    def get_serializer_class(self):
        # If the user is trying to UPDATE (PUT or PATCH), use the restricted serializer
        if self.request.method in ['PUT', 'PATCH']:
            return UserUpdateSerializer
        # If they are just READING (GET), use the full serializer
        return UserSerializer

    def get_object(self):
        return self.request.user