# Multi-account Codex limits in DMS

## Intent and goals

Let the user add multiple ChatGPT accounts to the DMS bar widget and select which account's Codex usage limits are shown. Keep the existing `~/.codex` account available as the default; an account switch changes the selected profile without logging out another profile.

## Approaches

- Reuse the one global Codex login and switch accounts by logging out/in: simplest, but it cannot keep accounts available simultaneously.
- Give each additional account a separate Codex profile (`CODEX_HOME`) and select among those profiles: selected because it preserves independent logins while retaining the existing global account as the default.
- Implement OAuth token storage directly in the plugin: rejected because Codex app-server already owns the supported ChatGPT login and credential lifecycle.

## Design

The Python helper will manage a private data directory under `$XDG_DATA_HOME/dms-chatgpt-limits` (or `~/.local/share/dms-chatgpt-limits`), with one `CODEX_HOME` directory per added profile. The existing global profile is represented by the reserved ID `default` and is never copied. The helper will expose account listing, limit lookup, and browser-based ChatGPT login through local `codex app-server` JSON-RPC. The UI will show an account selector at the top of the popout, an add-account action, and the selected account's limits; the bar pill will identify the selection and show its remaining primary limit.

## Constraints and non-goals

- Use only the existing ChatGPT-managed Codex authentication; do not request or store API keys.
- Never include account metadata, tokens, or Codex profile files in the GitHub repository.
- Ordinary ChatGPT chat limits are outside the app-server rate-limit endpoint; this widget reports Codex buckets.
- Use the already-installed DMS/QML, Python 3, and Codex CLI; add no runtime dependencies.
