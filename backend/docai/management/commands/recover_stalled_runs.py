"""Recover database state left behind by an abruptly lost Celery worker."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from docai.services.run_execution import recover_stalled_items


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
        try:
            result = recover_stalled_items(age_seconds)
        except ValueError as exc:
            raise CommandError(
                "--older-than-seconds must exceed both the hard task limit and maximum retry backoff "
                "to avoid recovering live work."
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Recovered {result.recovered_items} stalled item(s) across "
                f"{result.affected_runs} run(s)."
            )
        )
