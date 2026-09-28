import csv
import io
import json
import sys
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from part.models import Part
from stock.models import StockItem, StockLocation

from parts_sheet.import_service import import_rows
from parts_sheet.importer import parse_sheets
from parts_sheet.models import ImportPreview, NumberSeries
from parts_sheet.services import edit_parts, serialize_part
from parts_sheet.website import request_sync


def request_rows(*rows):
    return {"key": str(uuid.uuid4()), "rows": list(rows)}


def opening_stock_row(location, **changes):
    return {
        "fields": {"name": "OEM-42", "description": "Drive pulley"},
        "series": NumberSeries.objects.get(prefix="1008").pk,
        "stock": {"quantity": "12.5", "location": location.pk},
        **changes,
    }


def test_native_names_ipn_edits_and_number_high_water(user):
    part = Part.objects.create(name="OEM-OLD", IPN="1008001", description="Pulley")
    row = serialize_part(part, user)
    edit_parts(
        user,
        request_rows(
            {
                "id": part.pk,
                "token": row["token"],
                "ipn": "1008555",
                "fields": {"name": "OEM-NEW", "active": False},
            }
        ),
    )
    part.refresh_from_db()
    assert (part.name, part.IPN, part.description, part.active) == (
        "OEM-NEW",
        "1008555",
        "Pulley",
        False,
    )
    result = edit_parts(
        user,
        request_rows(
            {"fields": {"name": "OTHER-OEM"}, "series": NumberSeries.objects.get(prefix="1008").pk}
        ),
    )
    assert result["rows"][0]["ipn"] == "1008556"
    with pytest.raises(ValidationError, match="another part"):
        edit_parts(
            user,
            request_rows(
                {"id": part.pk, "token": serialize_part(part, user)["token"], "ipn": "1008556"}
            ),
        )


def test_new_part_opening_stock_and_barcode_retry(user):
    location = StockLocation.objects.create(name="Shelf A")
    data = request_rows(opening_stock_row(location))
    result = edit_parts(user, data)
    assert edit_parts(user, data) == result
    item = StockItem.objects.get()
    assert item.part.name == item.barcode_data == "OEM-42"
    assert item.part.description == "Drive pulley"
    assert item.quantity == Decimal("12.5") and item.location == location
    assert item.barcode_hash and result["rows"][0]["stock"]["id"] == item.pk


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "bad", "1.000001"])
def test_invalid_opening_stock_rolls_back_part_and_number(user, quantity):
    location = StockLocation.objects.create(name="Shelf")
    row = opening_stock_row(location, stock={"quantity": quantity, "location": location.pk})
    with pytest.raises(ValidationError):
        edit_parts(user, request_rows(row))
    assert not Part.objects.exists() and not StockItem.objects.exists()
    assert NumberSeries.objects.get(prefix="1008").last_value == 0


def test_location_and_barcode_conflicts_do_not_create_partial_records(user):
    structural = StockLocation.objects.create(name="Building", structural=True)
    with pytest.raises(ValidationError, match="Choose a stock location"):
        edit_parts(user, request_rows(opening_stock_row(structural)))
    shelf = StockLocation.objects.create(name="Shelf")
    edit_parts(user, request_rows(opening_stock_row(shelf)))
    with pytest.raises(ValidationError, match="already assigned"):
        edit_parts(user, request_rows(opening_stock_row(shelf)))
    assert Part.objects.count() == StockItem.objects.count() == 1


def test_stock_permission_is_separate_from_part_permission(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission

    user = get_user_model().objects.create_user("catalogue-only")
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="part", codename__in=["view_part", "add_part"]
        )
    )
    location = StockLocation.objects.create(name="Private shelf")
    client.force_login(user)
    bootstrap = client.get("/plugin/parts-sheet/api/bootstrap/").json()
    assert not bootstrap["stock_add"] and bootstrap["locations"] == []
    with pytest.raises(PermissionDenied):
        edit_parts(user, request_rows(opening_stock_row(location)))
    assert not Part.objects.exists()


def test_page_sizes_and_images(client, user):
    Part.objects.bulk_create([Part(name=f"OEM-{i}", IPN=f"IPN-{i}") for i in range(70)])
    for size, expected in ((25, 25), (50, 50), (100, 70), (200, 70)):
        data = client.get(f"/plugin/parts-sheet/api/rows/?page_size={size}").json()
        assert len(data["rows"]) == expected and data["page_size"] == size
    assert client.get("/plugin/parts-sheet/api/rows/?page_size=999999").status_code == 400
    part = Part.objects.first()
    part.image = "/media/pulley.png"
    assert serialize_part(part, user)["thumbnail"] == "/media/pulley.png"


def test_import_oem_description_mapping_and_missing_oem(user, client):
    rows, _, _ = parse_sheets(
        [
            (
                "Sheet",
                [
                    ["DiCor Part Number", "OEM PN", "Part Description"],
                    ["1008001", "OEM-P", "Pulley"],
                ],
            )
        ]
    )
    preview = ImportPreview.objects.create(key=uuid.uuid4(), user=user, rows=rows)
    import_rows(user, {"key": str(uuid.uuid4()), "preview": str(preview.pk)})
    part = Part.objects.get()
    assert (part.name, part.IPN, part.description) == ("OEM-P", "1008001", "Pulley")
    export = client.get("/plugin/parts-sheet/api/export/").content.decode("utf-8-sig")
    exported = list(csv.DictReader(io.StringIO(export)))[0]
    assert exported["OEM PN"] == "OEM-P" and exported["Part Description"] == "Pulley"
    rows[0]["ipn"] = "1008002"
    rows[0]["cells"].pop("oem_number")
    preview.rows = rows
    preview.save()
    with pytest.raises(ValidationError, match="add an OEM PN"):
        import_rows(user, {"key": str(uuid.uuid4()), "preview": str(preview.pk)})
    assert Part.objects.count() == 1


def test_standalone_website_sync_uses_existing_configuration(user, monkeypatch):
    cache.clear()
    monkeypatch.setenv("WEBSITE_SYNC_LAMBDA_ARN", "test-catalogue-function")
    client = Mock()
    client.invoke.return_value = {"StatusCode": 202}
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=Mock(return_value=client)))
    monkeypatch.setitem(sys.modules, "botocore.config", SimpleNamespace(Config=lambda **kw: kw))
    assert request_sync(user).status_code == 202
    event = json.loads(client.invoke.call_args.kwargs["Payload"])
    assert event["action"] == "sync-website"
    assert client.invoke.call_args.kwargs["InvocationType"] == "Event"
    assert request_sync(user).status_code == 202
    assert client.invoke.call_count == 1
    cache.clear()
