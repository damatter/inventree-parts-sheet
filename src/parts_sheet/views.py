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
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from part.models import Part, PartCategory

from . import __version__, pricing
from .import_service import import_rows
from .importer import classify, read_workbook
from .models import ChangeRecord, ImportPreview, NumberSeries
from .numbering import high_water, lock_series, snapshot
from .services import edit_parts, require_part, serialize_part
from .stock import can_add_stock


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


def filtered_parts(values):
    parts = Part.objects.select_related("category", "sheet_details").all()
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
    sort = values.get("sort", "IPN")
    if sort not in ("IPN", "-IPN", "name", "-name", "-pk"):
        sort = "IPN"
    return parts.order_by(sort, "pk")


def bootstrap(user):
    from company.models import Company
    from plugin.registry import registry
    from stock.models import StockLocation
    from users.permissions import check_user_permission

    from .website import configured

    caps = pricing.capabilities(user)
    return {
        "permissions": {
            a: bool(check_user_permission(user, Part, a)) for a in ("view", "add", "change")
        },
        "admin": bool(user.is_staff or user.is_superuser),
        "pricing": caps,
        "stock_add": can_add_stock(user),
        "locations": list(
            StockLocation.objects.filter(structural=False)
            .order_by("pathstring")
            .values("id", "name", "pathstring")
        )
        if can_add_stock(user)
        else [],
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
    rows = filtered_parts(request.GET)
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
                page = Paginator(filtered_parts(request.GET), page_size).get_page(
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
                    series.last_value = max(high_water(series), int(number[len(prefix) :]))
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
