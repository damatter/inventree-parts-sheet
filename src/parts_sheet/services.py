"""Transactional catalogue edits and allocation."""

import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from part.models import Part
from users.permissions import check_user_permission

from . import pricing
from .models import ChangeRecord, Operation, SheetDetails
from .numbering import allocate, lock_series, observe
from .stock import (
    can_view_locations,
    create_opening_stock,
    require_stock,
    validate_default_location,
)

FIELDS = (
    "name",
    "description",
    "category_id",
    "active",
    "assembly",
    "component",
    "purchaseable",
    "salable",
    "default_location_id",
)
CELL_FIELDS = (
    "required",
    "oem_number",
    "drawing",
    "make_model",
    "material",
    "size",
    "notes",
    "date_priced",
)
LEGACY_PRICE_FIELDS = ("oem_usd", "supplier_cad", "sell_cad")


def require_part(user, action):
    if not check_user_permission(user, Part, action):
        raise PermissionDenied(f"You need part {action} permission.")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def part_state(part):
    try:
        cells = dict(part.sheet_details.cells)
    except SheetDetails.DoesNotExist:
        cells = {}
    return {
        **{field: getattr(part, field) for field in FIELDS},
        "ipn": part.IPN or "",
        "revision": part.revision or "",
        "cells": cells,
    }


def serialize_part(part, user):
    data = part_state(part)
    token = digest(data)
    caps = pricing.capabilities(user)
    if not caps["costs"]:
        for key in ("oem_usd", "supplier_cad"):
            data["cells"].pop(key, None)
    if not caps["view"]:
        data["cells"].pop("sell_cad", None)
    return {
        **data,
        "id": part.pk,
        "token": token,
        "url": f"/web/part/{part.pk}/",
        "category": str(part.category) if part.category_id else "Uncategorised",
        "thumbnail": part.get_thumbnail_url() if part.image else "",
        "image": part.get_image_url() if part.image else "",
        "default_location": (
            part.default_location.pathstring or part.default_location.name
            if part.default_location_id and can_view_locations(user)
            else ""
        ),
    }


def idempotent(user, key, payload, action):
    try:
        key = uuid.UUID(str(key))
    except ValueError as exc:
        raise ValidationError("A valid operation key is required.") from exc
    with transaction.atomic():
        series = lock_series()
        receipt = Operation.objects.filter(pk=key).first()
        fingerprint = digest(payload)
        if receipt:
            if receipt.user_id != user.pk or receipt.digest != fingerprint:
                raise ValidationError("This operation key belongs to another request.")
            return receipt.result
        result = action(series)
        Operation.objects.create(key=key, user=user, digest=fingerprint, result=result)
        return result


def edit_parts(user, payload):
    require_part(user, "view")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValidationError("Save between 1 and 200 rows at a time.")
    ids = [r.get("id") for r in rows if r.get("id")]
    if len(ids) != len(set(ids)):
        raise ValidationError("A part can only appear once in a save.")
    # Recheck permissions before replaying a receipt, too: a user's access may
    # have changed since their original request.
    for row in rows:
        if not row.get("id"):
            require_part(user, "add")
        elif row.get("fields") or row.get("cells") or "ipn" in row:
            require_part(user, "change")
        if row.get("stock") is not None:
            require_stock(user)
            if row.get("id"):
                raise ValidationError("Opening stock can only be added with a new part.")
        if row.get("price") is not None:
            pricing.require(user, edit=True)

    def save(series):
        saved = []
        for row in rows:
            creating = not row.get("id")
            part_changes = row.get("fields", {})
            cells = row.get("cells", {})
            if not isinstance(part_changes, dict) or not isinstance(cells, dict):
                raise ValidationError("Invalid row cells.")
            if creating:
                require_part(user, "add")
                number = str(row.get("ipn") or "").strip()
                if not number:
                    selected = next((s for s in series if s.pk == int(row.get("series", 0))), None)
                    if selected is None:
                        raise ValidationError("Choose a number series for each new part.")
                    number = allocate(selected)
                if Part.objects.filter(IPN__iexact=number).exists():
                    raise ValidationError(f"{number} already exists. Open that part instead.")
                part = Part(IPN=number, active=False, component=True, salable=True)
                before = None
            else:
                part = Part.objects.select_for_update().get(pk=row["id"])
                before = part_state(part)
                if row.get("token") != digest(before):
                    raise ValidationError(
                        f"{part.IPN or part.name} changed elsewhere. Reload before saving."
                    )
                if part_changes or cells:
                    require_part(user, "change")
                if "ipn" in row:
                    number = str(row["ipn"] or "").strip()
                    if not number:
                        raise ValidationError("Enter the DiCor part number (internal part number).")
                    if Part.objects.filter(IPN__iexact=number).exclude(pk=part.pk).exists():
                        raise ValidationError(f"{number} already belongs to another part.")
                    part.IPN = number
            if set(part_changes) - set(FIELDS):
                raise ValidationError("That part field cannot be edited here.")
            if set(cells) - set(CELL_FIELDS):
                raise ValidationError("That supplemental cell cannot be edited here.")
            for field, value in part_changes.items():
                if field == "default_location_id":
                    validate_default_location(user, value)
                if (
                    field in ("active", "assembly", "component", "purchaseable", "salable")
                    and type(value) is not bool
                ):
                    raise ValidationError("Status fields must be true or false.")
                setattr(part, field, value)
            if "name" in part_changes:
                part.name = str(part.name or "").strip()
                if not part.name:
                    raise ValidationError("Enter the OEM PN. This is the InvenTree part name.")
            if creating or part_changes or "ipn" in row:
                part.full_clean()
                part.save()
            stock_result = None
            if row.get("stock") is not None:
                stock_result = create_opening_stock(user, part, row["stock"])
            if cells:
                if any(not isinstance(v, str) or len(v) > 2000 for v in cells.values()):
                    raise ValidationError(
                        "Supplemental cells must be text of at most 2000 characters."
                    )
                details, _ = SheetDetails.objects.get_or_create(part=part)
                details.cells = {**details.cells, **cells}
                details.save()
            price_result = None
            if row.get("price") is not None:
                price_values = dict(row["price"])
                if creating:
                    price_values["token"] = pricing.price_state(
                        part, price_values.get("customer"), price_values.get("quantity", 1)
                    )["token"]
                price_result = pricing.save_price(user, part, price_values)
            observe(part.IPN or "", series)
            part = Part.objects.select_related("category", "sheet_details").get(pk=part.pk)
            ChangeRecord.objects.create(
                user=user,
                action="create" if creating else "edit",
                details={
                    "part": part.pk,
                    "ipn": part.IPN,
                    "before": before,
                    "after": part_state(part),
                    "pricing_changed": price_result is not None,
                    "stock_item": stock_result["id"] if stock_result else None,
                },
            )
            saved.append(
                {**serialize_part(part, user), "price": price_result, "stock": stock_result}
            )
        return {"rows": saved}

    result = idempotent(user, payload.get("key"), payload, save)
    caps = pricing.capabilities(user)
    # Receipts may outlive a user's access-group membership. Apply today's
    # sensitive-data policy to cached responses as well as newly saved rows.
    for row in result["rows"]:
        if not caps["costs"]:
            for key in ("oem_usd", "supplier_cad"):
                row["cells"].pop(key, None)
        if not caps["view"]:
            row["cells"].pop("sell_cad", None)
            row.pop("price", None)
    return result


def delete_part(user, payload):
    require_part(user, "view")
    require_part(user, "delete")

    def remove(series):
        from stock.models import StockItem

        part = Part.objects.select_for_update().get(pk=payload.get("id"))
        before = part_state(part)
        if payload.get("token") != digest(before):
            raise ValidationError("This part changed elsewhere. Refresh before deleting it.")
        if part.active:
            raise ValidationError("Uncheck Visible and save the part before deleting it.")
        if StockItem.objects.filter(part=part).exists():
            raise ValidationError("This part has stock records. Manage those in InvenTree first.")
        part_id = part.pk
        try:
            # Native checks (locked part, assembly usage, protected relations)
            # remain authoritative; never bypass the model with bulk deletion.
            part.delete()
        except ProtectedError as exc:
            raise ValidationError(
                "Other records still use this part. Open it in InvenTree to review them."
            ) from exc
        ChangeRecord.objects.create(
            user=user, action="delete", details={"part": part_id, "before": before}
        )
        return {"deleted": part_id}

    return idempotent(user, payload.get("key"), payload, remove)
