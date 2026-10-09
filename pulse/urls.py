from django.urls import path
from .views import (
    RegisterView, LoginView, AlertListCreateView,
    AlertDeactivateView, get_flight_price, AdminSummaryView
)

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('alerts/', AlertListCreateView.as_view(), name='alerts'),
    path('alerts/<int:id>/', AlertDeactivateView.as_view(), name='alert-deactivate'),
    path('flights/price/', get_flight_price, name='flight-price'),
    path('admin/summary/', AdminSummaryView.as_view(), name='admin-summary'),
]