import json
import uuid

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from inventree_customer_pricing.models import CustomerPriceBreak, CustomerPriceList
from part.models import Part
from stock.models import StockItem, StockLocation

from parts_sheet.customers import create_customer
from parts_sheet.models import ImportLink, NumberSeries, SheetDetails
from parts_sheet.numbering import snapshot
from parts_sheet.services import delete_part, edit_parts, serialize_part


def deletion(part, user):
    return {"id": part.pk, "token": serialize_part(part, user)["token"], "key": str(uuid.uuid4())}


def test_delete_reclaims_only_tail_keeps_other_numbers_and_retries(user):
    low = Part.objects.create(name="Low", IPN="1008100", active=False)
    middle = Part.objects.create(name="Middle", IPN="1008101", active=False)
    high = Part.objects.create(name="High", IPN="1008102", active=False)
    series = NumberSeries.objects.get(prefix="1008")
    delete_part(user, deletion(middle, user))
    assert snapshot(series)["next"] == "1008103"
    request = deletion(high, user)
    result = delete_part(user, request)
    assert delete_part(user, request) == result
    series.refresh_from_db()
    assert snapshot(series)["next"] == "1008102"
    low.refresh_from_db()
    assert low.IPN == "1008100"
    assert list(Part.objects.values_list("IPN", flat=True)) == ["1008100"]


def test_consecutive_latest_native_deletions_reclaim_one_each_time(user):
    series = NumberSeries.objects.get(prefix="1008")
    rows = edit_parts(
        user,
        {
            "key": str(uuid.uuid4()),
            "rows": [{"series": series.pk, "fields": {"name": f"Part {i}"}} for i in range(3)],
        },
    )["rows"]
    Part.objects.get(pk=rows[2]["id"]).delete()
    series.refresh_from_db()
    assert snapshot(series)["next"] == rows[2]["ipn"]
    Part.objects.get(pk=rows[1]["id"]).delete()
    series.refresh_from_db()
    assert snapshot(series)["next"] == rows[1]["ipn"]
    assert Part.objects.get(pk=rows[0]["id"]).IPN == rows[0]["ipn"]


def test_delete_checks_conflicts_visibility_stock_locked_and_permissions(user):
    part = Part.objects.create(name="In use", IPN="1008100")
    with pytest.raises(ValidationError, match="Visible"):
        delete_part(user, deletion(part, user))
    part.active = False
    part.save()
    request = deletion(part, user)
    part.description = "Changed outside sheet"
    part.save()
    with pytest.raises(ValidationError, match="changed elsewhere"):
        delete_part(user, request)
    part.locked = True
    part.save()
    with pytest.raises(ValidationError, match="locked"):
        delete_part(user, deletion(part, user))
    part.locked = False
    part.save()
    location = StockLocation.objects.create(name="Bin")
    item = StockItem.objects.create(part=part, location=location, quantity=1)
    with pytest.raises(ValidationError, match="stock records"):
        delete_part(user, deletion(part, user))
    assert StockItem.objects.filter(pk=item.pk).exists()
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission

    viewer = get_user_model().objects.create_user("viewer")
    viewer.user_permissions.add(Permission.objects.get(codename="view_part"))
    with pytest.raises(PermissionDenied):
        delete_part(viewer, deletion(part, user))


def test_deleted_import_links_remain_tombstones(user):
    part = Part.objects.create(name="Imported", active=False)
    link = ImportLink.objects.create(fingerprint="test-fingerprint", part=part)
    delete_part(user, deletion(part, user))
    link.refresh_from_db()
    assert link.part_id is None


def test_column_filters_sort_all_rows_and_exact_customer_price(client, user):
    from company.models import Company

    customer = Company.objects.create(name="General Pricing")
    unrelated = Company.objects.create(name="Another customer")
    for index, amount in enumerate((100, 9, 20)):
        part = Part.objects.create(name=f"OEM-{index}", IPN=f"100800{index}", description="Pulley")
        SheetDetails.objects.create(part=part, cells={"material": "Bronze", "size": str(index)})
        price_list = CustomerPriceList.objects.create(part=part, customer=customer)
        CustomerPriceBreak.objects.create(price_list=price_list, quantity=1, price=amount)
        CustomerPriceBreak.objects.create(price_list=price_list, quantity=10, price=1)
        other_list = CustomerPriceList.objects.create(part=part, customer=unrelated)
        CustomerPriceBreak.objects.create(price_list=other_list, quantity=1, price=999)
    endpoint = "/plugin/parts-sheet/api/rows/"
    result = client.get(endpoint, {"customer": customer.pk, "sort": "price"}).json()
    assert [r["name"] for r in result["rows"]] == ["OEM-1", "OEM-2", "OEM-0"]
    result = client.get(
        endpoint, {"customer": customer.pk, "sort": "-price", "price_min": "10", "price_max": "99"}
    ).json()
    assert [r["name"] for r in result["rows"]] == ["OEM-2"]
    result = client.get(
        endpoint, {"filter_description": "pUll", "filter_material": "bron", "filter_size": "1"}
    ).json()
    assert result["total"] == 1 and result["rows"][0]["name"] == "OEM-1"
    result = client.get(endpoint, {"filter_name": "OEM", "sort": "-name"}).json()
    assert [r["name"] for r in result["rows"]] == ["OEM-2", "OEM-1", "OEM-0"]
    assert client.get(endpoint, {"sort": "price"}).status_code == 400


def test_location_paths_include_structural_ancestors_and_saved_default(client, user):
    root = StockLocation.objects.create(name="Warehouse", structural=True)
    aisle = StockLocation.objects.create(name="Aisle 1", parent=root, structural=True)
    shelf = StockLocation.objects.create(
        name="Shelf A", parent=aisle, pathstring="Warehouse / Aisle 1 / Shelf A"
    )
    options = client.get("/plugin/parts-sheet/api/bootstrap/").json()["locations"]
    assert options == [
        {
            "id": shelf.pk,
            "name": "Shelf A",
            "parent_id": aisle.pk,
            "structural": False,
            "pathstring": "Warehouse / Aisle 1 / Shelf A",
        }
    ]
    row = edit_parts(
        user,
        {
            "key": str(uuid.uuid4()),
            "rows": [
                {
                    "series": NumberSeries.objects.get(prefix="1008").pk,
                    "fields": {"name": "OEM-NEW", "default_location_id": shelf.pk},
                    "stock": {"quantity": "3", "location": shelf.pk},
                }
            ],
        },
    )["rows"][0]
    assert row["default_location"] == "Warehouse / Aisle 1 / Shelf A"
    assert Part.objects.get(pk=row["id"]).default_location_id == shelf.pk
    result = client.get(
        "/plugin/parts-sheet/api/rows/", {"filter_default_location": "Warehouse / Aisle"}
    ).json()
    assert result["total"] == 1


def test_number_reservation_does_not_renumber_existing_parts(client, user):
    part = Part.objects.create(name="Existing", IPN="1008002", active=False)
    response = client.post(
        "/plugin/parts-sheet/api/series/",
        json.dumps({"prefix": "1008", "digits": 3, "last": "1008500"}),
        content_type="application/json",
    )
    assert response.json()["next"] == "1008501"
    part.delete()
    series = NumberSeries.objects.get(prefix="1008")
    assert snapshot(series)["next"] == "1008501"


def test_quick_customer_creation_retry_and_duplicate_name_checks(client, user):
    from company.models import Company

    payload = {"key": str(uuid.uuid4()), "name": "New buyer", "currency": "cad"}
    first = create_customer(user, payload)
    assert create_customer(user, payload) == first
    customer = Company.objects.get(pk=first["id"])
    assert customer.is_customer and not customer.is_supplier and customer.currency == "CAD"
    with pytest.raises(ValidationError, match="already exists"):
        create_customer(user, {**payload, "key": str(uuid.uuid4()), "name": " NEW BUYER "})
    supplier = Company.objects.create(name="Supplier only", is_customer=False, is_supplier=True)
    with pytest.raises(ValidationError, match="already exists"):
        create_customer(user, {**payload, "key": str(uuid.uuid4()), "name": supplier.name})
    supplier.refresh_from_db()
    assert not supplier.is_customer
    row = edit_parts(
        user,
        {
            "key": str(uuid.uuid4()),
            "rows": [
                {
                    "fields": {"name": "OEM-PRICED"},
                    "series": NumberSeries.objects.get(prefix="1008").pk,
                    "price": {
                        "customer": customer.pk,
                        "quantity": 1,
                        "price": "21.75",
                        "currency": "CAD",
                    },
                }
            ],
        },
    )["rows"][0]
    assert row["price"]["price"] == "21.750000"
