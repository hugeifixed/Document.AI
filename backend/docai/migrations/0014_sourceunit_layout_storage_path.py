from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("docai", "0013_processingcheckpoint")]

    operations = [
        migrations.AddField(
            model_name="sourceunit",
            name="layout_storage_path",
            field=models.CharField(
                max_length=255,
                blank=True,
                default="",
                help_text="Private immutable page/sheet layout artifact; avoids loading the complete layout for viewing.",
            ),
        ),
    ]
