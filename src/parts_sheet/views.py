"""Session-authenticated, CSRF-protected endpoints served outside the SPA route."""

import csv
import io
import json
import re
import uuid
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import BooleanField, Case, F, OuterRef, Q, Subquery, Value, When
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from part.models import Part, PartCategory

from . import __version__, pricing
from .customers import can_add_customer, create_customer
from .import_service import import_rows
from .importer import classify, read_workbook
from .models import ChangeRecord, ImportPreview, NumberSeries
from .numbering import catalogue_high_water, lock_series, snapshot
from .services import delete_part, edit_parts, require_part, serialize_part
from .stock import can_add_stock, can_view_locations, location_options


@login_required
@never_cache
@ensure_csrf_cookie
@require_GET
def index(request):
    require_part(request.user, "view")
    return render(request, "parts_sheet/index.html", {"version": __version__})


@require_GET
def asset(request, filename):
    if filename not in ("sheet.js", "sheet.css", "shortcut.js"):
        raise Http404
    content_type = "text/css" if filename.endswith("css") else "text/javascript"
    return HttpResponse(
        (Path(__file__).parent / "assets" / filename).read_text("utf-8"), content_type=content_type
    )


def filtered_parts(values, user=None):
    parts = Part.objects.select_related("category", "sheet_details", "default_location").all()
    query = str(values.get("q", "")).strip()[:200]
    if query:
        parts = parts.filter(
            Q(IPN__icontains=query)
            | Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(keywords__icontains=query)
        )
    if values.get("category"):
        category = PartCategory.objects.get(pk=int(values["category"]))
        parts = parts.filter(category__in=category.get_descendants(include_self=True))
    if values.get("active") in ("true", "false"):
        parts = parts.filter(active=values["active"] == "true")
    if values.get("prefix"):
        parts = parts.filter(IPN__startswith=str(values["prefix"])[:40])
    columns = {
        "IPN": "IPN",
        "name": "name",
        "description": "description",
        "category": "category__pathstring",
        "active": "active",
        "make_model": "sheet_details__cells__make_model",
        "material": "sheet_details__cells__material",
        "size": "sheet_details__cells__size",
        "default_location": "default_location__pathstring",
        "pk": "pk",
    }
    for key in ("IPN", "name", "description", "make_model", "material", "size", "default_location"):
        value = str(values.get(f"filter_{key}", "")).strip()[:200]
        if value:
            if key == "default_location" and not can_view_locations(user):
                raise PermissionDenied("Stock location view permission is required.")
            parts = parts.filter(**{columns[key] + "__icontains": value})
    parts = parts.annotate(
        has_photo=Case(
            When(Q(image="") | Q(image__isnull=True), then=Value(False)),
            default=Value(True),
            output_field=BooleanField(),
        )
    )
    columns["photo"] = "has_photo"
    if values.get("photo") in ("true", "false"):
        parts = parts.filter(has_photo=values["photo"] == "true")
    sort = values.get("sort", "IPN")
    if sort.lstrip("-") == "default_location" and not can_view_locations(user):
        raise PermissionDenied("Stock location view permission is required.")
    if sort.lstrip("-") == "price" or values.get("price_min") or values.get("price_max"):
        pricing.require(user)
        from inventree_customer_pricing.models import CustomerPriceBreak

        customer = int(values.get("customer") or 0)
        quantity = Decimal(values.get("quantity") or "1")
        if not customer or not quantity.is_finite() or quantity < 1:
            raise ValidationError("Choose a customer and quantity break to filter or sort prices.")
        tiers = CustomerPriceBreak.objects.filter(
            price_list__part_id=OuterRef("pk"), price_list__customer_id=customer, quantity=quantity
        ).order_by("pk")
        parts = parts.annotate(sheet_price=Subquery(tiers.values("price")[:1]))
        columns["price"] = "sheet_price"
        for key, lookup in (("price_min", "gte"), ("price_max", "lte")):
            if values.get(key):
                price = Decimal(values[key])
                if not price.is_finite() or price < 0:
                    raise ValidationError("Enter a valid non-negative price filter.")
                parts = parts.filter(**{f"sheet_price__{lookup}": price})
    field = columns.get(sort.lstrip("-"), "IPN")
    ordering = (
        F(field).desc(nulls_last=True) if sort.startswith("-") else F(field).asc(nulls_last=True)
    )
    return parts.order_by(ordering, "pk")


def bootstrap(user):
    from company.models import Company
    from plugin.registry import registry
    from users.permissions import check_user_permission

    from .website import configured

    caps = pricing.capabilities(user)
    return {
        "permissions": {
            a: bool(check_user_permission(user, Part, a))
            for a in ("view", "add", "change", "delete")
        },
        "admin": bool(user.is_staff or user.is_superuser),
        "pricing": caps,
        "stock_add": can_add_stock(user),
        "customer_add": can_add_customer(user),
        "location_view": can_view_locations(user),
        "locations": location_options() if can_view_locations(user) else [],
        "website_sync": configured(),
        "series": [snapshot(s) for s in NumberSeries.objects.all()],
        "categories": [
            {"id": c.pk, "name": c.pathstring or c.name}
            for c in PartCategory.objects.filter(structural=False).order_by("pathstring")
        ],
        "customers": list(
            Company.objects.filter(is_customer=True, active=True)
            .order_by("name")
            .values("id", "name", "currency")
        )
        if caps["view"]
        else [],
        "integrations": {
            slug: registry.get_plugin(slug, active=True) is not None
            for slug in ("part-visibility", "inventory-manager", "quote-generator")
        },
    }


def export_csv(request):
    rows = filtered_parts(request.GET, request.user)
    if rows.count() > 20000:
        raise ValidationError("Filter to 20,000 parts or fewer before exporting.")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "DiCor Part Number",
            "OEM PN",
            "Part Description",
            "Category",
            "Visible",
            "Make/Model",
            "Material Spec",
            "Size/Ratio/tth",
            "Notes",
        ]
    )

    def safe(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    for part in rows.iterator(chunk_size=500):
        row = serialize_part(part, request.user)
        writer.writerow(
            [
                safe(v)
                for v in [
                    row["ipn"],
                    row["name"],
                    row["description"],
                    row["category"],
                    str(row["active"]),
                    *[row["cells"].get(k, "") for k in ("make_model", "material", "size", "notes")],
                ]
            ]
        )
    response = HttpResponse("\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="parts-catalogue.csv"'
    return response


@login_required
@never_cache
def api(request, action):
    try:
        require_part(request.user, "view")
        if request.method == "GET":
            if action == "bootstrap":
                return JsonResponse(bootstrap(request.user))
            if action == "rows":
                page_size = int(request.GET.get("page_size", 50))
                if page_size not in (25, 50, 100, 200):
                    raise ValidationError("Choose 25, 50, 100 or 200 parts per page.")
                page = Paginator(filtered_parts(request.GET, request.user), page_size).get_page(
                    request.GET.get("page", 1)
                )
                caps = pricing.capabilities(request.user)
                customer = int(request.GET.get("customer") or 0)
                quantity = Decimal(request.GET.get("quantity", "1"))
                if not quantity.is_finite() or quantity < 1:
                    raise ValidationError("Price quantity must be at least 1.")
                rows = []
                for part in page:
                    row = serialize_part(part, request.user)
                    if customer and caps["view"]:
                        row["price"] = pricing.price_state(part, customer, quantity)
                    rows.append(row)
                return JsonResponse(
                    {
                        "rows": rows,
                        "total": page.paginator.count,
                        "pages": page.paginator.num_pages,
                        "page": page.number,
                        "page_size": page_size,
                    }
                )
            if action == "export":
                return export_csv(request)
        elif request.method == "POST":
            if action == "sync":
                from .website import request_sync

                return request_sync(request.user)
            if action == "preview":
                require_part(request.user, "add")
                require_part(request.user, "change")
                upload = request.FILES.get("file")
                if not upload:
                    raise ValidationError("Choose a workbook.")
                try:
                    rows, warnings, counters = read_workbook(
                        upload.read(10 * 1024 * 1024 + 1), upload.name
                    )
                except ValidationError:
                    raise
                except Exception as exc:
                    raise ValidationError(
                        "This workbook could not be read. Use an unencrypted XLS, XLSX or UTF-8 CSV file."
                    ) from exc
                preview = ImportPreview.objects.create(
                    key=uuid.uuid4(), user=request.user, rows=rows, counters=counters
                )
                classified = classify(rows)
                return JsonResponse(
                    {
                        "preview": str(preview.pk),
                        "rows": [{k: v for k, v in r.items() if k != "cells"} for r in classified],
                        "warnings": warnings,
                        "counters": counters,
                    }
                )
            payload = json.loads(request.body)
            if not isinstance(payload, dict):
                raise ValidationError("Expected a JSON object.")
            if action == "save":
                return JsonResponse(edit_parts(request.user, payload))
            if action == "delete":
                return JsonResponse(delete_part(request.user, payload))
            if action == "customer":
                return JsonResponse(create_customer(request.user, payload))
            if action == "import":
                return JsonResponse(import_rows(request.user, payload))
            if action == "series":
                if not (request.user.is_staff or request.user.is_superuser):
                    raise PermissionDenied("Only an administrator can configure numbering.")
                require_part(request.user, "change")
                prefix = str(payload.get("prefix", "")).strip()
                digits = int(payload.get("digits", 3))
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", prefix) or not 1 <= digits <= 9:
                    raise ValidationError("Use a short prefix and 1–9 numeric digits.")
                with transaction.atomic():
                    series_list = lock_series()
                    series = next((s for s in series_list if s.prefix == prefix), None)
                    if series and series.digits != digits:
                        raise ValidationError("An existing series cannot change its width.")
                    if not series:
                        series = NumberSeries(prefix=prefix, digits=digits)
                    series.label = str(payload.get("label") or prefix)[:100]
                    number = str(payload.get("last") or prefix + "0" * digits)
                    if not re.fullmatch(re.escape(prefix) + rf"[0-9]{{{digits}}}", number):
                        raise ValidationError("Last number must include the prefix and all digits.")
                    series.reserved_through = int(number[len(prefix) :])
                    series.last_value = catalogue_high_water(series)
                    series.full_clean()
                    series.save()
                    ChangeRecord.objects.create(
                        user=request.user, action="numbering", details=snapshot(series)
                    )
                return JsonResponse(snapshot(series))
        return JsonResponse({"error": "Method or action not supported."}, status=405)
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ObjectDoesNotExist:
        return JsonResponse(
            {"error": "The selected record no longer exists. Reload the sheet."}, status=404
        )
    except (ValidationError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return JsonResponse(
            {"error": "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)},
            status=400,
        )
    except DatabaseError:
        return JsonResponse(
            {"error": "The database is busy or the data changed. Retry this same save."}, status=409
        )
    except Exception as exc:
        from rest_framework.exceptions import APIException

        if isinstance(exc, APIException):
            return JsonResponse({"error": str(exc.detail)}, status=exc.status_code)
        raise
