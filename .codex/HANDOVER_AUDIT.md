# Handover Audit

Last reviewed: 2026-08-26

## Summary

The current codebase contains a useful Django foundation for channel intake, message persistence, external AI calls, and basic risk-based branching. It does not yet prove full Milestone 1 delivery from this checkout, because the local database is empty, tests are absent, Outlook processing is disabled in the webhook view, and several promised reports/features are not present in the repository.

Status labels:

- Done: clear implementation exists and local checks support it.
- Partial: scaffolding or partial implementation exists, but not complete/proven.
- Missing: no meaningful code/docs found.
- Unknown: may exist outside this repo or require credentials/external systems to verify.

## Milestone 1 Promise vs Current Evidence

| Promise | Status | Evidence / Notes |
| --- | --- | --- |
| Backend foundation with source code | Partial | Django/DRF project exists with apps, models, routes, admin, settings, Docker files. Tests are empty and production config is incomplete. |
| WhatsApp Business API connection and testing | Partial / Unknown | Webhook verification, HMAC validation, parser, account model, media download, and outbound send service exist. No local account data or webhook logs prove live testing. |
| Outlook/Microsoft Graph connection and testing | Partial | Models, token service, Graph message fetch/reply, attachment handling, Celery pipeline, and webhook-to-orchestrator dispatch exist. Live testing still requires valid Graph credentials and webhook subscription data. |
| vCita feasibility review and written documentation | Partial | vCita Phase 1 scaffold now exists: account token storage, raw webhook capture, API client, admin/API smoke-test helper. Full feasibility still requires live token and webhook payload verification. |
| AI extraction on sample or real client requests | Partial / External | Backend calls external AI endpoint. AI implementation belongs to separate AI repo. No tests or sample fixtures prove extraction behavior here. |
| AI-generated structured summaries | Partial / External | Backend calls a configurable summary endpoint for Telegram review. Summary generation itself belongs to the separate AI service. |
| One complete end-to-end demonstration | Partial / Not proven | WhatsApp path can theoretically do intake -> AI -> client or Telegram. Outlook path is disabled at webhook entry. Local DB has no proof records. |
| AI detects tattoo details | External / Unknown | Depends on separate AI service. Backend can send message/history/image URLs. |
| AI detects Nina, Hoss, or unclear | External / Unknown | No backend model or persisted field for artist suggestion yet. |
| AI detects missing information | External / Unknown | No backend model or persisted field yet. |
| Simple structured request card appears in Telegram | Partial | Backend sends plain Telegram messages. No card structure, inline buttons, callback handling, or persistence. |
| End-of-milestone technical report | Missing | README is generic. No dedicated technical report found. |
| 90-day bug-fix support | Not code-verifiable | Contract/business matter, not represented in repo. |

## Current Local Verification

Commands run on 2026-08-22:

- `.\.venv\Scripts\python.exe manage.py check` - passes.
- `.\.venv\Scripts\python.exe manage.py test` - finds 0 tests.
- `/api/docs/` - returns 200.
- `/api/schema/` - returns 200.
- Local DB counts: 0 WhatsApp accounts, 0 Outlook accounts, 0 webhook logs, 0 leads, 0 conversations, 0 messages, 0 media files.

## Important Findings

### WhatsApp

Implemented:

- Meta verification handshake.
- Optional HMAC signature check.
- Raw webhook logging.
- Parser for message and status events.
- Lead/message persistence.
- Media download for supported media.
- AI call.
- Low-risk outbound reply through Meta API.
- High-risk waiting reply plus Telegram summary.

Needs work:

- Telegram review chat ID is now env-configured via `TELEGRAM_REVIEW_CHAT_ID`; later Milestone 2 can move this into database-backed team/channel config.
- Persist AI analysis details.
- Persist human review status.
- Add tests and sample webhook fixtures.
- Confirm real Meta credentials and webhook subscription outside local DB.

### Outlook

Implemented:

- Outlook account and token models.
- Graph token generation.
- Message fetch.
- Attachment fetch/save.
- Reply sending.
- Celery chain for fetch -> AI -> send/review.

Phase 0 fix:

- `OutlookWebhook.post()` now logs the webhook and calls `WebhookOrchestrator.process_outlook_webhook(...)`.

Needs work:

- Enable webhook processing.
- Verify Graph subscription signal registration.
- Add clientState validation.
- Add duplicate/loop protection tests.
- Confirm Graph permissions and webhook lifecycle.

### Telegram

Implemented:

- Basic sendMessage helper.
- Basic webhook endpoint that echoes `{"ok": true}`.

Missing:

- Inline buttons.
- Callback query processing.
- User identity mapping for Nina/Hoss.
- Approval/edit/reject workflows.
- Rich correction flow.
- Decision persistence.

### AI Boundary

The backend should not implement the AI algorithms. AI extraction, risk classification, summary generation, artist suggestion, missing-info detection, image style tagging, and pricing recommendations should come from the AI engineer's separately deployed service.

Backend responsibilities:

- Send clean request payloads.
- Validate and normalize AI responses.
- Persist AI outputs.
- Route low/high risk outcomes.
- Collect human feedback.
- Send approved/final actions to client channels.

## Milestone 1 Closure Recommendation

Before claiming Milestone 1 is truly complete, create a reproducible demo checklist:

1. Configure one WhatsApp account and one Outlook account in a non-production test environment.
2. Send a WhatsApp text message and image.
3. Confirm lead/message/media records.
4. Confirm AI endpoint receives text/history/image URLs.
5. Confirm low-risk auto-reply path.
6. Confirm high-risk Telegram summary path.
7. Test Outlook webhook path with valid Graph credentials and a live subscription.
8. Save screenshots/log IDs for the demo.
9. Write a technical report covering working behavior, limitations, and next steps.
