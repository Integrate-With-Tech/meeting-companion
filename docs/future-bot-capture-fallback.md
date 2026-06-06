# Future Visible Bot Capture Fallback

This document defines the product and audit requirements for a future visible bot/media capture fallback when native Teams transcription is unavailable.

## Product behavior

- Use `scheduled_bot_capture` only for meetings that have not happened yet.
- Use `capture_unavailable` for future meetings where bot/media capture fallback is not enabled or cannot be scheduled.
- Use `missing_source_artifact` for meetings that have already ended and have no transcript, recording, or uploaded source artifact.
- Do not schedule bot fallback for already-passed meetings.
- Captured media and user-uploaded audio/video must reuse the existing Whisper transcription pipeline before notes generation.

## Consent and recording visibility requirements

- The bot must be visible to all attendees before capture starts.
- The meeting UI must clearly indicate that recording/media capture is active.
- Capture must only begin after tenant-approved consent and policy checks pass.
- Tenants must be able to disable bot/media capture entirely.

## Audit requirements

- Record when fallback was scheduled, unavailable, started, stopped, or canceled.
- Record the actor, tenant, meeting identifier, and source transition for each fallback event.
- Record whether native Teams artifacts were missing when fallback scheduling was chosen.
- Record the media artifact identifier that was handed to Whisper once capture is implemented.

## Implementation note

- This issue only defines lifecycle states, UI messaging, and audit expectations.
- Media recording, bot orchestration, and consent enforcement remain separate implementation work.
