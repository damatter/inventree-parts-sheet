"""Only numbering, supplemental cells, and audit data live in this plugin."""

from django.conf import settings
from django.db import models


class NumberSeries(models.Model):
    prefix = models.CharField(max_length=40, unique=True)
    label = models.CharField(max_length=100)
    digits = models.PositiveSmallIntegerField(default=3)
    last_value = models.PositiveBigIntegerField(default=0)
    reserved_through = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["prefix"]


class SheetDetails(models.Model):
    part = models.OneToOneField("part.Part", on_delete=models.CASCADE, related_name="sheet_details")
    cells = models.JSONField(default=dict)


class ChangeRecord(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=30)
    details = models.JSONField(default=dict)


class Operation(models.Model):
    """A persistent receipt makes retrying a lost response safe."""

    key = models.UUIDField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)


class ImportPreview(models.Model):
    key = models.UUIDField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rows = models.JSONField(default=list)
    counters = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)


class ImportLink(models.Model):
    fingerprint = models.CharField(max_length=64, primary_key=True)
    part = models.ForeignKey("part.Part", null=True, on_delete=models.SET_NULL)
