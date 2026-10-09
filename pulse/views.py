from django.shortcuts import get_object_or_404
import random
from django.http import Http404, JsonResponse
from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework_simplejwt.tokens import AccessToken

from .models import PriceAlert, NotificationLog
from .serializers import RegisterSerializer, LoginSerializer, PriceAlertSerializer
from .permissions import IsAdminUser


MOCK_PRICES = {
    'DEL-BOM': (3000, 7000),
    'BLR-HYD': (1500, 4000),
    'DEL-BLR': (4000, 9000),
    'BOM-GOA': (2000, 5000),
}


class RegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        user = User.objects.create_user(
            username=data['username'],
            password=data['password'],
            email=data['email'],
        )

        access_token = str(AccessToken.for_user(user))

        return Response({
            'username': user.username,
            'access': access_token,
            'role': user.profile.role,
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(username=username, password=password)
        if user is None:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        access_token = str(AccessToken.for_user(user))

        return Response({
            'access': access_token,
            'role': user.profile.role,
        }, status=status.HTTP_200_OK)


class AlertListCreateView(ListCreateAPIView):
    serializer_class = PriceAlertSerializer

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AlertDeactivateView(APIView):
    def delete(self, request, id):
        alert = get_object_or_404(PriceAlert, id=id)
        if alert.user != request.user:
            raise Http404("No PriceAlert matches the given query.")

        alert.status = PriceAlert.Status.INACTIVE
        alert.save()

        return Response({'status': 'inactive'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def get_flight_price(request):
    route = request.GET.get('route', '')
    price_range = MOCK_PRICES.get(route)

    if not price_range:
        return JsonResponse({'error': 'Route not found'}, status=404)

    price = random.randint(*price_range)
    return JsonResponse({'route': route, 'price': price})


class AdminSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        alert_counts = PriceAlert.objects.aggregate(
            total_alerts=Count('id'),
            active_alerts=Count('id', filter=models.Q(status=PriceAlert.Status.ACTIVE)),
            triggered_alerts=Count('id', filter=models.Q(status=PriceAlert.Status.TRIGGERED)),
        )

        total_notifications = NotificationLog.objects.aggregate(total=Count('id'))['total']

        top_routes = (
            PriceAlert.objects
            .values('origin', 'destination')
            .annotate(alert_count=Count('id'))
            .order_by('-alert_count')[:5]
        )

        top_routes_formatted = [
            {'route': f"{r['origin']}-{r['destination']}", 'alert_count': r['alert_count']}
            for r in top_routes
        ]

        return Response({
            'total_alerts': alert_counts['total_alerts'],
            'active_alerts': alert_counts['active_alerts'],
            'triggered_alerts': alert_counts['triggered_alerts'],
            'total_notifications': total_notifications,
            'top_routes': top_routes_formatted,
        }, status=status.HTTP_200_OK)