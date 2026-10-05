import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("design", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="MaasRevisionEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("project_key", models.CharField(blank=True, default="", max_length=128)),
                ("variant_id", models.CharField(blank=True, default="", max_length=128)),
                ("instruction", models.TextField(blank=True, default="")),
                ("inference_source", models.CharField(blank=True, default="", max_length=64)),
                ("accepted_by_gates", models.BooleanField(default=False)),
                ("graph_diff", models.JSONField(default=list)),
                ("validation", models.JSONField(default=dict)),
                ("reference_evidence", models.JSONField(default=dict)),
                ("revision_evaluation", models.JSONField(default=dict)),
                ("user_decision", models.CharField(choices=[("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("undo", "Undo")], default="pending", max_length=16)),
                ("user_rating", models.FloatField(blank=True, null=True)),
                ("feedback_note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("feedback_at", models.DateTimeField(blank=True, null=True)),
                ("job", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="maas_revisions", to="design.optimizationjob")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="maasrevisionevent", index=models.Index(fields=["project_key", "-created_at"], name="design_maas_project_8aa0fe_idx")),
        migrations.AddIndex(model_name="maasrevisionevent", index=models.Index(fields=["user_decision", "-created_at"], name="design_maas_user_de_ad4ffb_idx")),
    ]
