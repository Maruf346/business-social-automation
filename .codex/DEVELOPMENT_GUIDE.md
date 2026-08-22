# Development Guide

Last reviewed: 2026-08-22

## Local Environment

Project root:

```powershell
C:\Users\maruf\Projects\business-social-automation
```

Use the project virtual environment:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Global `python` may not have Django installed, so prefer the venv path.

## Common Commands

Run Django checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Run tests:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

Run local server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 8007
```

Show migrations:

```powershell
.\.venv\Scripts\python.exe manage.py showmigrations
```

Create superuser:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Important URLs

Local server base:

```text
http://127.0.0.1:8007/
```

Swagger:

```text
http://127.0.0.1:8007/api/docs/
```

OpenAPI schema:

```text
http://127.0.0.1:8007/api/schema/
```

ReDoc:

```text
http://127.0.0.1:8007/api/redoc/
```

Webhook paths:

```text
/api/v1/webhook/meta/
/api/v1/webhook/outlook/
/api/v1/webhook/telegram/
```

## Environment Variables

Current important variables:

- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SERVE_MEDIA`
- `MEDIA_ROOT`
- `MEDIA_BASE_URL`
- `META_VERIFY_TOKEN`
- `META_APP_SECRET`
- `META_API_VERSION`
- `AI_API_URL`
- `AI_SUMMARY_API_URL`
- `AI_API_TIMEOUT`
- `AI_CHAT_HISTORY_LIMIT`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_REVIEW_CHAT_ID`
- `CELERY_TASK_ALWAYS_EAGER`
- `CELERY_TASK_EAGER_PROPAGATES`

Recommended additions:

- Database URL or explicit PostgreSQL settings.

## External AI Service

The AI service is developed in a separate repo by an AI engineer and will be deployed separately, likely on AWS.

Backend expectations today:

- Call analysis endpoint from `AI_API_URL`.
- Call summary endpoint for Telegram review.
- Send current message, recent history, image URLs, and canonical backend state through `existing_db_state`.
- Receive updated structured fields including tattoo idea, style tags, placement, size estimate, color preference, suggested artist, confidence level, AI reasoning, missing information, risk level, and draft reply.
- Persist AI response fields back to the backend database after every AI call.
- Send the updated DB state back to AI on the next message.

Do not implement AI extraction logic in this repo unless the project scope changes. This backend should validate, persist, and act on AI service responses.

See `AI_INTEGRATION_CONTRACT.md` for the full endpoint payload and response contract.

## Webhook Development Notes

WhatsApp:

- GET validates Meta webhook handshake.
- POST verifies HMAC if `META_APP_SECRET` is configured.
- Incoming payloads are saved to `WebhookLog`.
- Message events create/update `Lead` and `Message`.
- Status events update message status.

Outlook:

- GET handles Microsoft validation token.
- POST handles Microsoft validation token, logs payload, and calls the Outlook orchestrator.
- Live end-to-end behavior still requires valid Graph credentials and webhook subscription data.

Telegram:

- Current webhook endpoint only echoes `{"ok": true}`.
- Milestone 2 should implement callback query handling for inline buttons.

## Testing Strategy

Add tests in this order:

1. Health/docs endpoints.
2. WhatsApp parser fixtures.
3. Outlook parser fixtures.
4. Message service lead/message creation.
5. AI service payload construction.
6. Low-risk task branch with mocked AI and Meta API.
7. High-risk task branch with mocked AI and Telegram API.
8. Outlook fetch/generate/send chain with mocked Graph API.
9. Telegram callback authorization and decisions.

External APIs should be mocked in tests.

## Documentation Update Rule

When code changes:

- Update `.codex/PROJECT_CONTEXT.md` if architecture, routes, models, or flow changed.
- Update `.codex/HANDOVER_AUDIT.md` if a Milestone 1 gap is fixed or reclassified.
- Update `.codex/MILESTONE_2_PLAN.md` if planning or implementation order changes.
- Update `.codex/TECH_DEBT_AND_RISKS.md` when risks are added or resolved.
- Update this guide when commands, env vars, setup, or endpoints change.

This keeps Codex context current for future development sessions.
