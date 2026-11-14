from django.core.management.base import BaseCommand, CommandError

from operations.worker import Worker


class Command(BaseCommand):
    help = "Run the job worker (one per installation)."

    def handle(self, *args, **options):
        if Worker().run() != 0:
            raise CommandError("Another worker runs on this host")
