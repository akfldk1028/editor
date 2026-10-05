from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('design', '0002_maas_revision_event')]
    operations = [
        migrations.AddField(model_name='optimizationjob', name='execution_token', field=models.UUIDField(null=True, blank=True)),
        migrations.AddField(model_name='optimizationjob', name='heartbeat_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.CreateModel(
            name='OptimizationJobEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(max_length=32)),
                ('payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='design.optimizationjob')),
            ],
            options={'ordering': ['id'], 'indexes': [models.Index(fields=['job', 'id'], name='design_event_job_id_idx')]},
        ),
    ]
