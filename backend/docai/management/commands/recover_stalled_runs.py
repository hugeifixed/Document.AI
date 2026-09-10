"""Recover database state left behind by an abruptly lost Celery worker."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from docai.models import ITEM_STATUS, RunItem
from docai.services.runs import finalize_run


class Command(BaseCommand):
    help = (
        "Mark stale running items as retryable failures and finalize runs that "
        "have no other active items."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-seconds",
            type=int,
            default=None,
            help=(
                "Minimum stale age; defaults to the greater of the hard task limit or maximum retry "
                "delay, plus five minutes."
            ),
        )

    def handle(self, *args, **options):
        del args
        age_seconds = options["older_than_seconds"]
        minimum_age = max(
            settings.CELERY_TASK_TIME_LIMIT,
            settings.CELERY_TASK_RETRY_BACKOFF_MAX_SECONDS,
        )
        if age_seconds is None:
            age_seconds = minimum_age + 300
        if age_seconds <= minimum_age:
            raise CommandError(
                "--older-than-seconds must exceed both the hard task limit and maximum retry backoff "
                "to avoid recovering live work."
            )

        now = timezone.now()
        stale = RunItem.objects.filter(
            Q(status=ITEM_STATUS.running) | Q(status=ITEM_STATUS.queued, stage="retry_wait"),
            status_changed__lt=now - timedelta(seconds=age_seconds),
        )
        run_ids = list(stale.values_list("run_id", flat=True).distinct())
        recovered = stale.update(
            status=ITEM_STATUS.failed,
            stage="worker_lost",
            error_code="WORKER_LOST",
            error_message="The worker stopped before this item or its retry completed. It is safe to retry.",
            retryable=True,
            status_changed=now,
        )

        for run_id in run_ids:
            finalize_run(run_id, only_if_complete=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Recovered {recovered} stalled item(s) across {len(run_ids)} run(s)."
            )
        )
