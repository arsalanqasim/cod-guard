# WhatsApp clarification

An unclear context-bound text reply stays in the order's reply history and
requests review. The current dispatch decision is preserved. The attempt
remains open for a clear whole-order text reply or a Confirm/Cancel button
until 24 hours from the original submission. A clarification does not
restart that timer or send an automated reply.

Check order detail for the thread and the review flag. The attempt's
`replied_at` is empty until an eligible explicit reply is applied. Duplicate
unclear callbacks are recorded once. STOP and operator-recorded withdrawal
close pending attempts immediately. Later consent cannot reopen a closed
attempt.

The exhibition remains simulated. See [Cloud setup and evidence limits](WHATSAPP_CLOUD.md)
for the provider configuration and opt-in requirements.
