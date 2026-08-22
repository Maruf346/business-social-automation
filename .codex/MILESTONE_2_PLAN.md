# Milestone 2 Plan

Last reviewed: 2026-08-22

## Milestone 2 Goal

Turn the partial intake foundation into a production-capable workflow system:

- Risk-based automatic intake.
- Telegram command center for Nina/Hoss.
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

Goal: persist the objects needed for command center and learning.

Proposed models:

- `ArtistProfile`: Nina, Hoss, Lana, others; channel IDs; active status; specialties.
- `IntakeRequest`: normalized intake state across WhatsApp/Outlook/vCita.
- `AIAnalysis`: AI extraction, missing info, risk, confidence, artist suggestion, pricing estimate, style tags.
- `HumanDecision`: approved/rejected/edited decision by Nina/Hoss.
- `Correction`: changed artist, changed price, changed risk, changed message, reason.
- `BusinessRule`: manually approved routing/pricing rules.
- `SimilarCaseEmbedding`: vector reference to past approved cases, likely PostgreSQL + pgvector.
- `OutboundAction`: pending/sent/failed client replies, booking confirmations, calendar actions.

Deliverable:

- Backend can store AI suggestion and final human decision separately.

## Phase 2 - Telegram Command Center

Goal: replace plain Telegram summary messages with an interactive workflow.

Telegram constraints:

- Telegram chat messages cannot contain normal HTML forms or input boxes.
- Telegram supports inline buttons, callback queries, commands, force-reply, and Telegram Web Apps.

Recommended UX:

- Send a structured HTML-formatted message with the intake summary.
- Attach inline buttons:
  - Approve Reply
  - Edit Reply
  - Assign Nina
  - Assign Hoss
  - Mark Unclear
  - Reject / Needs Human
  - Add Price
  - Add Note
- Use callback query endpoint to receive button clicks.
- For simple text corrections, use force-reply or command syntax.
- For richer editing, build a Telegram Web App later.

How the backend knows Nina/Hoss:

- Store Telegram user IDs mapped to internal `ArtistProfile` or `StaffProfile`.
- On every callback, validate `callback_query.from.id`.
- Only allow authorized users to approve/edit/reject.

Deliverable:

- High-risk requests appear in Telegram with buttons.
- Nina/Hoss can approve, reject, assign artist, or begin correction.
- Decisions are persisted.

## Phase 3 - Risk-Based Auto-Reply Engine

Goal: low-risk missing-info collection should proceed automatically; medium/high-risk messages require approval.

Risk examples:

- Low risk: simple FAQ, missing size/placement/reference image/date/color preference.
- Medium/high risk: pricing, final quote, booking confirmation, deposit request, cancellation, complaint, complex design advice, artist commitment, rejection, sensitive content.

Backend behavior:

- AI returns risk level and reason.
- Backend validates risk level against allowed states.
- Low-risk: save AI analysis, send draft to original channel, store outbound message.
- Medium/high-risk: send waiting message if needed, create Telegram review card, block final response until approval.

Deliverable:

- Automated missing-info collection for low-risk intake.
- Human gate for risky actions.

## Phase 4 - Controlled Feedback-Learning Layer

Goal: learn from decisions without silently changing business rules.

Backend should store:

- AI detection and suggestion.
- AI confidence and reason.
- Nina/Hoss final decision.
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

- Never auto-send price to client unless explicitly approved by Nina/Hoss.
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
2. Add tests and fixtures.
3. Add workflow/decision models.
4. Build Telegram callback handling and buttons.
5. Persist AI analysis and human decisions.
6. Implement low-risk auto-reply and high-risk approval states cleanly.
7. Add Postgres/pgvector learning retrieval.
8. Add pricing and image tags.
9. Add calendar and vCita.
10. Harden deployment.
