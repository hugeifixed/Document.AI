from django.db import migrations


def backfill_runitem_audit_users(apps, schema_editor):
    RunItem = apps.get_model("docai", "RunItem")
    pending = []

    for item in (
        RunItem.objects.filter(created_by__isnull=True)
        .select_related("run")
        .iterator(chunk_size=1_000)
    ):
        if item.run.created_by_id is None:
            continue
        item.created_by_id = item.run.created_by_id
        if item.updated_by_id is None:
            item.updated_by_id = item.run.created_by_id
        pending.append(item)
        if len(pending) == 1_000:
            RunItem.objects.bulk_update(pending, ["created_by", "updated_by"])
            pending.clear()

    if pending:
        RunItem.objects.bulk_update(pending, ["created_by", "updated_by"])


class Migration(migrations.Migration):
    dependencies = [
        ("docai", "0003_alter_dataset_options_alter_project_options_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_runitem_audit_users, migrations.RunPython.noop),
    ]
