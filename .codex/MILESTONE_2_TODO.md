# Milestone 2 TODO

Last updated: 2026-09-06

This checklist tracks what is left after the current vCita, Telegram, Outlook, WhatsApp, AI, and Google Calendar work. Use this file as the working TODO list; update checkboxes as each item is completed and verified.

## Immediate Setup And Verification

- [ ] Deploy the latest backend image to AWS and run migrations, including `google_calendar.0001_initial`.
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
- [ ] Confirm all vCita services are mapped in the Admin panel with code, name, and service UID:
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
- [ ] Confirm Artist profiles have correct names, Telegram user IDs, Telegram chat IDs, vCita staff IDs where applicable, and Google Calendar mappings.
- [ ] Reconfirm whether Nina can approve requests. Current business rule has mainly treated Hoss as approver, but recent client wording mentions Hoss/Nina.

## Current Scheduling Flow

- [ ] Test `/schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM` from Telegram group.
- [ ] Verify command without service code returns a clear guidance message and does not silently use a fallback service.
- [ ] Confirm vCita availability check runs before booking.
- [ ] Confirm Google Calendar availability check runs before booking.
- [ ] Confirm vCita booking is created with the correct client, artist/staff, service, date, time, and request notes.
- [ ] Confirm Google Calendar event is created or updated after successful vCita booking.
- [ ] Confirm Telegram success message includes date, time, artist, service code/name, and vCita booking ID.
- [ ] Confirm rescheduling updates the existing vCita booking and existing Google Calendar event.
- [ ] Confirm Google conflict blocks booking before vCita is called.
- [ ] Confirm if vCita succeeds but Google sync fails, the booking remains and Telegram shows a clear warning.

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

- [ ] Add external artist offer states: offered, accepted, declined, expired.
- [ ] Send external artist a safe brief first, including tattoo idea and images but no phone number.
- [ ] Add accept/decline actions for external artists.
- [ ] Release client name and email only after the external artist accepts.
- [ ] Never release client phone number to external artists.
- [ ] Notify the client that the artist accepted and will contact them by email.
- [ ] Return declined or expired requests to Hoss/Nina for reassignment.
- [ ] Log every external artist contact-release decision.

## TA/TC External Artist Scheduling

- [ ] Confirm how TA/TC services should be represented in vCita for artists who are not vCita staff.
- [ ] Support scheduling TA/TC appointments for Lana, Sandra, and Sliva.
- [ ] Create the TA/TC appointment in the shared vCita agenda.
- [ ] Copy the confirmed appointment to the assigned external artist Google Calendar.
- [ ] Include correct artist, service, client name, client email, and request ID in both systems.
- [ ] Confirm both vCita and Google Calendar completion in Telegram.
- [ ] If vCita succeeds but Google Calendar fails, notify Hoss/Nina clearly.

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
- [ ] Create a short operator guide for `/whoami`, `/reply`, `/price`, `/logs`, `/hold`, `/keephold`, `/releasehold`, and `/schedule`.
- [ ] Create an error playbook for vCita failures, Google Calendar conflicts, Google sync failures, payment mismatch, WhatsApp setup issues, and Outlook renewal issues.
- [ ] Verify production secrets are not committed.
- [ ] Verify CI/CD deployment after the SCP-based pipeline change.
- [ ] Confirm EC2 deploy folder ownership allows GitHub Actions to upload deployment files.

## Final Demo Scenarios

- [ ] WhatsApp request to AI to Telegram review to approved client reply.
- [ ] Outlook request to AI to Telegram review to approved client reply.
- [ ] Hoss/Nina service booking through vCita.
- [ ] TA/TC booking for Lana/Sandra/Sliva with vCita plus Google Calendar copy.
- [ ] Pending hold to payment to final appointment to pending hold release.
- [ ] Payment paid webhook.
- [ ] Payment cancelled/refunded webhook.
- [ ] Google Calendar conflict prevention.
- [ ] External artist accept flow.
- [ ] External artist decline/no-response flow.
- [ ] Multiple active requests from the same client without data mixing.
- [ ] vCita failure message shown clearly in Telegram.
- [ ] Google Calendar failure message shown clearly in Telegram.
