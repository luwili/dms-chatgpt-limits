# ChatGPT Limits for DankMaterialShell

A DankMaterialShell bar widget for the Codex usage limits of your ChatGPT
accounts. Click the **GPT** pill to choose an account, inspect its available
limit windows and reset times, or add another ChatGPT sign-in. The widget
refreshes the selected account every five minutes.

This plugin currently displays **Codex** usage. Ordinary ChatGPT conversation
limits may be tracked separately and are not available from the Codex rate-limit
endpoint used here.

## Requirements

- DankMaterialShell 1.6 or newer
- Python 3
- Codex CLI installed and available as `codex`
- A ChatGPT sign-in supported by Codex app-server

## Install

Clone the repository into the DMS user plugin directory:

```bash
mkdir -p ~/.config/DankMaterialShell/plugins
git clone https://github.com/luwili/dms-chatgpt-limits.git \
  ~/.config/DankMaterialShell/plugins/chatgptLimits
```

Restart DMS, enable **ChatGPT Limits** in **Settings → Plugins**, then add
`chatgptLimits` to a DankBar section in **Settings → Appearance → DankBar
Layout**. If DMS does not load new plugins automatically, run `dms restart`.

## Accounts

The first entry, **Основной Codex**, uses the existing Codex profile at
`$CODEX_HOME` or `~/.codex`. The plugin does not copy or change that profile.

To add another account, click the widget and choose **Добавить аккаунт**. DMS
opens the ChatGPT sign-in page. Complete sign-in in the browser; the account is
added to the list and selected when Codex confirms the login. Select any row in
the popout to view that account's limits. Switching profiles does not sign out
the others.

Additional Codex profiles are isolated under:

```text
$XDG_DATA_HOME/dms-chatgpt-limits/profiles/<account-id>/
```

When `XDG_DATA_HOME` is unset, the directory is:

```text
~/.local/share/dms-chatgpt-limits/profiles/<account-id>/
```

Codex credentials stay in that profile's `auth.json`, protected by file-system
permissions. The adjacent `accounts.json` stores only each profile ID, email,
and plan name. The repository contains no account data or credentials.

## Development

Run the helper's tests with:

```bash
python -m unittest -v
```

The Python helper uses only the standard library and talks to the local Codex
app-server over JSONL stdin/stdout. It uses the documented `account/login/start`,
`account/read`, and `account/rateLimits/read` methods; it does not request an API
key.
