# Technical Debt and Risks

Last reviewed: 2026-08-22

## High Priority

### Outlook Webhook Does Not Trigger Processing

`OutlookWebhook.post()` currently logs the incoming payload but the orchestrator call is commented out.

Impact:

- Outlook end-to-end intake may not work from webhooks.

Fix:

- Re-enable `WebhookOrchestrator.process_outlook_webhook(payload, webhook_log)`.
- Add tests with sample Microsoft Graph webhook payloads.

### No Automated Tests

The repo has test files but no real tests.

Impact:

- Regression risk is high for webhook parsing, AI branching, and external API calls.

Fix:

- Add unit tests for parsers and services.
- Add integration-style tests for webhook endpoints with mocked external APIs.

### Hardcoded Telegram Chat ID

Telegram chat ID `8145617629` appears in service/task code.

Impact:

- Unsafe for production and hard to move across environments.

Fix:

- Move to env var or database-backed team/channel config.

### AI Summary URL Hardcoded

AI analysis URL is configurable, but summary URL is hardcoded in `AIService`.

Impact:

- Cannot safely switch AWS environments without code changes.

Fix:

- Add `AI_SUMMARY_API_URL` to settings and `.env.example`.

### AI Service Contract Is Implicit

Backend assumes fields such as `draft_reply` and `risk_level`.

Impact:

- AI/backend integration can break silently if response shape changes.

Fix:

- Define a formal AI API contract with the AI engineer.
- Validate response fields in backend.
- Store raw and normalized AI response.

## Medium Priority

### Outlook Subscription Signals May Not Register

`core/signals.py` defines post-save/pre-delete handlers, but `core/apps.py` does not import signals in `ready()`.

Impact:

- Creating or updating `WebhookSubscription` may not sync with Microsoft Graph.

Fix:

- Add `ready()` import or replace implicit signals with explicit admin/service actions.

### Docker Uses Gunicorn But Requirements Do Not Include It

Dockerfile and docker-compose run `gunicorn`, but `requirements.txt` does not list `gunicorn`.

Impact:

- Container startup can fail.

Fix:

- Add `gunicorn` to requirements or change Docker command.

### Celery Is Eager

`CELERY_TASK_ALWAYS_EAGER = True`.

Impact:

- Local flow is simpler, but production behavior differs from real async workers.

Fix:

- Make eager mode env-driven.
- Configure Redis broker and worker in deployment.

### Local Database Is Empty

Current `db.sqlite3` has no account, lead, message, or webhook data.

Impact:

- Cannot prove live integration state from the checkout.

Fix:

- Create reproducible demo fixtures or seed scripts without secrets.

### README Is Outdated

README Swagger URLs mention `/api/schema/swagger-ui/`, while actual Swagger URL is `/api/docs/`.

Impact:

- New developers may use wrong docs URL.

Fix:

- Update README after the `.codex` handover docs are accepted.

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
- Telegram callbacks must verify user IDs for Nina/Hoss/admin.
- Internal pricing must never be sent to clients without human approval.
- Media URLs should be reviewed before production; public dev tunnel URLs are not a long-term storage strategy.

## Documentation Risk

If `.codex` files are not updated during development, future context will drift.

Rule:

- Every meaningful backend change should update code and docs together.
