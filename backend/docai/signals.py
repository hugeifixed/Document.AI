"""Cache invalidation: whenever source data changes, the dependent cache keys go."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from docai.models import (
    Dataset,
    Evaluation,
    Project,
    Run,
    WorkflowConfiguration,
)
from docai.services.dashboard import invalidate_dashboard


@receiver([post_save, post_delete], sender=Project)
@receiver([post_save, post_delete], sender=Dataset)
@receiver([post_save, post_delete], sender=Run)
@receiver([post_save, post_delete], sender=Evaluation)
@receiver([post_save, post_delete], sender=WorkflowConfiguration)
def _dashboard_changed(sender, instance=None, **kwargs):
    project_id = instance.pk if isinstance(instance, Project) else instance.project_id
    invalidate_dashboard(project_id)
