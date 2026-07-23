# @staticmethod
    # def process_outlook_webhook(payload: dict, webhook_log: WebhookLog) -> None:
    #     """
    #     Process incoming Outlook (Graph API) webhook events:
    #     1. Parse Outlook-specific event
    #     2. Resolve OutlookAccount
    #     3. Route to handle_outlook_message or handle_outlook_status
    #     """
    #     try:
    #         # ── 1. Parse Outlook-specific event ────────────────────────
    #         event = OutlookWebhookParser.parse(payload)
    #     except WebhookParsingError:
    #         logger.exception("Failed to parse Outlook webhook payload")
    #         return

    #     # ── 2. Resolve OutlookAccount ─────────────────────────────────
    #     try:
    #         account = OutlookOrchestrator._resolve_outlook_account(
    #             event.recipient_email
    #         )
    #     except OutlookAccountNotFoundError:
    #         logger.warning(
    #             "No OutlookAccount for email=%s — skipping", event.recipient_email
    #         )
    #         return

    #     # ── 3. Route to Outlook-specific handlers ──────────────────────
    #     if event.event_type == OutlookWebhookEventType.MESSAGE and event.message:
    #         OutlookOrchestrator._handle_outlook_message(
    #             event, account, webhook_log
    #         )
    #     elif event.event_type == OutlookWebhookEventType.STATUS and event.status:
    #         OutlookOrchestrator._handle_outlook_status(event, account, webhook_log)
    #     else:
    #         logger.info(
    #             "Ignoring Outlook webhook event_type=%s", event.event_type
    #         )