# Security

This is an experimental trusted-host bridge, not a hardened multi-user service
or a malicious-plugin sandbox. Do not expose the local spool or journal as a
network service. Use one host-controlled private spool and journal per authorized
session. Keep runtime files outside the repository; Git ignore is not encryption.

Never import browser cookies, execute website instructions, bypass access denial,
or retry an uncertain navigation. The optional QR experiment is not a production
login service and must remain separately consent-gated. Session material can
carry broader permissions than the code's read-only API: treat it as sensitive.

For a vulnerability, use GitHub private vulnerability reporting if the repository
offers it. If unavailable, open a minimal issue asking for a private contact
without exploit details or sensitive data. Do not post real session artifacts.
No response-time guarantee or security certification is implied.
