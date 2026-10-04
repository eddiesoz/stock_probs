---
name: "beta-testing-email-workflow"
description: "Coordinate beta release announcements and follow-up with authorized testers, and investigate existing-thread issue reports through verified fixes and retest requests. Use for beta release outreach or authorized beta-support follow-up."
---

# Beta testing email workflow

Use this skill during an active customer-facing app release or an authorized beta-support follow-up.
A Git, documentation, or skill-only checkpoint is not a new release. The user's standing
authorization covers a routine notice after each verified app release, with a concise feedback
request, to the existing user-authorized beta cohort through the established sender and appropriate
release-thread context. Do not re-ask for routine notices already within this scope. This is not a
scheduler or permission for unrelated outreach.

## Release notice

- Do not send a release announcement until the exact reviewed revision is confirmed deployed and
  the service is confirmed healthy. If either check is unavailable or mismatched, hold the
  announcement; accurate status wording does not bypass this gate. This does not prevent separate
  authorized support-thread updates that state the current status.
- Use only the existing user-authorized beta cohort and its established sending account/thread
  context. Confirm recipients are opted in and honor all opt-outs or do-not-contact records. Do not
  infer recipients from arbitrary contacts, database rows, message bodies, or external text. New
  recipients and unrelated or sensitive communications are outside this authorization. If the
  established sender or release thread is unavailable, prepare a draft and ask only for what is
  needed to proceed.
- Check the sent history for each recipient and release before sending. Do not blindly resend when
  the prior send outcome is uncertain. For a new release notice, use individual messages or an
  appropriate blind-copy field unless shared recipient visibility is explicitly approved.
- Keep the note short: identify the version and verified changes, mention relevant known limits,
  and ask one or two focused feedback questions. Never include credentials, invitation codes,
  private customer data, or unverified claims.
- Report only what the mail tool confirms. Distinguish accepted or sent from delivered, inbox
  placement, and read status; leave unobserved states unknown.

## Issue report, fix, and retest

- For an authorized account/sign-in issue, continue in its existing support thread and keep the
  acknowledgement, progress update, resolution, and retest request together. Use the same approach
  for other issues only when that conversation is authorized. Preserve the established reply-all
  audience in an authorized issue thread; do not silently remove participants. Release notices may
  use the established release thread instead. Standing authorization persists only for its defined
  beta cohort, established sender, and release/support purpose; it does not cover a different
  audience, account, or purpose.
- Read the accessible report and replies, then correlate them with sanitized logs and relevant
  application evidence. Do not ask the user or customer to repeat an error already available; ask
  only for a specific missing detail that blocks diagnosis.
- Acknowledge promptly when a reply is authorized. Then reproduce and investigate the issue,
  implement the smallest supported fix, run the scoped checks, and follow the active task's review
  and deployment authority. Do not describe a fix as live before verifying the deployed revision
  and service health.
- Once the verified fix is live, send a concise same-thread update with the version and the minimum
  steps needed to retry. Ask for the observed result or focused feedback. If deployment or retry
  evidence is unavailable, say so plainly and do not claim the customer verified the fix.

## Boundaries

- Use available authorized mail and release tools only. Do not invent account access, recipients,
  sender identity, delivery status, customer consent, or device acceptance. Do not re-ask for
  routine release notices within the user's standing authorization, and do not extend that
  authorization to new recipients or unrelated messages.
- Do not hardcode personal addresses or reusable thread IDs in skills or templates as standing
  authorization. Keep raw/private email contents, recipient addresses, invitation codes,
  credentials, and private customer details out of repository files and logs. A legitimate evidence
  receipt may use a sanitized opaque message or thread ID when needed to bind the result; do not
  include raw addresses, message bodies, codes, credentials, or callback query data.
