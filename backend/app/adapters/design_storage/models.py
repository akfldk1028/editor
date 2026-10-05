import uuid

from django.db import models


class OptimizationJob(models.Model):
    """GA optimization job."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('complete', 'Complete'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pnu = models.CharField(max_length=19, blank=True, default='')
    address = models.CharField(max_length=500, blank=True, default='')
    site_polygon = models.JSONField(help_text='GeoJSON polygon of site boundary')
    site_area_m2 = models.FloatField(null=True, blank=True)
    job_spec = models.JSONField(help_text='GA inputs/outputs/options spec')
    constraints = models.JSONField(default=list, help_text='Auto-injected from land/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    execution_token = models.UUIDField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    generation_count = models.IntegerField(default=0)
    max_generations = models.IntegerField(default=50)
    population_size = models.IntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Job {self.id!s:.8} [{self.status}] gen={self.generation_count}/{self.max_generations}"


class DesignResult(models.Model):
    """Individual design result within an optimization job."""

    job = models.ForeignKey(OptimizationJob, on_delete=models.CASCADE, related_name='results')
    generation = models.IntegerField()
    design_id = models.IntegerField(help_text='Sequential ID within job')
    inputs = models.JSONField(help_text='Design input parameters')
    outputs = models.JSONField(default=dict, help_text='Evaluated metrics')
    ranking = models.FloatField(null=True, blank=True, help_text='Pareto front number')
    crowding_distance = models.FloatField(null=True, blank=True)
    is_feasible = models.BooleanField(default=True)
    is_pareto_optimal = models.BooleanField(default=False)
    mass_geojson = models.JSONField(null=True, blank=True, help_text='3D mass GeoJSON for Cesium')

    class Meta:
        ordering = ['job', 'generation', 'design_id']
        indexes = [
            models.Index(fields=['job', 'generation']),
            models.Index(fields=['job', 'is_pareto_optimal']),
        ]

    def __str__(self):
        return f"Design {self.design_id} gen={self.generation} rank={self.ranking}"


class MaasRevisionEvent(models.Model):
    """Persistent evidence for conversational/reference-conditioned mass revisions."""

    DECISION_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("undo", "Undo"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(OptimizationJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="maas_revisions")
    project_key = models.CharField(max_length=128, blank=True, default="")
    variant_id = models.CharField(max_length=128, blank=True, default="")
    instruction = models.TextField(blank=True, default="")
    inference_source = models.CharField(max_length=64, blank=True, default="")
    accepted_by_gates = models.BooleanField(default=False)
    graph_diff = models.JSONField(default=list)
    validation = models.JSONField(default=dict)
    reference_evidence = models.JSONField(default=dict)
    revision_evaluation = models.JSONField(default=dict)
    user_decision = models.CharField(max_length=16, choices=DECISION_CHOICES, default="pending")
    user_rating = models.FloatField(null=True, blank=True)
    feedback_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    feedback_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project_key", "-created_at"]),
            models.Index(fields=["user_decision", "-created_at"]),
        ]


class OptimizationJobEvent(models.Model):
    job = models.ForeignKey(OptimizationJob, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["job", "id"], name="design_event_job_id_idx")]
