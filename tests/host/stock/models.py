"""Small host contract; the container job tests real stock and barcode models."""

import hashlib

from django.core.exceptions import ValidationError
from django.db import models


class StockLocation(models.Model):
    name = models.CharField(max_length=100)
    pathstring = models.CharField(max_length=255, default="")
    structural = models.BooleanField(default=False)


class StockItem(models.Model):
    part = models.ForeignKey("part.Part", on_delete=models.CASCADE)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=5)
    barcode_data = models.CharField(max_length=250, blank=True, default="")
    barcode_hash = models.CharField(max_length=250, blank=True, default="")

    def assign_barcode(self, barcode_data, save=True):
        hashed = hashlib.sha256(barcode_data.encode()).hexdigest()
        if type(self).objects.filter(barcode_hash=hashed).exists():
            raise ValidationError("Existing barcode found")
        self.barcode_data = barcode_data
        self.barcode_hash = hashed
        if save:
            self.save()

    def save(self, *args, **kwargs):
        kwargs.pop("user", None)
        return super().save(*args, **kwargs)
