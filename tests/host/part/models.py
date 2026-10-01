"""Minimal host contract. Customer Pricing itself is loaded from its real source."""

from django.core.exceptions import ValidationError
from django.db import models
from djmoney.models.fields import MoneyField


class PartCategory(models.Model):
    name = models.CharField(max_length=100)
    pathstring = models.CharField(max_length=255, default="")
    structural = models.BooleanField(default=False)

    def get_descendants(self, include_self=False):
        return type(self).objects.filter(pk=self.pk)

    def __str__(self):
        return self.name


class Part(models.Model):
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=250, blank=True, default="")
    IPN = models.CharField(max_length=100, blank=True, null=True)
    revision = models.CharField(max_length=100, blank=True, default="")
    keywords = models.CharField(max_length=250, blank=True, default="")
    category = models.ForeignKey(PartCategory, null=True, blank=True, on_delete=models.DO_NOTHING)
    active = models.BooleanField(default=True)
    assembly = models.BooleanField(default=False)
    component = models.BooleanField(default=True)
    purchaseable = models.BooleanField(default=True)
    salable = models.BooleanField(default=True)
    image = models.CharField(max_length=250, blank=True, default="")
    default_location = models.ForeignKey(
        "stock.StockLocation", null=True, blank=True, on_delete=models.SET_NULL
    )
    locked = models.BooleanField(default=False)

    def delete(self, **kwargs):
        if self.locked:
            raise ValidationError("Cannot delete this part as it is locked")
        if self.active:
            raise ValidationError("Cannot delete this part as it is still active")
        return super().delete(**kwargs)

    def get_thumbnail_url(self):
        return self.image

    def get_image_url(self):
        return self.image

    def clean(self):
        if self.category_id and self.category.structural:
            raise ValidationError("Parts cannot be in structural categories.")

    def schedule_pricing_update(self, create=False):
        pass


class PartSellPriceBreak(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=15, decimal_places=5)
    price = MoneyField(max_digits=19, decimal_places=6, default_currency="CAD")
