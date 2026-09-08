# Milestone 2 TODO

Last updated: 2026-09-08

This checklist tracks what is left after the current vCita, Telegram, Outlook, WhatsApp, AI, and Google Calendar work. Use this file as the working TODO list; update checkboxes as each item is completed and verified.
## Next Recommended Order

1. Deploy the latest backend image and run migrations, including `intake.0010` for external artist offers.
2. Verify Admin panel setup: active vCita account, vCita Matter-name field UID, mapped vCita services with correct schedule provider, artist Telegram IDs/chat IDs, vCita staff IDs for Hoss/Nina where needed, and Google Calendar mappings for external artists.
3. Test Telegram external artist offer flow end to end with one non-approver artist.
4. Test current scheduling flow with `/schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM` and Google Calendar conflict checks.
5. Test pending hold to payment webhook to final scheduling, after vCita webhook subscriptions are active.
6. Re-test Outlook email flow.
7. Finish WhatsApp only after the client completes Meta/WhatsApp Cloud API setup.

## Immediate Setup And Verification

- [ ] Deploy the latest backend image to AWS and run migrations, including `google_calendar.0001_initial`, pending-hold migrations, and `intake.0010` for external artist offers.
- [ ] Add the Google service account JSON on EC2 at `/opt/tattoo-hysteria-backend/secrets/google-service-account.json`.
- [ ] Confirm production env values:
  - [ ] `GOOGLE_SERVICE_ACCOUNT_FILE=/app/secrets/google-service-account.json`
  - [ ] `GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar`
- [ ] Add Google calendars in the Admin panel:
  - [ ] Pending Appointments calendar.
  - [ ] Lana calendar.
  - [ ] Sandra calendar.
  - [ ] Sliva calendar.
  - [ ] Shared vCita/Hoss/Nina calendar, if needed.
- [ ] Use the Admin panel action to test Google Calendar access for every configured calendar.
- [ ] Confirm all vCita services are mapped in the Admin panel with code, name, service UID, and the correct schedule provider:
  - [ ] `CH`
  - [ ] `CN`
  - [ ] `OCH`
  - [ ] `OCN`
  - [ ] `RH`
  - [ ] `RN`
  - [ ] `ORH`
  - [ ] `ORN`
  - [ ] `TH`
  - [ ] `TN`
  - [ ] `TA`
  - [ ] `TC`
- [ ] Confirm vCita Matter-name field UID is stored on the active vCita account for payment-dependent pending holds.
- [ ] Confirm TA/TC service rows are set to Google Calendar only; no neutral vCita staff UID is needed for TA/TC.
- [ ] Confirm TA/TC `VcitaService` rows have `schedule_provider=Google Calendar only`.
- [ ] Confirm Artist profiles have correct names, Telegram user IDs, Telegram chat IDs, `can_approve` values, vCita staff IDs where applicable, and Google Calendar mappings.
- [ ] Reconfirm whether Nina can approve requests. Current backend supports any active artist with `can_approve=True`; business policy still needs final confirmation.
- [ ] Test assigning a non-approver artist sends a private offer card with `Accept` and `Decline`.
- [ ] Test accepted external artist offer assigns the intake, hides buttons, releases only client name/email, notifies group/client/artist, and cancels competing offers.
- [ ] Test declined external artist offer hides buttons, notifies group/artist, and leaves the intake available for reassignment.
- [x] Make review-card draft replies copy-friendly with a preformatted Telegram block.
- [x] Remove AI-decision buttons from the original review card after Approve/Edit/Reject while keeping assignment controls independent.
- [x] Hide assignment buttons once an intake is assigned or has an active external artist offer.
- [x] Hide Schedule buttons from newly generated review cards; scheduling now uses explicit `/hold` or `/schedule` commands.
- [x] Add `/reassign REQUEST_ID` to send a short artist-selection card and clear that card after selection.

## Current Scheduling Flow

- [ ] Test `/schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM` from Telegram group.
- [ ] Verify command without service code returns a clear guidance message and does not silently use a fallback service.
- [ ] Confirm vCita availability check runs before booking.
- [ ] Confirm Google Calendar availability check runs before booking.
- [ ] Confirm Hoss/Nina services create vCita bookings with the correct client, artist/staff, service, date, time, and request notes.
- [ ] Confirm Hoss/Nina services create/update Google Calendar events after successful vCita booking.
- [ ] Confirm Telegram success message includes date, time, artist, service code/name, and the correct provider details: vCita booking ID for vCita services, Google event ID for Google-only services.
- [ ] Confirm rescheduling updates the existing vCita booking for Hoss/Nina services and the existing Google Calendar event for all scheduled services.
- [ ] Confirm Google conflict blocks booking before vCita is called.
- [ ] Confirm if vCita succeeds but Google sync fails for Hoss/Nina services, the booking remains and Telegram shows a clear warning.

## Pending Appointment Flow

- [x] Add a clear pending-hold command or button, for example `/hold REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM`.
- [x] Create a temporary block in the Pending Appointments Google Calendar before payment.
- [x] Store pending hold event ID, expiry date, selected service, artist, and request mapping.
- [x] Keep pending hold active while payment is outstanding.
- [x] Release pending hold only after the final vCita appointment and confirmed Google Calendar sync are successful.
- [x] If final vCita booking fails, keep the pending hold and alert Hoss/Nina.
- [x] Add one-week pending expiry handling through Celery Beat + `notify_pending_holds`.
- [x] Notify Hoss/Nina with a Telegram review card when a pending hold reaches the review deadline.
- [x] Add Keep Hold/Release Hold review-card buttons plus `/keephold REQUEST_ID` and `/releasehold REQUEST_ID` fallbacks.

## Payments And vCita Webhooks

- [ ] Subscribe production vCita webhooks for:
  - [ ] `appointment/scheduled`
  - [ ] `appointment/rescheduled`
  - [ ] `appointment/cancelled`
  - [ ] `payment/paid`
  - [ ] `payment/recorded`
  - [ ] `payment/updated`
  - [ ] `payment/cancelled`
  - [ ] `payment/refunded`
  - [ ] `deposit/created`
  - [ ] `invoice/issued`
  - [ ] `invoice/updated`
- [ ] Store vCita invoice, deposit, payment, and booking IDs against the correct intake/request.
- [x] Match payment webhook payloads back to the correct request when the payload contains a request ID, stored payment reference, or one unique vCita client match.
- [ ] Prevent duplicate final appointments if vCita sends repeated or delayed webhook events.
- [ ] Add a reconciliation flow for missed payment webhooks.
- [x] Notify Telegram group when payment is paid, cancelled, refunded, or cannot be matched.
- [x] Trigger final appointment creation after payment when one matching pending hold exists.

## External Artist Flow

- [x] Add external artist offer states: offered, accepted, declined, cancelled.
- [x] Send external artist a safe brief first, including tattoo idea and reference links when available, but no client phone/email.
- [x] Add `Accept`/`Decline` button actions for external artists.
- [x] Release client name and email only after the external artist accepts.
- [x] Never release client phone number to external artists.
- [x] Notify the client that the artist accepted and will contact them by email.
- [x] Return declined requests to Hoss/Nina for reassignment through group notification.
- [ ] Add optional no-response/expiry handling for artist offers if Hoss wants a timeout later.
- [x] Log every external artist offer, accept, decline, and contact-release decision.

## TA/TC External Artist Scheduling

- [x] Final rule confirmed: TA/TC appointments for Lana, Sandra, and Sliva do not create vCita bookings.
- [x] Support scheduling TA/TC appointments for external artists without requiring their own vCita staff UID.
- [x] Route TA/TC/external artist schedules to the assigned artist Google Calendar only.
- [x] Prevent external artists from being scheduled with non-external service codes and show a clear Telegram error.
- [x] Prevent Hoss/Nina/internal artists from being scheduled with Google-only TA/TC service codes and show a clear Telegram error.
- [x] Prevent `/hold` for external artists or Google-only services because holds are only for Hoss/Nina vCita/payment-backed bookings.
- [x] Include correct artist, service, client/contact context where available, and request ID in Google Calendar sync records.
- [ ] Confirm Google Calendar-only completion in Telegram during final testing.
- [ ] Confirm Google Calendar conflicts block TA/TC scheduling before any schedule state is saved.

## WhatsApp

- [ ] Complete client-side Meta/WhatsApp Cloud API setup.
- [ ] Confirm the WhatsApp phone number is Cloud API or coexistence capable.
- [ ] Confirm the phone number is registered and subscribed to the Meta app.
- [ ] Verify inbound WhatsApp messages reach `/api/v1/webhook/meta/`.
- [ ] Test WhatsApp request to AI to Telegram review flow.
- [ ] Test approved AI reply back to WhatsApp client.
- [ ] Test Hoss/artist Telegram reply back to WhatsApp client.
- [ ] Test WhatsApp media handling.

## Outlook

- [ ] Re-test Outlook subscription creation after the latest deploy.
- [ ] Confirm Outlook webhook renewal still works.
- [ ] Test inbound email to AI to Telegram review flow.
- [ ] Test approved AI reply back to the email thread.
- [ ] Test Hoss/artist Telegram reply back to the email thread.
- [ ] Confirm self-sent Outlook replies are ignored.
- [ ] Test multiple active email threads from the same client without request mixing.
- [ ] Confirm attachments are stored and passed to AI/client flows correctly.

## AI And Backend Contract

- [ ] Confirm AI sends `date` as `YYYY-MM-DD`.
- [ ] Confirm AI sends `time` as `HH:MM`.
- [ ] Confirm AI sends `summary` in a Telegram-friendly length and format.
- [ ] Confirm AI low-risk missing-info conversations can continue automatically when cold-start mode is not intended to force manual review.
- [ ] Confirm high-risk behavior intentionally triggers Telegram summary/card.
- [ ] Decide whether AI should return a service code, appointment type, or only date/time.
- [ ] Keep backend fallback behavior clear when AI does not return a service code.
- [ ] Separate long AI reasoning from staff-facing summary if Telegram cards become too noisy.

## Admin And Operations

- [ ] Add or refine Admin panel filters/search for vCita webhook payloads.
- [ ] Add or refine Admin panel filters/search for Google Calendar events.
- [ ] Create a short operator guide for `/whoami`, `/reply`, `/price`, `/logs`, `/hold`, `/keephold`, `/releasehold`, `/schedule`, and external artist `Accept`/`Decline` buttons.
- [ ] Create an error playbook for vCita failures, Google Calendar conflicts, Google sync failures, payment mismatch, WhatsApp setup issues, and Outlook renewal issues.
- [ ] Verify production secrets are not committed.
- [ ] Verify CI/CD deployment after the SCP-based pipeline change.
- [ ] Confirm EC2 deploy folder ownership allows GitHub Actions to upload deployment files.

## Final Demo Scenarios

- [ ] WhatsApp request to AI to Telegram review to approved client reply.
- [ ] Outlook request to AI to Telegram review to approved client reply.
- [ ] Hoss/Nina service booking through vCita.
- [ ] TA/TC booking for Lana/Sandra/Sliva with Google Calendar only.
- [ ] Pending hold to payment to final appointment to pending hold release.
- [ ] Payment paid webhook.
- [ ] Payment cancelled/refunded webhook.
- [ ] Google Calendar conflict prevention.
- [ ] External artist accept flow after AWS deploy/migrate.
- [ ] External artist decline flow after AWS deploy/migrate.
- [ ] Optional external artist no-response/expiry flow, if Hoss wants timeout automation later.
- [ ] Multiple active requests from the same client without data mixing.
- [ ] vCita failure message shown clearly in Telegram.
- [ ] Google Calendar failure message shown clearly in Telegram.
