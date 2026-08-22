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

### `intake`

AI-backed intake state and analysis history.

Key models:

- `IntakeRequest`: canonical latest tattoo request state for a lead/conversation.
- `AIAnalysis`: immutable snapshot of every AI analysis response, linked to the triggering message and intake.
- `ArtistProfile`: admin-managed artists, Telegram user IDs, private chat IDs, and Hoss-only approval flag.
- `HumanDecision`: approval, rejection, assignment, manual, and artist reply actions.
- `TelegramMessageLink`: maps bot messages to intakes so private artist replies can be resolved safely.

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
- Assigned intakes route future client messages to the assigned artist's private Telegram inbox.
- Artist private replies are mapped by reply-to message or `/reply REQUEST_ID ...` and sent back to the original client channel.

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
- Hoss can approve an AI draft reply, reject, mark manual, or assign the active intake to an artist.
- Hoss can assign the intake to himself; after assignment, he receives private inbox messages like any other artist.
- Assignment applies to the active `IntakeRequest`, not permanently to the whole lead.
- After assignment, future client messages for that intake route to the assigned artist's private Telegram chat.
- Assigned artist replies are sent automatically to the client through the original channel.
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
