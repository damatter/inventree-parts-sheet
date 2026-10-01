"""Run inside the official InvenTree container, after installing both plugins."""

import json
import uuid
from decimal import Decimal
from io import BytesIO

from company.models import Company
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.client import encode_multipart
from inventree_customer_pricing.models import CustomerPriceList, PartPricingPolicy
from part.models import Part, PartSellPriceBreak
from PIL import Image
from plugin.registry import registry
from stock.models import StockItem, StockLocation

from parts_sheet.customers import create_customer
from parts_sheet.models import NumberSeries
from parts_sheet.numbering import snapshot
from parts_sheet.pricing import price_state
from parts_sheet.services import delete_part, edit_parts

assert registry.get_plugin("parts-sheet", active=True), "Parts Sheet failed plugin discovery"
assert registry.get_plugin("customer-pricing", active=True), "Customer Pricing did not activate"
user = get_user_model().objects.create_superuser("parts-sheet-smoke", password=uuid.uuid4().hex)
customer = Company.objects.create(name="Smoke customer", is_customer=True, currency="CAD")
location = StockLocation.objects.create(name="Smoke shelf")
series = NumberSeries.objects.get(prefix="1008")
Part.objects.create(name="Existing catalogue part", IPN="1008927")
payload = {
    "key": str(uuid.uuid4()),
    "rows": [
        {
            "series": series.pk,
            "fields": {
                "name": "OEM-SMOKE-42",
                "description": "Manufactured part",
                "assembly": True,
            },
            "stock": {"quantity": "5", "location": location.pk},
        }
    ],
}
created = edit_parts(user, payload)["rows"][0]
assert created["ipn"] == "1008928"
assert edit_parts(user, payload)["rows"][0]["id"] == created["id"]
part = Part.objects.get(pk=created["id"])
stock = StockItem.objects.get(part=part)
assert stock.barcode_data == "OEM-SMOKE-42" and stock.quantity == 5 and stock.location == location
assert stock.barcode_hash and stock.tracking_info.exists()
assert StockItem.lookup_barcode(stock.barcode_hash).pk == stock.pk
state = price_state(part, customer.pk, 1)
edit_parts(
    user,
    {
        "key": str(uuid.uuid4()),
        "rows": [
            {
                "id": part.pk,
                "token": created["token"],
                "fields": {"active": True},
                "ipn": "1008930",
                "price": {
                    "customer": customer.pk,
                    "quantity": 1,
                    "price": "42.50",
                    "currency": "CAD",
                    "token": state["token"],
                },
            }
        ],
    },
)
assert CustomerPriceList.objects.get(part=part).breaks.get(quantity=1).price == Decimal("42.50")
policy = PartPricingPolicy.objects.filter(part=part).first()
assert policy is not None, "Customer Pricing synchronization signal did not run"
assert not policy.last_sync_error, policy.last_sync_error
assert PartSellPriceBreak.objects.get(part=part).price.amount == Decimal("42.50")
part.refresh_from_db()
assert part.active and part.assembly
assert part.IPN == "1008930" and part.name == "OEM-SMOKE-42"
assert part.description == "Manufactured part"
client = Client(HTTP_HOST="localhost")
client.force_login(user)
assert client.get("/plugin/parts-sheet/").status_code == 200
response = client.get("/plugin/parts-sheet/api/bootstrap/")
assert response.status_code == 200, response.content
assert response.json()["pricing"]["edit"]
assert any(row["id"] == customer.pk for row in response.json()["customers"])
assert any(row["id"] == location.pk for row in response.json()["locations"])
assert response.json()["stock_add"]
response = client.get("/plugin/parts-sheet/api/rows/")
assert response.status_code == 200, response.content
assert any(row["id"] == part.pk for row in json.loads(response.content)["rows"])

# Exercise native company validation, full stock paths, filtering, and deletion
# signals after InvenTree's dynamic plugin/model discovery has completed.
buyer = create_customer(
    user, {"key": str(uuid.uuid4()), "name": "New smoke buyer", "currency": "CAD"}
)
assert Company.objects.get(pk=buyer["id"]).is_supplier is False
root_location = StockLocation.objects.create(name="Smoke building", structural=True)
bin_location = StockLocation.objects.create(name="Smoke bin", parent=root_location)
new_payload = {
    "key": str(uuid.uuid4()),
    "rows": [
        {
            "series": series.pk,
            "fields": {"name": "OEM-FULL-CREATE", "default_location_id": bin_location.pk},
            "price": {"customer": buyer["id"], "quantity": 1, "price": "17.25", "currency": "CAD"},
        }
    ],
}
created_row = edit_parts(user, new_payload)["rows"][0]
created_part = Part.objects.get(pk=created_row["id"])
assert created_part.default_location_id == bin_location.pk
assert "Smoke building" in created_row["default_location"]
assert CustomerPriceList.objects.get(part=created_part).breaks.get(quantity=1).price == Decimal(
    "17.25"
)
response = client.get(
    "/plugin/parts-sheet/api/rows/", {"customer": buyer["id"], "price_min": "17", "sort": "-price"}
)
assert response.status_code == 200, response.content
assert response.json()["rows"][0]["id"] == created_part.pk

# This is the same native multipart endpoint used by the sheet's uploader.
image_buffer = BytesIO()
Image.new("RGB", (8, 8), color=(100, 100, 100)).save(image_buffer, format="PNG")
image_upload = SimpleUploadedFile("smoke.png", image_buffer.getvalue(), content_type="image/png")
response = client.patch(
    f"/api/part/{created_part.pk}/",
    encode_multipart("SMOKE", {"image": image_upload}),
    content_type="multipart/form-data; boundary=SMOKE",
)
assert response.status_code == 200, response.content
created_part.refresh_from_db()
assert created_part.image
last_number = created_part.IPN
created_part.delete()
series.refresh_from_db()
assert snapshot(series)["next"] == last_number
replacement = edit_parts(
    user,
    {
        "key": str(uuid.uuid4()),
        "rows": [{"series": series.pk, "fields": {"name": "OEM-RECLAIMED"}}],
    },
)["rows"][0]
assert replacement["ipn"] == last_number
deleted = delete_part(
    user, {"key": str(uuid.uuid4()), "id": replacement["id"], "token": replacement["token"]}
)
assert deleted["deleted"] == replacement["id"]
part.refresh_from_db()
assert part.IPN == "1008930", "Existing part number shifted"
print(
    "Native InvenTree 1.3.5 creation, numbering, pricing synchronization, routes and migration smoke passed."
)
