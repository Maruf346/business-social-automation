from django.contrib.auth.base_user import BaseUserManager
from .choices import UserType

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email: raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields )
        user.set_password(password)
        user.user_type = UserType.ADMIN
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, user_type=UserType.SUPER_ADMIN, **extra_fields )


