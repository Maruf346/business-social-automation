# Technical Debt and Risks

Last reviewed: 2026-08-23

## High Priority

### Outlook Webhook Live Verification Still Needed

`OutlookWebhook.post()` now calls the orchestrator and handles Microsoft Graph validation tokens.

Impact:

- The code path is connected, but a live Outlook webhook still needs valid Graph credentials, subscription records, and end-to-end verification.

Next:

- Configure an `OutlookAccount`.
- Create/verify a `WebhookSubscription`.
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
- Human decisions and corrections are not implemented yet.

Next:

- Verify `existing_db_state` payload with the AI engineer.
- Confirm AI response values for `risk_level` and `confidence_level`.
- Build Telegram decision/correction models and callbacks.
- Add validation before production auto-send.

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

### Docker Gunicorn Dependency Added

Dockerfile and docker-compose run `gunicorn`, and `requirements.txt` now includes it.

Impact:

- Docker still needs a full build/run verification before production use.

Next:

- Verify Docker image build in the target environment.

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

### vCita Unknowns

No vCita feasibility report exists in this repo.

Risk:

- Milestone 2 vCita implementation may depend on unsupported API features.

Recommendation:

- Do feasibility spike before committing implementation details.

## Security Risks

- Secrets are env-driven but `.env` exists locally and must never be committed.
- Webhook endpoints are unauthenticated by design, so signature/clientState validation matters.
- Telegram callbacks must verify Hoss for group approval actions and the assigned artist for private reply actions.
- Internal pricing must never be sent to clients without human approval.
- Media URLs should be reviewed before production; public dev tunnel URLs are not a long-term storage strategy.

## Documentation Risk

If `.codex` files are not updated during development, future context will drift.

Rule:

- Every meaningful backend change should update code and docs together.
