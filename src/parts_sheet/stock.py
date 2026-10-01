"""Create opening stock through the host's normal stock and barcode models."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from stock.models import StockItem, StockLocation
from users.permissions import check_user_permission


def can_add_stock(user):
    return bool(
        check_user_permission(user, StockItem, "add")
        and check_user_permission(user, StockLocation, "view")
    )


def require_stock(user):
    if not can_add_stock(user):
        raise PermissionDenied("Stock add and location view permissions are required.")


def can_view_locations(user):
    return bool(check_user_permission(user, StockLocation, "view"))


def validate_default_location(user, location_id):
    if not can_view_locations(user):
        raise PermissionDenied("Stock location view permission is required.")
    if (
        location_id is not None
        and not StockLocation.objects.filter(pk=location_id, structural=False).exists()
    ):
        raise ValidationError("Choose a stock location that can hold parts.")


def location_options():
    locations = list(StockLocation.objects.values("id", "name", "parent_id", "structural"))
    by_id = {row["id"]: row for row in locations}

    def full_path(row):
        names, seen = [], set()
        while row and row["id"] not in seen:
            names.append(row["name"])
            seen.add(row["id"])
            row = by_id.get(row["parent_id"])
        return " / ".join(reversed(names))

    return sorted(
        [{**row, "pathstring": full_path(row)} for row in locations if not row["structural"]],
        key=lambda row: row["pathstring"].casefold(),
    )


def create_opening_stock(user, part, values):
    require_stock(user)
    if not isinstance(values, dict):
        raise ValidationError("Enter an opening quantity and stock location.")
    try:
        quantity = Decimal(str(values.get("quantity", "")))
    except (InvalidOperation, ValueError):
        raise ValidationError("Opening quantity must be a positive number.") from None
    if not quantity.is_finite() or quantity <= 0:
        raise ValidationError("Opening quantity must be a positive number.")
    location = StockLocation.objects.filter(pk=values.get("location"), structural=False).first()
    if location is None:
        raise ValidationError("Choose a stock location that can hold parts.")
    item = StockItem(part=part, quantity=quantity, location=location)
    # InvenTree enforces its external barcode uniqueness rule here. Never steal
    # a barcode from an existing stock item or silently invent a different code.
    try:
        item.assign_barcode(barcode_data=part.name, save=False)
    except ValidationError as exc:
        raise ValidationError(
            f'OEM PN "{part.name}" is already assigned to a stock item. '
            "Use the existing stock item, or add this part without opening stock."
        ) from exc
    item.full_clean()
    item.save(user=user)
    return {"id": item.pk, "url": f"/web/stock/item/{item.pk}/", "quantity": str(item.quantity)}
