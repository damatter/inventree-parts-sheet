"""Run inside the official InvenTree container, after installing both plugins."""

import json
import uuid
from decimal import Decimal

from company.models import Company
from django.contrib.auth import get_user_model
from django.test import Client
from inventree_customer_pricing.models import CustomerPriceList, PartPricingPolicy
from part.models import Part, PartSellPriceBreak
from plugin.registry import registry

from parts_sheet.models import NumberSeries
from parts_sheet.pricing import price_state
from parts_sheet.services import edit_parts

assert registry.get_plugin("parts-sheet", active=True), "Parts Sheet failed plugin discovery"
assert registry.get_plugin("customer-pricing", active=True), "Customer Pricing did not activate"
user = get_user_model().objects.create_superuser("parts-sheet-smoke", password=uuid.uuid4().hex)
customer = Company.objects.create(name="Smoke customer", is_customer=True, currency="CAD")
series = NumberSeries.objects.get(prefix="1008")
Part.objects.create(name="Existing catalogue part", IPN="1008927")
payload = {
    "key": str(uuid.uuid4()),
    "rows": [{"series": series.pk, "fields": {"name": "New manufactured part", "assembly": True}}],
}
created = edit_parts(user, payload)["rows"][0]
assert created["ipn"] == "1008928"
assert edit_parts(user, payload)["rows"][0]["id"] == created["id"]
part = Part.objects.get(pk=created["id"])
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
client = Client(HTTP_HOST="localhost")
client.force_login(user)
assert client.get("/plugin/parts-sheet/").status_code == 200
response = client.get("/plugin/parts-sheet/api/bootstrap/")
assert response.status_code == 200, response.content
assert response.json()["pricing"]["edit"]
assert any(row["id"] == customer.pk for row in response.json()["customers"])
response = client.get("/plugin/parts-sheet/api/rows/")
assert response.status_code == 200, response.content
assert any(row["id"] == part.pk for row in json.loads(response.content)["rows"])
print(
    "Native InvenTree 1.3.5 creation, numbering, pricing synchronization, routes and migration smoke passed."
)
