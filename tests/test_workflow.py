import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from company.models import Company
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from inventree_customer_pricing.models import (
    CustomerPriceBreak,
    CustomerPriceList,
    PartPricingPolicy,
)
from part.models import Part, PartSellPriceBreak

from parts_sheet import pricing
from parts_sheet.import_service import import_rows
from parts_sheet.importer import classify, parse_sheets
from parts_sheet.models import ImportPreview, NumberSeries, SheetDetails
from parts_sheet.services import edit_parts, serialize_part


def payload(rows):
    return {"key": str(uuid.uuid4()), "rows": rows}


def new(name="Pulley", **kwargs):
    return {
        "fields": {"name": name},
        "series": NumberSeries.objects.get(prefix="1008").pk,
        **kwargs,
    }


def test_allocation_scans_native_and_does_not_follow_other_formats(user):
    for ipn in ("1008927", "85006407", "750XX304DC", "10089999"):
        Part.objects.create(name="Existing", IPN=ipn)
    result = edit_parts(user, payload([new()]))["rows"][0]
    assert result["ipn"] == "1008928"
    assert result["active"] is False
    assert result["url"] == f"/web/part/{result['id']}/"


def test_retries_create_once_and_reclaim_latest_number_after_native_delete(user):
    p = payload([new()])
    first = edit_parts(user, p)
    assert edit_parts(user, p) == first
    part = Part.objects.get(pk=first["rows"][0]["id"])
    number = int(part.IPN)
    part.delete()
    assert int(edit_parts(user, payload([new()]))["rows"][0]["ipn"]) == number


def test_atomic_validation_rolls_back_entire_batch_and_counter(user):
    before = NumberSeries.objects.get(prefix="1008").last_value
    with pytest.raises(ValidationError):
        edit_parts(user, payload([new(), new(name="")]))
    assert Part.objects.count() == 0
    assert NumberSeries.objects.get(prefix="1008").last_value == before


def test_special_numbers_preserved_and_duplicate_rejected(user):
    assert edit_parts(user, payload([new(ipn="HYD 704-6")]))["rows"][0]["ipn"] == "HYD 704-6"
    with pytest.raises(ValidationError, match="already exists"):
        edit_parts(user, payload([new(ipn="hyd 704-6")]))


def test_exhausted_series_stops(user):
    NumberSeries.objects.filter(prefix="1008").update(reserved_through=999)
    with pytest.raises(ValidationError, match="full"):
        edit_parts(user, payload([new()]))


def test_stale_edit_preserves_external_changes(user):
    part = Part.objects.create(IPN="1008001", name="Old")
    row = serialize_part(part, user)
    part.name = "Changed elsewhere"
    part.save()
    with pytest.raises(ValidationError, match="changed elsewhere"):
        edit_parts(user, payload([{**row, "fields": {"active": False}, "cells": {}}]))
    part.refresh_from_db()
    assert part.active is True


def test_native_active_and_supplemental_cells_save_without_replacing_part(user):
    part = Part.objects.create(IPN="1008001", name="Old")
    row = serialize_part(part, user)
    result = edit_parts(
        user,
        payload(
            [
                {
                    "id": part.pk,
                    "token": row["token"],
                    "fields": {"name": "New", "active": False},
                    "cells": {"material": "Bronze"},
                }
            ]
        ),
    )
    assert result["rows"][0]["id"] == part.pk
    part.refresh_from_db()
    assert not part.active and part.name == "New"
    assert part.sheet_details.cells["material"] == "Bronze"


def test_actual_customer_pricing_and_native_sync(user):
    customer = Company.objects.create(name="Customer")
    part = Part.objects.create(name="Part", IPN="1008001")
    state = pricing.price_state(part, customer.pk, 1)
    values = {
        "customer": customer.pk,
        "quantity": 1,
        "price": "24.50",
        "currency": "CAD",
        "token": state["token"],
    }
    row = serialize_part(part, user)
    edit_parts(user, payload([{"id": part.pk, "token": row["token"], "price": values}]))
    price_list = CustomerPriceList.objects.get(part=part, customer=customer)
    assert price_list.breaks.get(quantity=1).price == Decimal("24.5")
    assert PartSellPriceBreak.objects.get(part=part).price.amount == Decimal("24.5")
    assert PartPricingPolicy.objects.get(part=part).last_sync_error == ""


def test_create_part_and_customer_price_in_one_save(user):
    customer = Company.objects.create(name="Customer")
    result = edit_parts(
        user,
        payload(
            [
                new(
                    price={
                        "customer": customer.pk,
                        "quantity": 1,
                        "price": "32.50",
                        "currency": "CAD",
                    }
                )
            ]
        ),
    )
    part = Part.objects.get(pk=result["rows"][0]["id"])
    assert CustomerPriceList.objects.get(part=part).breaks.get(quantity=1).price == Decimal("32.5")


def test_sync_survives_missing_pricing_signals_and_waits_for_commit(user, monkeypatch):
    from inventree_customer_pricing import signals

    monkeypatch.setattr(signals, "_queue_sync", lambda part_id: None)
    customer = Company.objects.create(name="Customer")
    request = payload([new(price={"customer": customer.pk, "price": "32.50", "currency": "CAD"})])
    with transaction.atomic():
        result = edit_parts(user, request)
        assert not PartSellPriceBreak.objects.exists()
    part = Part.objects.get(pk=result["rows"][0]["id"])
    assert PartSellPriceBreak.objects.get(part=part).price.amount == Decimal("32.5")

    with pytest.raises(ValidationError):
        edit_parts(
            user, payload([new(price={"customer": customer.pk, "price": "99"}), new(name="")])
        )
    assert Part.objects.count() == 1
    assert PartSellPriceBreak.objects.count() == 1


def test_price_edits_preserve_other_tiers_and_customers(user):
    part = Part.objects.create(name="Part")
    a = Company.objects.create(name="A")
    b = Company.objects.create(name="B")
    for customer in (a, b):
        price_list = CustomerPriceList.objects.create(part=part, customer=customer, currency="CAD")
        for qty in (1, 10):
            CustomerPriceBreak.objects.create(price_list=price_list, quantity=qty, price=20)
    state = pricing.price_state(part, a.pk, 1)
    pricing.save_price(
        user,
        part,
        {
            "customer": a.pk,
            "quantity": 1,
            "price": "25",
            "currency": "CAD",
            "token": state["token"],
        },
    )
    assert CustomerPriceBreak.objects.filter(price=20).count() == 3
    with pytest.raises(ValidationError, match="changed"):
        pricing.save_price(
            user, part, {"customer": a.pk, "quantity": 1, "price": "26", "token": state["token"]}
        )


def test_price_permissions_fail_closed_and_legacy_costs_are_hidden(user):
    from django.contrib.auth import get_user_model

    limited = get_user_model().objects.create_user("limited")
    part = Part.objects.create(name="Part")
    SheetDetails.objects.create(
        part=part, cells={"oem_usd": "50", "sell_cad": "90", "material": "Steel"}
    )
    assert serialize_part(part, limited)["cells"] == {"material": "Steel"}
    with pytest.raises(PermissionDenied):
        pricing.save_price(limited, part, {})
    with pytest.raises(PermissionDenied):
        edit_parts(limited, payload([new()]))


def test_workbook_parser_preserves_identifiers_notes_and_ignores_bom():
    data = [
        (
            "Drive Mount",
            [
                ["Last Number Used:", "", 1008272],
                [
                    "Part Description",
                    "DiCor Part Number",
                    "Local Supplier (CAD)",
                    "",
                    "Date Priced",
                ],
                ["Section"],
                ["Pulley", 1008927.0, "69.00 USD", "Important note", "Sept./26"],
                ["Special", "750XX304DC", 0, "", ""],
            ],
        ),
        ("BOM", [["Part Description", "Material Spec"], ["Motor", "ABC"]]),
    ]
    rows, warnings, counters = parse_sheets(data)
    assert len(rows) == 2 and rows[0]["ipn"] == "1008927"
    assert rows[0]["cells"]["supplier_cad"] == "69.00 USD"
    assert rows[0]["cells"]["notes"] == "Important note"
    assert rows[1]["ipn"] == "750XX304DC" and counters["1008"] == 272
    assert len(warnings) == 2


def test_duplicate_or_revised_native_ipn_is_ambiguous():
    Part.objects.create(name="A", IPN="X")
    Part.objects.create(name="B", IPN="X", revision="2")
    assert classify([{"name": "X", "ipn": "X"}])[0]["status"] == "conflict"
    assert (
        classify([{"name": "X", "ipn": "a"}, {"name": "Y", "ipn": "A"}])[0]["status"] == "conflict"
    )


def test_import_matching_new_unnumbered_idempotence_and_prices(user):
    customer = Company.objects.create(name="Customer")
    existing = Part.objects.create(name="Native name", IPN="1008927", active=True)
    price_list = CustomerPriceList.objects.create(part=existing, customer=customer, currency="CAD")
    CustomerPriceBreak.objects.create(price_list=price_list, quantity=1, price=99)
    rows = [
        {
            "source": "Sheet:9",
            "name": "Spreadsheet name",
            "ipn": "1008927",
            "cells": {"sell_cad": "10", "material": "Bronze"},
        },
        {
            "source": "Sheet:10",
            "name": "New part",
            "ipn": "1008005",
            "cells": {"sell_cad": "20", "oem_number": "OEM-005"},
        },
        {"source": "Sheet:11", "name": "No number", "ipn": "", "cells": {"oem_number": "OEM-006"}},
    ]
    preview = ImportPreview.objects.create(
        key=uuid.uuid4(), user=user, rows=rows, counters={"1008": 272}
    )
    data = {
        "key": str(uuid.uuid4()),
        "preview": str(preview.pk),
        "include_unnumbered": True,
        "series": NumberSeries.objects.get(prefix="1008").pk,
        "customer": customer.pk,
    }
    result = import_rows(user, data)
    assert result == {"created": 2, "matched": 1, "skipped": 0, "prices_added": 1, "prices_kept": 1}
    existing.refresh_from_db()
    assert existing.name == "Native name" and existing.active
    assert Part.objects.get(name="OEM-006").IPN == "1008928"
    assert Part.objects.get(name="OEM-005").description == "New part"
    assert import_rows(user, data) == result
    data["key"] = str(uuid.uuid4())
    assert import_rows(user, data)["created"] == 0
    assert CustomerPriceBreak.objects.get(price_list=price_list).price == 99


def test_all_catalogue_rows_and_part_links(client):
    Part.objects.create(name="Outside workbook", IPN="ABC-42")
    data = client.get("/plugin/parts-sheet/api/rows/").json()
    assert data["total"] == 1 and data["rows"][0]["ipn"] == "ABC-42"


def test_csrf_and_unauthenticated_writes(user):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    assert client.get("/plugin/parts-sheet/api/rows/").status_code == 302
    client.force_login(user)
    assert (
        client.post(
            "/plugin/parts-sheet/api/save/",
            data=json.dumps(payload([new()])),
            content_type="application/json",
        ).status_code
        == 403
    )


def test_page_and_asset_routes(client):
    response = client.get("/plugin/parts-sheet/")
    assert (
        response.status_code == 200 and b"/plugin/parts-sheet/assets/sheet.js" in response.content
    )
    assert client.get("/plugin/parts-sheet/assets/secret.py").status_code == 404


def test_disabled_pricing_does_not_break_catalogue(client):
    from plugin.registry import registry

    registry.active = False
    assert client.get("/plugin/parts-sheet/api/bootstrap/").json()["pricing"]["installed"] is False
    assert client.get("/plugin/parts-sheet/api/rows/?customer=1").status_code == 200


def test_corrupt_workbook_returns_useful_error(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = client.post(
        "/plugin/parts-sheet/api/preview/",
        {"file": SimpleUploadedFile("broken.xls", b"not a workbook")},
    )
    assert response.status_code == 400
    assert "could not be read" in response.json()["error"]


def test_receipt_does_not_expose_prices_after_group_access_revoked(user):
    from django.contrib.auth.models import Permission

    part = Part.objects.create(name="Part", IPN="1008001")
    SheetDetails.objects.create(part=part, cells={"oem_usd": "50", "sell_cad": "90"})
    state = serialize_part(part, user)
    data = payload([{"id": part.pk, "token": state["token"], "fields": {"name": "New"}}])
    assert edit_parts(user, data)["rows"][0]["cells"]["sell_cad"] == "90"
    user.is_superuser = False
    user.save()
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_part", "change_part"]))
    assert edit_parts(user, data)["rows"][0]["cells"] == {}


def test_export_formula_injection_and_filters(client):
    Part.objects.create(name='=HYPERLINK("bad")', IPN="1008001", active=False)
    response = client.get("/plugin/parts-sheet/api/export/?active=false")
    assert "'=HYPERLINK" in response.content.decode()
    assert client.get("/plugin/parts-sheet/api/rows/?active=true").json()["total"] == 0


def test_admin_counter_cannot_move_back(client):
    Part.objects.create(name="Existing", IPN="1008927")
    result = client.post(
        "/plugin/parts-sheet/api/series/",
        data=json.dumps(
            {"prefix": "1008", "label": "Manufactured", "digits": 3, "last": "1008000"}
        ),
        content_type="application/json",
    )
    assert result.json()["next"] == "1008928"


def test_parallel_creates_have_distinct_numbers(user):
    # File-backed SQLite fixture below is used for concurrency, not :memory:.
    from django.db import connection

    if "memory" in str(connection.settings_dict["NAME"]):
        pytest.skip("Run concurrency check against file-backed SQLite or PostgreSQL")
    user_id = user.pk
    series_id = NumberSeries.objects.get(prefix="1008").pk

    def create(index):
        from django.contrib.auth import get_user_model

        close_old_connections()
        try:
            return edit_parts(
                get_user_model().objects.get(pk=user_id),
                payload([{"series": series_id, "fields": {"name": f"Part {index}"}}]),
            )["rows"][0]["ipn"]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(create, range(8)))
    assert len(set(values)) == 8
