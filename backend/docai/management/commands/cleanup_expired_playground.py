"""Delete expired playground sessions and their private temporary uploads."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from docai.models import PlaygroundSession
from docai.services.playground import cleanup_expired


class Command(BaseCommand):
    help = (
        "Remove expired playground proposals and temporary sample files (schedule at least daily)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Report the expired session count."
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            self.stdout.write(
                str(PlaygroundSession.objects.filter(expires_at__lte=timezone.now()).count())
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {cleanup_expired()} expired playground session(s).")
            )
