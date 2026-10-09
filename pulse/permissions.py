from rest_framework.permissions import BasePermission
from .models import UserProfile


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and hasattr(request.user, 'profile')
            and request.user.profile.role == UserProfile.Role.ADMIN
        )