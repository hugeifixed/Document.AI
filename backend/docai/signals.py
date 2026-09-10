"""Cache invalidation: whenever source data changes, the dependent cache keys go."""
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from docai.models import (
    CategoryDefinition,
    Dataset,
    Evaluation,
    ExtractionTemplate,
    Project,
    Run,
    WorkflowConfiguration,
)


def _bust(*keys):
    cache.delete_many([k for k in keys if k])


@receiver([post_save, post_delete], sender=Project)
@receiver([post_save, post_delete], sender=Dataset)
@receiver([post_save, post_delete], sender=Run)
@receiver([post_save, post_delete], sender=Evaluation)
def _dashboard_changed(sender, **kwargs):
    _bust("docai:dashboard")


@receiver([post_save, post_delete], sender=CategoryDefinition)
@receiver([post_save, post_delete], sender=ExtractionTemplate)
@receiver([post_save, post_delete], sender=WorkflowConfiguration)
def _reference_changed(sender, instance=None, **kwargs):
    pid = getattr(instance, "project_id", None)
    _bust("docai:reference", f"docai:reference:{pid}" if pid else None)


@receiver(post_save, sender=Run)
def _run_metrics_changed(sender, instance=None, **kwargs):
    _bust(f"docai:run_metrics:{instance.id}")
