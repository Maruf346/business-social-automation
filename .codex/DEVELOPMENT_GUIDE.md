# Development Guide

Last reviewed: 2026-08-26

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

Run with Docker locally:

```powershell
docker compose up --build
```

Production compose render check:

```powershell
$env:DOCKER_IMAGE="dockerhub_username/tattoo-hysteria-backend:latest"
$env:POSTGRES_PASSWORD="change_me"
docker compose -f docker-compose.prod.yml config
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
/api/v1/webhook/vcita/
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
- `DATABASE_URL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `DATABASE_SSL_REQUIRE`
- `DB_CONN_MAX_AGE`
- `CELERY_BROKER_URL`
- `USE_S3`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_STORAGE_BUCKET_NAME`
- `AWS_S3_REGION_NAME`
- `AWS_S3_CUSTOM_DOMAIN`
- `AWS_LOCATION`
- `AWS_QUERYSTRING_AUTH`
- `AWS_DEFAULT_ACL`
- `DOCKER_IMAGE`
- `GUNICORN_WORKERS`
- `GUNICORN_THREADS`
- `GUNICORN_TIMEOUT`

GitHub Actions variables/secrets for Docker Hub:

- Repository variable `DOCKERHUB_USERNAME`.
- Repository variable `DOCKERHUB_REPOSITORY`, optional, defaults to `tattoo-hysteria-backend`.
- Repository secret `DOCKERHUB_TOKEN`.

GitHub Actions variables/secrets for EC2 deploy:

- Repository variable `ENABLE_EC2_DEPLOY=true` to enable deployment.
- Repository variable `EC2_APP_DIR`, optional, defaults to `/opt/tattoo-hysteria-backend`.
- Repository secret `EC2_HOST`.
- Repository secret `EC2_USER`.
- Repository secret `EC2_SSH_KEY`.
- Repository secret `EC2_SSH_PORT`, optional.

## Intake State App

The `intake` app owns backend memory for AI-driven intake.

Models:

- `IntakeRequest`: latest known tattoo request state.
- `AIAnalysis`: raw and normalized AI response snapshots.
- `OutboundAction`: pending/sent/failed audit records for client reply attempts.
- Current intake state stores AI summary, AI suggested price, Hoss-approved price, price note, approver, and approval timestamp.
- Django admin for `IntakeRequest` is organized for local testing: summary, draft reply, AI suggested price, approved price, and price note can be edited directly before sending a Telegram review card.

Service:

- `IntakeStateService` builds `existing_db_state` and applies AI responses back to the database.
- `ClientOutboundService` sends WhatsApp/Outlook replies and creates `OutboundAction` records for supported outbound paths.

After model changes:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations intake
.\.venv\Scripts\python.exe manage.py migrate intake
```

## vCita App

The `vcita` app is Phase 1 scaffolding for the vCita calendar/booking path.

Admin setup:

1. Open Django admin.
2. Add a `VcitaAccount`.
3. Set `api_token` to the vCita API token.
4. Keep `api_base_url=https://api.vcita.biz` unless vCita provides another endpoint.
5. Set `is_active=True`.

Webhook URL:

```text
/api/v1/webhook/vcita/
```

Current behavior:

- `GET /api/v1/webhook/vcita/` returns a health response.
- `POST /api/v1/webhook/vcita/` stores the raw webhook payload in `VcitaWebhookEvent`.
- No lead/client/booking/payment mapping happens yet.

Smoke-test the API token after adding `VcitaAccount`:

```powershell
.\.venv\Scripts\python.exe manage.py vcita_smoke_test
```

Or inside production Docker:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py vcita_smoke_test
```

After vCita model changes:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations vcita
.\.venv\Scripts\python.exe manage.py migrate vcita
```

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

- Telegram webhook endpoint now dispatches updates to `TelegramWorkflowService`.
- `/whoami` returns Telegram user/chat IDs and stores private chat ID for registered artists.
- Callback query handling supports Hoss-only approve/reject/Edit Reply/assign actions.
- Callback query handling supports Hoss-only Edit Price.
- Shared group actions must be authorized to Hoss only.
- Edit Reply tells Hoss to send `/reply REQUEST_ID message text` in the group; only an artist with `can_approve=True` can send that command for an unassigned intake.
- Edit Price tells Hoss to send `/price REQUEST_ID price | optional note`; this updates internal pricing only.
- Older cards with the previous `manual` callback action are treated as Edit Reply for backward compatibility.
- Artist private replies should be mapped by `reply_to_message.message_id` to a stored `TelegramMessageLink`.
- Assigned artist fallback reply format should be `/reply REQUEST_ID message text`.
- Assigned artist private cards include request context: idea, approved/AI price, optional price note, placement, size, color, and summary.
- Artists can send text, photos, or documents in private replies. WhatsApp receives media through Meta link sends; Outlook receives media links in the email reply.
- Fake/admin-created intakes with `source=other` can test Telegram cards and button routing, but they cannot send real client replies. Approve/Edit/artist send actions should report this in Telegram instead of crashing the webhook.

Artist setup in Django admin:

1. Create an `ArtistProfile` for Hoss.
2. Set Hoss `telegram_user_id`.
3. Set Hoss `can_approve=True`.
4. Create `ArtistProfile` rows for other artists.
5. Ask each artist to start the bot and run `/whoami`.
6. Copy/store their `telegram_user_id` if not already known; the private `telegram_chat_id` is saved automatically for registered artists.

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
