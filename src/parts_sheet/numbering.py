"""Allocate only within the chosen series; retain high-water marks forever."""

import re

from django.core.exceptions import ValidationError
from django.db.models import F
from part.models import Part

from .models import NumberSeries


def lock_series():
    # An actual UPDATE acquires a write lock even on SQLite. Every plugin write uses
    # this lock first, in the same order, before reading or allocating identifiers.
    NumberSeries.objects.filter(pk__in=NumberSeries.objects.values("pk")).update(
        last_value=F("last_value")
    )
    return list(NumberSeries.objects.select_for_update().order_by("pk"))


def high_water(series):
    pattern = re.compile(re.escape(series.prefix) + rf"([0-9]{{{series.digits}}})\Z")
    highest = series.last_value
    for ipn in Part.objects.filter(IPN__startswith=series.prefix).values_list("IPN", flat=True):
        match = pattern.fullmatch(ipn or "")
        if match:
            highest = max(highest, int(match[1]))
    return highest


def allocate(series):
    value = high_water(series) + 1
    if value >= 10**series.digits:
        raise ValidationError(f"{series.label} is full. Add another series in Numbering.")
    ipn = series.prefix + str(value).zfill(series.digits)
    if Part.objects.filter(IPN__iexact=ipn).exists():
        raise ValidationError(f"Part number {ipn} already exists.")
    series.last_value = value
    series.save(update_fields=["last_value"])
    return ipn


def observe(ipn, series_list):
    for series in series_list:
        match = re.fullmatch(re.escape(series.prefix) + rf"([0-9]{{{series.digits}}})", ipn)
        if match and int(match[1]) > series.last_value:
            series.last_value = int(match[1])
            series.save(update_fields=["last_value"])


def snapshot(series):
    highest = high_water(series)
    exhausted = highest + 1 >= 10**series.digits
    return {
        "id": series.pk,
        "label": series.label,
        "prefix": series.prefix,
        "digits": series.digits,
        "last": series.prefix + str(highest).zfill(series.digits),
        "next": None if exhausted else series.prefix + str(highest + 1).zfill(series.digits),
    }
