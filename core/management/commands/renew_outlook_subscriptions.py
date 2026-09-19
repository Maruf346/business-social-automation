from django.core.management.base import BaseCommand

from core.outlook.subscription_sync import SubscriptionSyncService


class Command(BaseCommand):
    help = "Renew Microsoft Graph Outlook webhook subscriptions that are expiring soon."

    def add_arguments(self, parser):
        parser.add_argument("--lookahead-hours", type=int, default=24)
        parser.add_argument("--extension-hours", type=int, default=48)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = SubscriptionSyncService.renew_due(
            lookahead_hours=options["lookahead_hours"],
            extension_hours=options["extension_hours"],
            limit=options["limit"],
        )
        self.stdout.write(self.style.SUCCESS(f"Outlook subscription renewal scan completed: {result}"))
