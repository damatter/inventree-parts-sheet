"""Apply a reviewed import without overwriting existing native parts or prices."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from part.models import Part

from . import pricing
from .importer import classify, exact_price
from .models import ChangeRecord, ImportLink, ImportPreview, SheetDetails
from .numbering import allocate, observe
from .services import digest, idempotent, require_part


def import_rows(user, payload):
    require_part(user, "view")
    require_part(user, "add")
    require_part(user, "change")
    preview = ImportPreview.objects.get(pk=payload.get("preview"), user=user)
    if preview.created < timezone.now() - timedelta(days=1):
        raise ValidationError("This preview expired. Upload the workbook again.")
    customer_id = payload.get("customer")
    if customer_id:
        pricing.require(user, edit=True)

    def apply(series):
        rows = classify(preview.rows)
        if any(r["status"] == "conflict" for r in rows):
            raise ValidationError(
                "Duplicate part numbers need resolving before this import can run."
            )
        category_id = payload.get("category") or None
        active = payload.get("active", False)
        if type(active) is not bool:
            raise ValidationError("Active must be true or false.")
        selected = next((s for s in series if s.pk == int(payload.get("series") or 0)), None)
        for s in series:
            s.reserved_through = max(s.reserved_through, int(preview.counters.get(s.prefix, 0)))
            s.save(update_fields=["reserved_through"])
        for row in rows:
            observe(row["ipn"], series)
        counts = {"created": 0, "matched": 0, "skipped": 0, "prices_added": 0, "prices_kept": 0}
        for row in rows:
            fingerprint = digest(row["source"] + "\n" + row["name"])
            link = ImportLink.objects.filter(pk=fingerprint).first() if not row["ipn"] else None
            if link and link.part_id is None:
                counts["skipped"] += 1
                continue
            if row["status"] == "unnumbered" and not link and not payload.get("include_unnumbered"):
                counts["skipped"] += 1
                continue
            if row["part_id"] or link:
                part = Part.objects.select_for_update().get(pk=row["part_id"] or link.part_id)
                counts["matched"] += 1
            else:
                oem = str(row["cells"].get("oem_number", "")).strip()
                if not oem:
                    raise ValidationError(
                        f"{row['source']} ({row['ipn'] or row['name']}): add an OEM PN before importing this new part."
                    )
                if not row["ipn"] and selected is None:
                    raise ValidationError("Choose a series for rows without a part number.")
                ipn = row["ipn"] or allocate(selected)
                part = Part(
                    name=oem,
                    description=row["name"],
                    IPN=ipn,
                    category_id=category_id,
                    active=active,
                    salable=True,
                    component=True,
                )
                part.full_clean()
                part.save()
                counts["created"] += 1
                if not row["ipn"]:
                    ImportLink.objects.create(fingerprint=fingerprint, part=part)
            details, _ = SheetDetails.objects.get_or_create(part=part)
            # Keep values already entered in this screen. Store the source description
            # separately so matching a native part never silently renames it.
            cells = {**row["cells"], "source": row["source"], "source_name": row["name"]}
            for key, value in cells.items():
                if not details.cells.get(key):
                    details.cells[key] = value
            details.save()
            price = exact_price(row["cells"].get("sell_cad", ""))
            if customer_id and price is not None:
                current = pricing.price_state(part, customer_id, 1)
                if (
                    current["break_id"]
                    or not current["active"]
                    or current["currency"] not in ("", "CAD")
                ):
                    counts["prices_kept"] += 1
                else:
                    pricing.save_price(
                        user,
                        part,
                        {
                            "customer": customer_id,
                            "quantity": 1,
                            "price": str(price),
                            "currency": "CAD",
                            "token": current["token"],
                        },
                    )
                    counts["prices_added"] += 1
        ChangeRecord.objects.create(
            user=user, action="import", details={"preview": str(preview.pk), **counts}
        )
        return counts

    return idempotent(user, payload.get("key"), payload, apply)
