import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_series(apps, schema_editor):
    series = apps.get_model("parts_sheet", "NumberSeries")
    for prefix in ("1007", "1008", "1009"):
        series.objects.using(schema_editor.connection.alias).get_or_create(
            prefix=prefix, defaults={"label": prefix + " series", "digits": 3}
        )


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("part", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="NumberSeries",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        primary_key=True, serialize=False, auto_created=True, verbose_name="ID"
                    ),
                ),
                ("prefix", models.CharField(max_length=40, unique=True)),
                ("label", models.CharField(max_length=100)),
                ("digits", models.PositiveSmallIntegerField(default=3)),
                ("last_value", models.PositiveBigIntegerField(default=0)),
            ],
            options={"ordering": ["prefix"]},
        ),
        migrations.CreateModel(
            name="SheetDetails",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        primary_key=True, serialize=False, auto_created=True, verbose_name="ID"
                    ),
                ),
                ("cells", models.JSONField(default=dict)),
                (
                    "part",
                    models.OneToOneField(
                        to="part.part",
                        related_name="sheet_details",
                        on_delete=django.db.models.deletion.CASCADE,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ChangeRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        primary_key=True, serialize=False, auto_created=True, verbose_name="ID"
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("action", models.CharField(max_length=30)),
                ("details", models.JSONField(default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Operation",
            fields=[
                ("key", models.UUIDField(primary_key=True, serialize=False)),
                ("digest", models.CharField(max_length=64)),
                ("result", models.JSONField(default=dict)),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ImportPreview",
            fields=[
                ("key", models.UUIDField(primary_key=True, serialize=False)),
                ("rows", models.JSONField(default=list)),
                ("counters", models.JSONField(default=dict)),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE
                    ),
                ),
            ],
        ),
        migrations.RunPython(seed_series, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ImportLink",
            fields=[
                ("fingerprint", models.CharField(max_length=64, primary_key=True, serialize=False)),
                (
                    "part",
                    models.ForeignKey(to="part.part", on_delete=django.db.models.deletion.PROTECT),
                ),
            ],
        ),
    ]
