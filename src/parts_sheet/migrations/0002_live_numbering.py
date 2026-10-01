import re

from django.db import migrations, models


def reconcile_existing_counters(apps, schema_editor):
    series_model = apps.get_model("parts_sheet", "NumberSeries")
    part_model = apps.get_model("part", "Part")
    alias = schema_editor.connection.alias
    for series in series_model.objects.using(alias).all():
        pattern = re.compile(re.escape(series.prefix) + rf"([0-9]{{{series.digits}}})\Z")
        numbers = (
            part_model.objects.using(alias)
            .filter(IPN__startswith=series.prefix)
            .values_list("IPN", flat=True)
        )
        series.last_value = max(
            [0]
            + [int(match[1]) for number in numbers if (match := pattern.fullmatch(number or ""))]
        )
        series.save(using=alias, update_fields=["last_value"])


class Migration(migrations.Migration):
    dependencies = [("parts_sheet", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="numberseries",
            name="reserved_through",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="importlink",
            name="part",
            field=models.ForeignKey(null=True, on_delete=models.SET_NULL, to="part.part"),
        ),
        migrations.RunPython(reconcile_existing_counters, migrations.RunPython.noop),
    ]
