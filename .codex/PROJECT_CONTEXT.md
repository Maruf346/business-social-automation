# Project Context

Last reviewed: 2026-08-27

## Product Goal

TattooHysteria Ink-Flow is an omnichannel intake and workflow backend for a tattoo studio. It receives client messages from supported channels, stores leads/conversations/messages, calls an external AI service for extraction and routing guidance, and coordinates owner/artist review through Telegram before final client responses or booking actions.

The project is being continued after a midway handover. Treat the current repo as a partial foundation, not as a fully delivered production system.

## Repository Responsibility

This repository owns the backend orchestration layer:

- Channel webhooks and API callbacks.
- Lead, conversation, message, media, and integration persistence.
- Calls to external services: WhatsApp/Meta, Microsoft Graph/Outlook, Telegram, and the separate AI service.
- Risk-based routing decisions based on AI service responses.
- Human-in-the-loop workflow, decision logging, calendar/vCita integration, and deployment work for Milestone 2.

This repository does not own the AI implementation itself. An AI engineer is building the AI service in a separate repository. The backend should call the AI service through deployed HTTP endpoints, expected to be hosted separately on AWS.

## Current Stack

- Backend: Django 6.0.7, Django REST Framework.
- API docs: drf-spectacular, Swagger at `/api/docs/`.
- Auth/config scaffolding: SimpleJWT, custom `account.User`.
- Task system: Celery, currently configured as eager in local settings.
- Database: SQLite by default for local direct `runserver`; Postgres is supported through `DATABASE_URL` or `POSTGRES_*` env vars and is used by Docker Compose.
- Deployment: Docker image build, production compose, nginx reverse proxy, Redis service, Celery worker service, and optional S3 media storage are now scaffolded.
- External APIs: Meta WhatsApp Graph API, Microsoft Graph API, Telegram Bot API, external AI API.
- vCita/inTandem integration: Phase 1 scaffold exists for account token storage, webhook capture, and Bearer-token API smoke checks.

Important mismatch: the Milestone 2 note mentions FastAPI, LangChain/LangGraph, PostgreSQL, and AWS. The current repo is Django/DRF/Celery/SQLite. Prefer evolving this Django backend unless a rewrite is explicitly approved.

## Django Apps

### `account`

Custom user/device models and admin-related user foundation.

Current visible state:

- `User` model uses email login.
- `Device` model exists.
- No implemented API views or routes yet.

### `lead`

CRM-style data models.

Key models:

- `Lead`: client identity by source plus phone/email, including `vcita_client_uid` once mapped to vCita.
- `Conversation`: threaded conversations, mainly useful for Outlook.
- `Message`: incoming/outgoing message records.
- `MediaFile`: downloaded WhatsApp media or Outlook attachments.
- `Tag` and `LeadTag`: basic tagging foundation.

### `intake`

AI-backed intake state and analysis history.

Key models:

- `IntakeRequest`: canonical latest tattoo request state for a lead/conversation.
- `AIAnalysis`: immutable snapshot of every AI analysis response, linked to the triggering message and intake, including summary, AI suggested price, and AI-proposed appointment date/time.
- `ArtistProfile`: admin-managed artists, Telegram user IDs, private chat IDs, Hoss-only approval flag, and optional vCita staff UID mapping.
- `HumanDecision`: approval, rejection, assignment, edited reply, and artist reply actions.
- `TelegramMessageLink`: maps bot messages to intakes so private artist replies can be resolved safely.
- `OutboundAction`: audit trail for attempted client replies with pending/sent/failed status.

Key services:

- `IntakeStateService.get_or_create_active_intake(...)`
- `IntakeStateService.build_existing_db_state(...)`
- `IntakeStateService.record_ai_response(...)`
- `TelegramWorkflowService.handle_update(...)`
- `TelegramWorkflowService.send_review_card(...)`
- `TelegramWorkflowService.send_artist_update(...)`
- `ClientOutboundService.send_intake_reply(...)`

Current behavior:

- WhatsApp and Outlook AI flows now create/load an active intake before calling AI.
- The backend sends canonical intake data as `existing_db_state`.
- After every AI analysis response, the backend updates `IntakeRequest` and stores an `AIAnalysis`.
- Low-risk responses continue client auto-reply.
- High, medium, or unknown risk values route toward human review instead of auto-send.
- High-risk review cards now use DB-driven inline buttons.
- High-risk review cards show price, AI suggested price, optional price note, summary, and draft reply.
- Review cards show AI-proposed appointment date/time when AI returns both `date` and `time`; this also reveals the Schedule button.
- Assigned intakes route future client messages to the assigned artist's private Telegram inbox.
- Assigned artist private cards include intake context such as idea, pricing, placement/size/color, and summary.
- Artist private replies are mapped by reply-to message or `/reply REQUEST_ID ...` and sent back to the original client channel.
- Client reply attempts are recorded in `OutboundAction` for AI auto-replies, waiting messages, Hoss-approved replies, Hoss-edited replies, and artist replies.

### `core`

Integration and orchestration layer.

Key models:

- `WhatsAppAccount`: Meta/WABA account configuration.
- `OutlookAccount`: Microsoft Graph account configuration.
- `WebhookSubscription`: Outlook webhook subscription config.
- `OutlookAccessToken`: stored Graph access token.
- `WebhookLog`: raw incoming webhook logs.

Key flows:

- WhatsApp webhook receives Meta payloads.
- Parser extracts message/status events.
- Orchestrator creates/updates lead and message records.
- Celery task calls the AI service.
- Low-risk AI result sends client auto-reply.
- High-risk AI result sends waiting message to client and Telegram summary to the team.
- Client outbound attempts are audited through `OutboundAction` records.

### `vcita`

vCita integration foundation.

Key models:

- `VcitaAccount`: admin-managed API token, API base URL, business UID/name, legacy default service UID, default timezone, and optional webhook secret.
- `VcitaService`: admin-managed service-code mapping from short Telegram code, such as `OCH`, to vCita service UID and display name.
- `VcitaWebhookEvent`: raw webhook event storage, including headers, payload, body, event/entity hints, external id, status, and processing error.

Key code:

- `VcitaAPIClient`: Bearer-token client for vCita userinfo, staff/services discovery, webhook subscription/listing, client lookup/creation, availability checks, and booking create/update calls.
- `VcitaSchedulingService`: creates or updates vCita bookings for assigned intakes and stores vCita booking IDs back on `IntakeRequest`.
- `VcitaWebhook`: unauthenticated webhook receiver at `/api/v1/webhook/vcita/`.
- `vcita_smoke_test`: management command that calls a simple vCita endpoint using the active account token.

Current behavior:

- vCita webhook GET returns a health response.
- vCita webhook POST stores raw payloads safely and returns `EVENT_RECEIVED`.
- If a webhook payload contains a booking/appointment/meeting ID matching an intake, payment and booking status hints update `IntakeRequest` and notify Telegram.
- Unknown vCita webhook payloads are stored only; live payload shapes still need verification.
- The API token is stored in Django admin, not environment variables.

## Current Routes

- `/` - basic backend health JSON.
- `/api/v1/` - basic API endpoint JSON.
- `/api/v1/webhook/meta/` - WhatsApp/Meta webhook.
- `/api/v1/webhook/outlook/` - Outlook webhook.
- `/api/v1/webhook/telegram/` - basic Telegram webhook echo.
- `/api/v1/webhook/vcita/` - vCita webhook receiver.
- `/api/schema/` - OpenAPI schema.
- `/api/docs/` - Swagger UI.
- `/api/redoc/` - ReDoc UI.

## Deployment Shape

Current deployment target is AWS EC2 without a custom domain for the first pass.

Implemented deployment assets:

- `Dockerfile` builds the Django/gunicorn image and runs `docker/start-web.sh`.
- `docker/start-web.sh` runs migrations, collects static files, and starts gunicorn on port `8007`.
- `docker/start-worker.sh` starts the Celery worker for webhook follow-up tasks.
- `docker-compose.yml` supports local container runs with backend, Celery worker, Postgres, and Redis.
- `docker-compose.prod.yml` runs backend image, Celery worker, Postgres, Redis, and nginx.
- `nginx/default.conf` listens on port `80` and proxies all traffic to the backend container.
- `.github/workflows/pipeline.yml` builds and pushes the Docker image to Docker Hub on pushes to `main`.
- The EC2 deploy job is gated by `ENABLE_EC2_DEPLOY=true`; it copies `docker-compose.prod.yml` and `nginx/default.conf` over SCP, then pulls the latest Docker Hub image and restarts `docker-compose.prod.yml` over SSH. EC2 does not need GitHub repo credentials for deploy.

Media uploads are prepared for S3 through `USE_S3=True` and AWS S3 env vars. Local media remains the default when S3 is disabled.

## AI Service Contract

The detailed AI contract lives in `AI_INTEGRATION_CONTRACT.md`.

The backend calls:

- `POST /api/v1/inquiries/analyze`
- `POST /api/v1/inquiries/telegram-summary`

The analysis endpoint accepts:

- `current_message`
- `new_image_urls`
- `existing_db_state`
- `recent_chat_history`

The analysis endpoint returns updated structured intake fields:

- `tattoo_idea`
- `style_tags`
- `placement`
- `size_estimate_cm`
- `color_preference`
- `suggested_artist`
- `confidence_level`
- `ai_reasoning`
- `missing_information`
- `risk_level`
- `summary`
- `suggested_price` / `price`
- `pricing_reasoning`
- `date`: AI-proposed appointment date in `YYYY-MM-DD`.
- `time`: AI-proposed appointment time in `HH:MM`.
- `draft_reply`: proposed client-facing reply.

The backend also calls a summary endpoint for Telegram/human review. The summary endpoint is configured with `AI_SUMMARY_API_URL` and should be finalized with the AI engineer.

Telegram review messages are sent to the chat configured by `TELEGRAM_REVIEW_CHAT_ID`.

Important implementation rule:

- The backend database must store the latest structured intake state returned by AI after every message.
- That stored state must be sent back to AI as `existing_db_state` on the next message.
- This is how AI knows what is already known and what is still missing.

## Human Roles

Known studio decision makers:

- Hoss: only approver for group approval/assignment actions.
- Artists: dynamic list managed in the backend, expected to include Nina, Hoss, Lana, and additional artists.

Artist assignment rules:

- High-risk intakes first go to the shared Telegram group.
- Hoss can approve an AI draft reply, reject, choose Edit Reply, or assign the active intake to an artist.
- Edit Reply keeps the intake waiting for human action and tells Hoss to send the final client message with `/reply REQUEST_ID message text` in the shared group.
- Hoss can choose Edit Price and then update internal approved pricing with `/price REQUEST_ID price | optional note`.
- Hoss schedules an assigned intake with `/schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM`, for example `/schedule 12 OCH 2026-09-04 14:30`.
- The Schedule button appears when AI provided date/time, but it now shows service-code guidance instead of silently using a default service.
- Hoss can view human decision history with `/logs`, `/logs REQUEST_ID`, `/logs --20`, or `/logs REQUEST_ID --20`; default limit is 10 and max is 30.
- Schedule commands resolve `SERVICE_CODE` through active `VcitaService` rows, use the vCita account timezone, defaulting to `Europe/Amsterdam`, and store date/time plus service snapshot on the intake.
- If Hoss tries to schedule before assigning an artist, the bot replies: `Please assign an artist first, then schedule this request.`
- Price updates are internal only and do not send anything to the client.
- Older Telegram cards using the previous `manual` callback action are still routed into the Edit Reply flow.
- Only Hoss, represented by an active `ArtistProfile` with `can_approve=True`, can use group `/reply` for an unassigned intake.
- Hoss can assign the intake to himself; after assignment, he receives private inbox messages like any other artist.
- Assignment applies to the active `IntakeRequest`, not permanently to the whole lead.
- After assignment, future client messages for that intake route to the assigned artist's private Telegram chat.
- Assigned artist replies are sent automatically to the client through the original channel.
- Successful vCita scheduling notifies the shared Telegram group, the assigned artist privately, and the client through the original channel.
- Artist private replies should support text and media/files.
- Current implementation supports Telegram text/photo/document private replies. WhatsApp receives media through Meta link sends; Outlook receives media as links in the email reply.

The backend needs a canonical Telegram identity model for Hoss and every artist, including Telegram numeric user ID and private chat ID.

## Documentation Maintenance Rule

Whenever implementation changes:

- Update `PROJECT_CONTEXT.md` for architecture or flow changes.
- Update `HANDOVER_AUDIT.md` when a Milestone 1 gap is closed or reclassified.
- Update `MILESTONE_2_PLAN.md` when task scope/order changes.
- Update `TECH_DEBT_AND_RISKS.md` when risks are fixed or discovered.
- Update `DEVELOPMENT_GUIDE.md` when commands, env vars, endpoints, or setup change.
