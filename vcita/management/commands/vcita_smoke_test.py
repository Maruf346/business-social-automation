from django.core.management.base import BaseCommand, CommandError

from vcita.api import VcitaAPIClient, VcitaAPIError
from vcita.models import VcitaAccount


class Command(BaseCommand):
    help = "Call a simple vCita API endpoint with the active account token."

    def add_arguments(self, parser):
        parser.add_argument("--account-id", type=int, help="Specific VcitaAccount id to use.")

    def handle(self, *args, **options):
        account_id = options.get("account_id")
        if account_id:
            account = VcitaAccount.objects.filter(pk=account_id).first()
        else:
            account = VcitaAccount.objects.filter(is_active=True).first()

        if not account:
            raise CommandError("No vCita account found. Add an active VcitaAccount in Django admin first.")

        try:
            response = VcitaAPIClient(account).list_webhooks()
        except VcitaAPIError as exc:
            raise CommandError(f"vCita API check failed ({exc.status_code or 'no status'}): {exc}") from exc

        self.stdout.write(self.style.SUCCESS("vCita API check succeeded."))
        self.stdout.write(str(response)[:1000])
