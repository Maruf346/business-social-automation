# Technical Debt and Risks

Last reviewed: 2026-08-29

## High Priority

### Outlook Webhook Live Verification Still Needed

`OutlookWebhook.post()` now calls the orchestrator and handles Microsoft Graph validation tokens.

Impact:

- The code path is connected, but a live Outlook webhook still needs valid Graph credentials, subscription records, and end-to-end verification.

Next:

- Configure an `OutlookAccount`.
- Create/verify a `WebhookSubscription`.
- `WebhookSubscription` creation now sends `expirationDateTime` to Microsoft Graph in UTC `Z` format.
- Send a live or fixture-backed Graph notification through the endpoint.

### No Automated Tests

The repo has test files but no real tests.

Impact:

- Regression risk is high for webhook parsing, AI branching, and external API calls.

Fix:

- Add unit tests for parsers and services.
- Add integration-style tests for webhook endpoints with mocked external APIs.

### Telegram Review Chat Is Env-Configured

Telegram review chat ID is now read from `TELEGRAM_REVIEW_CHAT_ID`.

Impact:

- This is acceptable for Phase 0. Milestone 2 may need database-backed team/channel configuration.

Next:

- Add staff/team configuration models when building the Telegram command center.

### Telegram Assignment and Private Reply Routing Needs Live Verification

The backend now has models and handlers for Hoss-only approval, dynamic artist assignment, Telegram callback mapping, and private artist-to-client replies.

Impact:

- This is implemented but not yet verified with the live Telegram Bot API/webhook.
- Hoss and artists must be configured in Django admin with real Telegram numeric user IDs.
- Artists must start the bot or run `/whoami` so their private `telegram_chat_id` is known.
- Outlook media replies are currently sent as links, not true email attachments.

Next:

- Configure `ArtistProfile` records.
- Set Hoss `can_approve=True`.
- Set Telegram webhook to `/api/v1/webhook/telegram/`.
- Verify group approval, Edit Reply, assignment, private reply, and `/reply` fallback with real Telegram updates.

### AI Summary URL Is Env-Configured

AI analysis and summary URLs are now configurable. `AI_SUMMAERY_API_URL` is still accepted as a backward-compatible fallback for the previous typo, but new env files should use `AI_SUMMARY_API_URL`.

Impact:

- Backend and AI engineer still need a formal versioned response contract.

Next:

- Confirm the final deployed AWS endpoint paths.
- Validate response shape before Milestone 2 decision persistence work.

### AI State Persistence Implemented, Needs Live Verification

The backend now persists updated structured intake fields into `IntakeRequest` and stores every AI response snapshot in `AIAnalysis`.

Impact:

- The code path exists, but it still needs live verification against the deployed AI endpoint.
- The current implementation does not yet expose an admin/operator workflow for reviewing these records beyond Django admin.
- Human decisions and outbound action audit records exist; correction/business-rule learning records are still not implemented.

Next:

- Verify `existing_db_state` payload with the AI engineer.
- Confirm AI response values for `risk_level` and `confidence_level`.
- Build correction/business-rule models when the feedback-learning phase starts.
- Add validation before production auto-send.

### Outbound Audit Logging Needs Live Provider Verification

`OutboundAction` now records pending/sent/failed attempts for client replies.

Impact:

- The audit path is implemented for AI auto-replies, waiting messages, Hoss-approved replies, Hoss-edited replies, and artist replies.
- Real provider response bodies are not yet stored in detail; WhatsApp provider message IDs are linked through the outgoing `Message`.
- Outlook low-risk sends keep the existing staged pipeline and are wrapped with `OutboundAction` instead of being fully refactored through `ClientOutboundService`.

Next:

- Verify sent/failed statuses with real WhatsApp and Outlook provider failures.
- Decide later whether to expose `OutboundAction` in admin or an operator dashboard.

### AI Service Contract Must Stay Versioned

The current AI endpoint contract is documented in `AI_INTEGRATION_CONTRACT.md`.

Impact:

- AI/backend integration can break if payloads or response fields change without coordination.

Fix:

- Keep `AI_INTEGRATION_CONTRACT.md` updated with the AI engineer.
- Add validation around required fields before auto-sending client replies.
- Store raw AI response payloads for debugging.

## Medium Priority

### Outlook Subscription Signals Registered

`core.signals` is now imported in `CoreConfig.ready()`, and settings use `core.apps.CoreConfig`.

Impact:

- Signal registration should now run when Django starts. Live behavior still depends on valid Graph credentials and subscription data.

Next:

- Consider replacing implicit signals with explicit admin/service actions if subscription side effects become hard to reason about.

### Docker Deployment Needs Real Server Verification

Dockerfile, local compose, production compose, nginx proxy, Docker Hub CI, and optional EC2 deploy scaffolding now exist.

Impact:

- Django system checks pass locally.
- Compose files render, but Docker emitted a local Windows Docker config permission warning while reading `C:\Users\maruf\.docker\config.json`.
- The image build/push and EC2 pull/restart flow still need to be verified with real Docker Hub and AWS credentials.
- The production deploy assumes the EC2 app directory contains this repository and a production `.env`.

Next:

- Add GitHub repository variables/secrets.
- Build and push the first image.
- Prepare EC2 with Docker, Docker Compose, and the repo checkout.
- Run the first production compose startup and verify `/api/docs/` over the EC2 public IP.

### S3 Media Storage Prepared But Not Live

Settings support S3 media through `USE_S3=True` and AWS S3 env vars.

Impact:

- Local media remains default.
- S3 behavior needs a real bucket, IAM credentials, and an access decision: public bucket policy/CDN URLs or signed URLs.

Next:

- Create the S3 bucket.
- Configure least-privilege IAM access for object upload/read.
- Decide whether AI image URLs must be public or signed.

### Celery Is Eager

`CELERY_TASK_ALWAYS_EAGER` is now env-driven and defaults to true for local development.

Impact:

- Local flow is simpler, but production behavior differs from real async workers.

Next:

- Configure Redis broker and worker in deployment.

### Local Database Is Empty

Current `db.sqlite3` has no account, lead, message, or webhook data.

Impact:

- Cannot prove live integration state from the checkout.
- Fake/admin-created intakes with `source=other` cannot complete outbound replies because there is no WhatsApp or Outlook target channel.

Fix:

- Create reproducible demo fixtures or seed scripts without secrets.
- For full outbound testing, create the intake from a real WhatsApp or Outlook webhook context.

### README API Docs URLs Updated

README API docs URLs now point to `/api/docs/` and `/api/redoc/`.

Impact:

- README is still broad and generic, but the API docs paths are no longer misleading.

Next:

- Consider a fuller README cleanup after the Milestone 2 backend direction is settled.

### Encoding Artifacts

Several files and README text show mojibake characters.

Impact:

- Documentation and logs look unprofessional and may hide intended text.

Fix:

- Clean docs/comments carefully without changing runtime behavior.

## Product / Scope Risks

### FastAPI vs Django Mismatch

Milestone 2 document says backend should be Python/FastAPI, but current repo is Django.

Risk:

- A rewrite could derail delivery.

Recommendation:

- Continue in Django unless client explicitly requires FastAPI and accepts timeline impact.

### AI Ownership Is Separate

AI implementation is in another repo.

Risk:

- Backend delivery depends on AI API availability and contract stability.

Recommendation:

- Agree on versioned AI endpoint contracts early.
- Mock AI responses in backend tests.

### Telegram UI Expectations

The note mentions forms/input boxes using HTML. Telegram chat messages do not support normal HTML forms.

Recommendation:

- Use inline buttons and callback queries first.
- Use Telegram Web Apps only if rich editing is truly needed.

### vCita Feasibility Still Needs Live Token and Payload Verification

vCita scaffolding and initial scheduling now exist: `VcitaAccount`, `VcitaWebhookEvent`, `/api/v1/webhook/vcita/`, `VcitaAPIClient`, Admin panel token/userinfo/staff/service actions, `vcita_smoke_test`, and Hoss-only Telegram scheduling.

Risk:

- Full Milestone 2 vCita behavior may depend on unsupported API features or token access level.
- Webhook payload shape is not yet verified against the client's live vCita account.
- API write capabilities for client creation, booking creation/update, notes, and exact accepted payload field names still need confirmation against the live client token.
- The webhook receiver can enforce an optional shared secret through `?secret=...` or `X-Vcita-Webhook-Secret`, but vCita's own signature strategy is still unknown.
- Payment webhook processing is conservative and only updates intakes when a payload contains a booking/appointment/meeting ID matching `IntakeRequest.vcita_booking_uid`.

Recommendation:

- Add the client's vCita token in the Admin panel as `VcitaAccount`.
- Run `Sync vCita business info from token`, `Show active vCita staff IDs`, and `Show vCita service IDs`.
- Save vCita staff UID on each `ArtistProfile` and default service UID on `VcitaAccount`.
- Test `vcita_smoke_test` and one controlled `/schedule REQUEST_ID YYYY-MM-DD HH:MM` against the live token.
- Configure vCita webhook to `/api/v1/webhook/vcita/`, preferably with the shared secret query parameter.
- Inspect real webhook payloads in `VcitaWebhookEvent` and refine payment/status extraction if needed.

## Security Risks

- Secrets are env-driven but `.env` exists locally and must never be committed.
- Webhook endpoints are unauthenticated by design, so signature/clientState validation matters.
- vCita webhook verification/signature strategy is still unknown and must be confirmed before production reliance.
- Telegram callbacks must verify Hoss for group approval actions and the assigned artist for private reply actions.
- Internal pricing must never be sent to clients without human approval.
- Media URLs should be reviewed before production; public dev tunnel URLs are not a long-term storage strategy.

## Documentation Risk

If `.codex` files are not updated during development, future context will drift.

Rule:

- Every meaningful backend change should update code and docs together.
