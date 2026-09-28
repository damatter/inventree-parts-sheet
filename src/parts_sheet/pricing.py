"""Adapter to the installed Customer Pricing plugin, never a second price store."""

import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction


def capabilities(user):
    from plugin.registry import registry
    from users.permissions import check_user_role

    installed = registry.get_plugin("customer-pricing", active=True) is not None
    result = {
        "installed": installed,
        "view": False,
        "edit": False,
        "costs": False,
        "message": "Enable the Customer Pricing plugin to use Part Pricing.",
    }
    if not installed:
        return result
    try:
        from inventree_customer_pricing.access import user_has_pricing_access
    except ImportError:
        result["message"] = "Update Customer Pricing to 0.6.1 or later, then restart the server."
        return result
    if user_has_pricing_access(user):
        for key, role, action in (
            ("view", "sales_order", "view"),
            ("edit", "sales_order", "change"),
            ("costs", "purchase_order", "view"),
        ):
            result[key] = bool(user.is_superuser or check_user_role(user, role, action))
    result["edit"] = result["edit"] and result["view"]
    result["message"] = (
        "Choose a customer to show their prices in the sheet, or open Part Pricing on a row."
        if result["view"]
        else "Material costs are available in Part Pricing. Sales permission is required for customer prices."
        if result["costs"]
        else "Ask an administrator for the Customer Pricing access group and sales or purchasing permissions."
    )
    return result


def require(user, edit=False):
    if not capabilities(user)["edit" if edit else "view"]:
        raise PermissionDenied("Part Pricing access and the appropriate sales role are required.")


def price_state(part, customer_id, quantity):
    from inventree_customer_pricing.models import CustomerPriceList

    schedule = CustomerPriceList.objects.filter(part=part, customer_id=customer_id).first()
    data = {"list_id": None, "active": True, "currency": "", "price": "", "break_id": None}
    if schedule:
        tier = schedule.breaks.filter(quantity=quantity).first()
        data.update(
            list_id=schedule.pk,
            active=schedule.active,
            currency=schedule.currency,
            price=str(tier.price) if tier else "",
            break_id=tier.pk if tier else None,
        )
    data["token"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data


def save_price(user, part, values):
    require(user, edit=True)
    from company.models import Company
    from inventree_customer_pricing.models import CustomerPriceBreak, CustomerPriceList
    from inventree_customer_pricing.native_sync import sync_part_sale_prices_safely
    from inventree_customer_pricing.serializers import (
        CustomerPriceBreakSerializer,
        CustomerPriceListSerializer,
    )

    customer = Company.objects.filter(
        pk=values.get("customer"), is_customer=True, active=True
    ).first()
    if not customer:
        raise ValidationError("Choose an active InvenTree customer.")
    # Serializer enforces the pricing plugin's precision and quantity/price limits.
    tier_input = CustomerPriceBreakSerializer(
        data={"quantity": values.get("quantity", 1), "price": values.get("price")}
    )
    tier_input.is_valid(raise_exception=True)
    quantity = tier_input.validated_data["quantity"]
    schedule = (
        CustomerPriceList.objects.select_for_update().filter(part=part, customer=customer).first()
    )
    if schedule:
        list(CustomerPriceBreak.objects.select_for_update().filter(price_list=schedule))
    current = price_state(part, customer.pk, quantity)
    if values.get("token") != current["token"]:
        raise ValidationError("This customer price changed. Reload before saving.")
    if not current["active"]:
        raise ValidationError(
            "This customer's price list is inactive. Activate it in Part Pricing first."
        )
    if schedule and values.get("currency", schedule.currency).upper() != schedule.currency:
        raise ValidationError("Currency must match the customer's existing price list.")
    if schedule is None:
        serializer = CustomerPriceListSerializer(
            data={
                "customer": customer.pk,
                "currency": values.get("currency") or customer.currency or "CAD",
                "active": True,
            }
        )
        serializer.is_valid(raise_exception=True)
        schedule = serializer.save(part=part)
    tier = schedule.breaks.filter(quantity=quantity).first()
    serializer = CustomerPriceBreakSerializer(tier, data=tier_input.validated_data)
    serializer.is_valid(raise_exception=True)
    serializer.save(price_list=schedule)
    # AppMixin can reload model classes without reconnecting the pricing plugin's
    # original signal senders. Explicitly request its idempotent sync after commit
    # so saves and imports still update native pricing in that host lifecycle.
    transaction.on_commit(lambda: sync_part_sale_prices_safely(part.pk))
    return price_state(part, customer.pk, quantity)
