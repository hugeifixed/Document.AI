"""Remove completed headless idempotency records after their replay window."""

from django.core.management.base import BaseCommand

from docai.services.invocations import expired_cleanup_queryset, purge_expired_invocations


class Command(BaseCommand):
    help = (
        "Delete expired workflow-invocation reservations only when their run is terminal "
        "or acceptance failed before a run was created."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many records are eligible without deleting them.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            count = expired_cleanup_queryset().count()
            self.stdout.write(f"{count} expired invocation record(s) eligible for cleanup.")
            return
        deleted = purge_expired_invocations()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired invocation record(s)."))
