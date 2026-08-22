# AI Integration Contract

Last reviewed: 2026-08-22

## Ownership Boundary

The AI service is owned by the assigned AI engineer in a separate repository and will be deployed separately, likely on AWS.

This Django backend owns:

- Building the AI request payload from canonical backend state.
- Calling the deployed AI endpoints.
- Validating and normalizing AI responses.
- Persisting the updated structured intake fields returned by AI.
- Sending low-risk replies through the original channel.
- Routing high-risk requests into Telegram for Nina/Hoss review.

This backend does not own:

- AI extraction algorithms.
- Prompting/model orchestration inside the AI service.
- Vision analysis implementation.

## Core State Rule

The backend database must be the canonical source of intake state.

Every message cycle should follow this loop:

1. Receive client message from WhatsApp or Outlook.
2. Save incoming message and any media.
3. Load the current local intake state from DB.
4. Send that state to AI as `existing_db_state`.
5. Receive AI response with updated structured fields.
6. Persist AI response fields back to DB.
7. Use `missing_information` and `risk_level` to decide the next action.
8. On the next client message, send the updated DB state again.

This matters because AI can only ask relevant missing-info questions if the backend sends the latest known state each time.

## Analysis Endpoint

Method:

```text
POST /api/v1/inquiries/analyze
```

Purpose:

Analyze a tattoo inquiry and return updated extracted fields, missing information, risk level, and a draft reply.

Request payload:

```json
{
  "current_message": "string",
  "new_image_urls": [
    "string"
  ],
  "existing_db_state": {
    "additionalProp1": {}
  },
  "recent_chat_history": [
    {
      "role": "user",
      "content": "string"
    }
  ]
}
```

Successful response:

```json
{
  "tattoo_idea": "string",
  "style_tags": [
    "fine-line"
  ],
  "placement": "string",
  "size_estimate_cm": "string",
  "color_preference": "string",
  "suggested_artist": "Nina",
  "confidence_level": "high",
  "ai_reasoning": "string",
  "missing_information": [
    "size in cm"
  ],
  "risk_level": "low",
  "draft_reply": "string"
}
```

Known error responses:

- `400`: inquiry cannot be processed.
- `422`: validation error.
- `502`: upstream AI pipeline failed.
- `503`: AI service is not configured.

## Telegram Summary Endpoint

Method:

```text
POST /api/v1/inquiries/telegram-summary
```

Purpose:

Create staff-facing summary text for a high-risk inquiry. The AI service returns text only; this backend sends it to Telegram.

Request payload:

```json
{
  "current_message": "",
  "new_image_urls": [
    "string"
  ],
  "existing_db_state": {
    "additionalProp1": {}
  },
  "recent_chat_history": [
    {
      "role": "user",
      "content": "string"
    }
  ]
}
```

Successful response:

```json
{
  "risk_level": "high",
  "summary": "string",
  "draft_reply": "string",
  "telegram_message": "string"
}
```

Known error responses:

- `400`: inquiry cannot be processed.
- `409`: inquiry is not high risk.
- `422`: validation error.
- `502`: upstream AI pipeline failed.
- `503`: AI service is not configured.

## Backend Persistence Requirements

The backend should persist each AI analysis response, not just use it transiently.

Minimum state to persist per intake/request:

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
- `draft_reply`
- raw AI response payload
- source message that caused the analysis

Recommended design:

- Store canonical latest intake fields on `IntakeRequest`.
- Store every AI response snapshot in `AIAnalysis`.
- Link each `AIAnalysis` to the triggering `Message`.
- Use latest `IntakeRequest` fields to build `existing_db_state`.

## Risk-Level Behavior

### Low Risk

If `risk_level == "low"`:

- Persist AI structured fields.
- Save/send `draft_reply` to the client through the original channel.
- Continue the conversation with AI.
- On the next message, include the updated DB state in `existing_db_state`.

Typical low-risk cases:

- Simple FAQ.
- Basic missing-info collection.
- Asking for size, placement, reference image, color preference, preferred month/date.

### High Risk

If `risk_level == "high"`:

- Persist AI structured fields.
- Send a waiting/holding response to the client if appropriate.
- Call `/api/v1/inquiries/telegram-summary`.
- Send staff summary/card to Telegram.
- Stop automatic client-facing replies until Nina/Hoss approve the next action.

Typical high-risk cases:

- Pricing.
- Final quote.
- Booking confirmation.
- Deposit request.
- Cancellation or rescheduling.
- Complaint.
- Complex design advice.
- Artist commitment.
- Polite rejection.
- Sensitive/unusual messages.

## Existing DB State Shape

The exact shape can evolve, but it should be stable and explicit.

Recommended `existing_db_state`:

```json
{
  "lead": {
    "id": 123,
    "name": "Client Name",
    "phone_number": "string",
    "email": "string",
    "source": "whatsapp"
  },
  "intake": {
    "id": 456,
    "tattoo_idea": "string",
    "style_tags": ["fine-line"],
    "placement": "string",
    "size_estimate_cm": "string",
    "color_preference": "string",
    "suggested_artist": "Nina",
    "confidence_level": "high",
    "missing_information": ["size in cm"],
    "risk_level": "low",
    "status": "collecting_info"
  },
  "latest_ai_analysis": {
    "id": 789,
    "ai_reasoning": "string",
    "draft_reply": "string"
  }
}
```

Important:

- Do not rely only on chat history for known fields.
- Do not let AI be the only memory of missing fields.
- Use DB state as the source of truth for what is known and what is still missing.

## Validation Rules

Backend should tolerate partial AI responses but should validate critical fields:

- `draft_reply` is required for low-risk auto-reply.
- `risk_level` must be recognized. Unknown values should default to human review, not auto-send.
- `missing_information` should be stored as a list.
- `style_tags` should be stored as a list.
- `suggested_artist` should eventually be normalized against known artists.
- Raw response should be stored for debugging even if normalization partially fails.

## Implementation Notes

- `IntakeRequest` and `AIAnalysis` live in the dedicated `intake` app.
- WhatsApp and Outlook task flows now create/load an active intake, send its state as `existing_db_state`, and persist AI response fields before risk routing.
- Unknown or unsupported `risk_level` values normalize to `unknown`, which routes toward human review instead of auto-send.

## Open Implementation Questions

- Should each lead have one active intake at a time or multiple parallel requests?
- Should high-risk `draft_reply` be stored as a proposed reply for approval?
- Should `confidence_level` be enum-only (`low`, `medium`, `high`) or free text?
- How should image-derived style tags be updated if later AI responses change them?
