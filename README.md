# ChatGPT Limits for DMS

This DMS bar plugin displays rate limits returned by the local Codex app-server
for the signed-in ChatGPT account. It refreshes every five minutes and also has
a manual refresh button in the popout.

The widget currently reports Codex limits. Limits for ordinary ChatGPT chat are
not exposed through this endpoint and may be tracked separately by ChatGPT.

The helper starts `codex app-server --stdio`, completes the local JSON-RPC
handshake, requests `account/rateLimits/read`, and exits. It does not read,
copy, or persist the Codex credentials.
