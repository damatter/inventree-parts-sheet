import os
import sys
from pathlib import Path

import django
import pytest

source = os.environ.get(
    "CUSTOMER_PRICING_SOURCE", str(Path(__file__).resolve().parents[2] / "customer-pricing")
)
sys.path.insert(0, source)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()


@pytest.fixture(scope="session", autouse=True)
def database():
    from django.test.utils import setup_databases, teardown_databases

    old = setup_databases(verbosity=0, interactive=False)
    yield
    teardown_databases(old, verbosity=0)


@pytest.fixture(autouse=True)
def clean_db(database):
    from django.core.management import call_command
    from plugin.registry import registry

    from parts_sheet.models import NumberSeries

    call_command("flush", verbosity=0, interactive=False)
    for prefix in ("1007", "1008", "1009"):
        NumberSeries.objects.create(prefix=prefix, label=prefix + " series")
    registry.active = True


@pytest.fixture
def user():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser("tester", password="test-only")


@pytest.fixture
def client(user):
    from django.test import Client

    client = Client()
    client.force_login(user)
    return client
