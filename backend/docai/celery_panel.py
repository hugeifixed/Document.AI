"""Optional Celery panel integration; imported only when its extra is installed."""

from dataclasses import replace

from dj_celery_panel.celery_utils import CeleryWorkersInspectBackend


class WorkersBackend(CeleryWorkersInspectBackend):
    """An inspection timeout cannot establish that a worker has stopped."""

    def get_workers(self):
        result = super().get_workers()
        if result.error == "No workers are currently running":
            return replace(
                result,
                error="No worker replied to inspection. A busy solo worker may still be processing.",
            )
        return result
