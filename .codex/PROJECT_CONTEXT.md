# Project Context

Last reviewed: 2026-08-22

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
- Database: SQLite in current settings; Milestone 2 expects PostgreSQL, likely with pgvector.
- External APIs: Meta WhatsApp Graph API, Microsoft Graph API, Telegram Bot API, external AI API.

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

- `Lead`: client identity by source plus phone/email.
- `Conversation`: threaded conversations, mainly useful for Outlook.
- `Message`: incoming/outgoing message records.
- `MediaFile`: downloaded WhatsApp media or Outlook attachments.
- `Tag` and `LeadTag`: basic tagging foundation.

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

## Current Routes

- `/` - basic backend health JSON.
- `/api/v1/` - basic API endpoint JSON.
- `/api/v1/webhook/meta/` - WhatsApp/Meta webhook.
- `/api/v1/webhook/outlook/` - Outlook webhook.
- `/api/v1/webhook/telegram/` - basic Telegram webhook echo.
- `/api/schema/` - OpenAPI schema.
- `/api/docs/` - Swagger UI.
- `/api/redoc/` - ReDoc UI.

## AI Service Contract

The backend currently expects an AI analysis endpoint that accepts:

- `current_message`
- `new_image_urls`
- `existing_db_state`
- `recent_chat_history`

The backend currently expects at least:

- `draft_reply`: proposed client-facing reply.
- `risk_level`: currently handled as `low` or `high`.

The backend also calls a summary endpoint for Telegram/human review. This should become environment-configured and should be finalized with the AI engineer.

Recommended next contract fields for Milestone 2:

- `extracted_details`
- `missing_information`
- `suggested_artist`
- `artist_confidence`
- `risk_level`
- `risk_reason`
- `draft_reply`
- `internal_price_estimate`
- `style_tags`
- `reference_image_findings`

## Human Roles

Known studio decision makers:

- Nina
- Hoss

Future artist/routing notes mention Lana for fine-line style. This is not modeled yet.

The backend needs a canonical user/role model for Telegram actors so it can know which Telegram user is Nina, Hoss, admin, or another artist.

## Documentation Maintenance Rule

Whenever implementation changes:

- Update `PROJECT_CONTEXT.md` for architecture or flow changes.
- Update `HANDOVER_AUDIT.md` when a Milestone 1 gap is closed or reclassified.
- Update `MILESTONE_2_PLAN.md` when task scope/order changes.
- Update `TECH_DEBT_AND_RISKS.md` when risks are fixed or discovered.
- Update `DEVELOPMENT_GUIDE.md` when commands, env vars, endpoints, or setup change.
