from django.apps import AppConfig


class PartsSheetConfig(AppConfig):
    name = "parts_sheet"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import pre_delete

        from .numbering import reclaim_deleted_number

        pre_delete.connect(
            reclaim_deleted_number, dispatch_uid="parts-sheet-reclaim-latest-number", weak=False
        )
