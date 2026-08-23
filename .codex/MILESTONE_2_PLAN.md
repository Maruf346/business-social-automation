# Milestone 2 Plan

Last reviewed: 2026-08-23

## Milestone 2 Goal

Turn the partial intake foundation into a production-capable workflow system:

- Risk-based automatic intake.
- Telegram command center for Hoss approval and assigned-artist inboxes.
- Human approval and correction workflow.
- Controlled feedback-learning memory.
- Reference-image style analysis through the external AI service.
- Internal pricing suggestions.
- Calendar and vCita workflow.
- Production database, deployment, testing, and monitoring.

## Architecture Decision

Current repo is Django/DRF/Celery. Milestone 2 notes mention FastAPI/LangChain/LangGraph/PostgreSQL/AWS, but this repo is already a Django backend.

Recommendation: continue with Django unless a rewrite is explicitly approved. A rewrite would add cost and risk without being necessary for the listed backend workflows.

The AI service is a separate project owned by an AI engineer. This backend will consume the AI service through AWS-hosted endpoints.

## Phase 0 - Stabilize Handover Foundation

Goal: make the current code reliable enough to build on.

Completed on 2026-08-22:

- Enabled Outlook webhook processing by calling the orchestrator from the Outlook webhook view.
- Added Outlook POST validation-token handling for Microsoft Graph webhook validation.
- Moved AI summary URL into settings/env as `AI_SUMMARY_API_URL`.
- Moved Telegram review chat ID into settings/env as `TELEGRAM_REVIEW_CHAT_ID`.
- Added `core.signals` registration through `CoreConfig`.
- Added `gunicorn` to `requirements.txt` for the existing Docker command.
- Made Celery eager mode configurable through env variables.
- Updated README docs URLs.

Deferred by current project direction:

- Tests and sample fixtures were not added in this pass because the current maintainer asked to skip test work for now. Previous testing history exists only on the previous developer's local machine.

Deliverable:

- Backend foundation is cleaner and less hardcoded. Live demonstration still requires channel credentials, account records, and external AI endpoint availability.

## Phase 1 - Data Model for Workflow and Decisions

Goal: persist the objects needed for AI state continuity, command center, and learning.

Implemented on 2026-08-22:

- `IntakeRequest`: canonical latest tattoo-intake state across WhatsApp/Outlook/vCita.
- `AIAnalysis`: every AI response snapshot, linked to the triggering message and intake request.
- `IntakeStateService`: builds `existing_db_state`, normalizes AI responses, updates canonical intake state, and stores AI snapshots.
- WhatsApp and Outlook AI task flows now send DB state to AI and persist AI response fields before risk routing.

Still planned:

- `ArtistProfile`: Nina, Hoss, Lana, others; channel IDs; active status; specialties. Implemented 2026-08-22.
- `HumanDecision`: approved/rejected/edited decision by Hoss or assigned artist action. Implemented 2026-08-22.
- `Correction`: changed artist, changed price, changed risk, changed message, reason.
- `BusinessRule`: manually approved routing/pricing rules.
- `SimilarCaseEmbedding`: vector reference to past approved cases, likely PostgreSQL + pgvector.
- `OutboundAction`: pending/sent/failed client replies, booking confirmations, calendar actions.

Deliverable:

- Backend can build `existing_db_state` from its database, call AI, persist updated AI fields, and send the updated DB state again on the next message.

Completed Phase 1 implementation items:

1. Add `IntakeRequest` with fields matching AI response: tattoo idea, style tags, placement, size estimate, color preference, suggested artist, confidence, missing information, risk level, status.
2. Add `AIAnalysis` to store raw and normalized AI responses per message.
3. Add service methods to build `existing_db_state` from `Lead`, active `IntakeRequest`, and latest `AIAnalysis`.
4. Add service methods to apply AI response fields back onto `IntakeRequest`.
5. Update WhatsApp and Outlook task flows to use the DB state builder before calling AI.
6. Update low-risk flow to persist AI state before sending the draft reply.
7. Update high-risk flow to persist AI state before creating Telegram summary.

## Phase 2 - Telegram Command Center

Goal: replace plain Telegram summary messages with an interactive workflow.

Telegram constraints:

- Telegram chat messages cannot contain normal HTML forms or input boxes.
- Telegram supports inline buttons, callback queries, commands, force-reply, and Telegram Web Apps.

Recommended UX:

- Send a structured HTML-formatted message with the intake summary.
- Attach inline buttons:
  - Approve Reply
  - Reject
  - Edit Reply
  - Assign dynamic artist buttons from active DB records
  - Mark Unclear
  - Add Price
  - Add Note
- Use callback query endpoint to receive button clicks.
- For simple text corrections, Hoss clicks Edit Reply and then sends `/reply REQUEST_ID message text` in the shared group.
- For richer editing, build a Telegram Web App later.

Locked workflow decisions:

- High-risk requests go to one shared Telegram group first.
- Only Hoss can approve/reject/assign from the shared group.
- Hoss is also assignable as an artist; if he assigns himself, the bot sends future updates to his private Telegram inbox.
- Active artists are managed in Django admin. New active artists should appear as assignment options without code changes.
- Assignment applies only to the active `IntakeRequest`, not the lead forever.
- Hoss approving the AI draft reply immediately sends that draft to the client through the original source channel.
- Hoss can choose Edit Reply instead of approving the AI draft; the edited reply is then sent through group command `/reply REQUEST_ID message text`.
- If Hoss approves without assigning an artist, the intake remains unassigned and future high-risk messages return to the shared group.
- After an artist is assigned, future client messages for that intake are routed to the assigned artist's private Telegram chat.
- Assigned artist replies are sent automatically to the client, without another Hoss approval step.
- Artist replies should support text plus images/files.

How the backend identifies Telegram users:

- Store Telegram numeric user IDs mapped to `ArtistProfile`.
- Store each artist's private Telegram chat ID after they start the bot or run `/whoami`.
- On every group callback, verify `callback_query.from.id` belongs to Hoss.
- On every private artist reply, verify `message.from.id` belongs to the assigned artist.

Multi-intake reply routing:

- The bot sends private artist messages per assigned intake/update.
- The artist normally replies directly to the bot's request/update message.
- Backend maps `telegram_chat_id + reply_to_message.message_id` to the target `IntakeRequest`.
- Assigned artist fallback command: `/reply REQUEST_ID message text`.
- Hoss-only group edit command for unassigned intakes: `/reply REQUEST_ID message text`.
- Standalone private messages without a known reply target should be rejected with instructions.

Deliverable:

- High-risk requests appear in the shared Telegram group with Hoss-only action buttons.
- Hoss can approve, edit, reject, or assign a dynamic artist.
- Assigned artists receive private Telegram updates and can reply to clients.
- Decisions are persisted.

Implemented on 2026-08-22:

- Added `ArtistProfile`, `HumanDecision`, and `TelegramMessageLink`.
- Added admin management for artists, decisions, and message links.
- Added dynamic inline assignment buttons generated from active artists.
- Added Hoss-only callback authorization through `ArtistProfile.can_approve`.
- Added `/whoami` handling to capture Telegram user/chat IDs.
- Added approval callback that sends the latest AI draft reply to the client.
- Added reject/Edit Reply/assign callbacks.
- Added private artist reply handling by reply-to message mapping.
- Added `/reply REQUEST_ID ...` fallback for assigned artists and Hoss-only group edited replies.
- Added assigned-intake routing so future WhatsApp/Outlook client messages go to the assigned artist instead of AI.
- Added text/photo/document artist reply support. Outlook media currently sends as links; WhatsApp media sends via Meta media links.

Still needs live verification:

- Real Telegram bot webhook delivery.
- Real Hoss and artist Telegram user IDs.
- Real WhatsApp media link delivery from Telegram-downloaded files.
- Real Outlook reply behavior with media links.

## Phase 3 - Risk-Based Auto-Reply Engine

Goal: low-risk missing-info collection should proceed automatically; medium/high-risk messages require approval.

Risk examples:

- Low risk: simple FAQ, missing size/placement/reference image/date/color preference.
- Medium/high risk: pricing, final quote, booking confirmation, deposit request, cancellation, complaint, complex design advice, artist commitment, rejection, sensitive content.

Backend behavior:

- AI returns risk level and reason.
- Backend validates risk level against allowed states. Unknown values should default to human review.
- Low-risk: save AI analysis, update `IntakeRequest`, send draft to original channel, store outbound message.
- Medium/high-risk: save AI analysis, update `IntakeRequest`, send waiting message if needed, create Telegram review card, block final response until approval.

Deliverable:

- Automated missing-info collection for low-risk intake.
- Human gate for risky actions.

## Phase 4 - Controlled Feedback-Learning Layer

Goal: learn from decisions without silently changing business rules.

Backend should store:

- AI detection and suggestion.
- AI confidence and reason.
- Hoss final decision and assigned artist actions.
- Corrections and optional correction reason.
- Final artist assigned.
- Approved price or price range.
- Final outcome.
- Related request text and image style tags.

Learning approach:

- PostgreSQL stores canonical records.
- pgvector stores embeddings for semantic similarity search.
- Backend retrieves similar approved cases and sends them as context to the AI endpoint.
- Repeated correction patterns become suggested business rules.
- Suggested rules require manual approval before affecting automation.

Deliverable:

- Past approved decisions improve future AI context without uncontrolled self-modifying behavior.

## Phase 5 - Reference Image Analysis

Goal: clients can send images without knowing style names.

Backend responsibility:

- Download and expose media URLs securely.
- Send image URLs to the AI service.
- Store returned style tags and findings.

AI responsibility:

- Analyze image content.
- Return searchable tags such as fine-line, watercolor, minimal, floral, micro-realism, black and grey, calligraphy.

Deliverable:

- Intake requests have searchable image-derived style tags.

## Phase 6 - Internal Pricing Suggestions

Goal: provide internal-only estimates that humans must approve before clients see them.

Inputs:

- Style.
- Size.
- Placement.
- Detail level.
- Artist.
- Complexity.
- Historical approved decisions.
- Manual business rules.

Rules:

- Never auto-send price to client unless explicitly approved by Hoss.
- Store price estimate and confidence as internal fields.
- Log final approved price/range separately.

Deliverable:

- Telegram card shows internal price estimate.
- Approved final price is stored for future learning.

## Phase 7 - Calendar and vCita

Google Calendar:

- Store artist calendar identities.
- Check availability before booking confirmation.
- Prevent double booking.
- Create/update calendar events after approval.

vCita:

- First produce or recover feasibility report.
- Test reading booking requests.
- Test reference image access.
- Test creating/updating client profiles.
- Test adding notes.
- Test creating appointments.
- Test payment/deposit status detection.
- Document unsupported capabilities and safest alternatives.

Deliverable:

- Booking workflow integrates with the chosen calendar/vCita path.

## Phase 8 - Production Hardening

Tasks:

- Move to PostgreSQL.
- Add pgvector if learning layer is implemented.
- Configure real Celery worker/queue instead of eager tasks.
- Secure env and secrets.
- Add CI checks.
- Add structured logging.
- Add retry/dead-letter strategy for outbound messages.
- Add admin/debug views for failed webhooks.
- Deploy on AWS or agreed hosting.
- Ensure 24/7 webhook uptime.

Deliverable:

- Production deployment with monitoring and recovery path.

## Suggested Build Order

1. Stabilize existing webhooks and env config.
2. Add AI state models and persistence. Done 2026-08-22.
3. Build `existing_db_state` payload generation from DB. Done 2026-08-22.
4. Update WhatsApp/Outlook AI calls to persist AI response fields. Done 2026-08-22.
5. Build Telegram callback handling and buttons.
6. Persist human decisions. Done 2026-08-22.
7. Implement approved outbound reply flow for high-risk requests. Done 2026-08-22.
8. Add Postgres/pgvector learning retrieval.
9. Add pricing and richer image tags.
10. Add calendar and vCita.
11. Harden deployment.
