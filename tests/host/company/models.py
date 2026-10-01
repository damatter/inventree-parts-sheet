from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=3, default="CAD")
    active = models.BooleanField(default=True)
    is_customer = models.BooleanField(default=True)
    is_supplier = models.BooleanField(default=False)
