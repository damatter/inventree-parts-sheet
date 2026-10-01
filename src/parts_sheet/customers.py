"""Quick native customer creation, sharing the catalogue's retry protection."""

from company.models import Company
from django.core.exceptions import PermissionDenied, ValidationError
from users.permissions import check_user_permission

from . import pricing
from .models import ChangeRecord
from .services import idempotent, require_part


def can_add_customer(user):
    return bool(pricing.capabilities(user)["edit"] and check_user_permission(user, Company, "add"))


def create_customer(user, payload):
    require_part(user, "view")
    if not can_add_customer(user):
        raise PermissionDenied("Company add and Customer Pricing edit permissions are required.")
    name = str(payload.get("name") or "").strip()
    currency = str(payload.get("currency") or "CAD").strip().upper()
    if not name:
        raise ValidationError("Enter the customer name.")

    def create(series):
        matches = Company.objects.filter(name__iexact=name)
        if matches.exists():
            raise ValidationError(
                "A company with this name already exists. Choose the existing customer, "
                "or review that company in InvenTree instead of creating a duplicate."
            )
        company = Company(
            name=name, currency=currency, is_customer=True, is_supplier=False, active=True
        )
        company.full_clean()
        company.save()
        ChangeRecord.objects.create(user=user, action="customer", details={"company": company.pk})
        return {"id": company.pk, "name": company.name, "currency": company.currency}

    return idempotent(user, payload.get("key"), payload, create)
