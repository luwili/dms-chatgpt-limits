# Multi-account Codex limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently authenticated Codex profiles to the DMS limits widget and publish the standalone plugin repository.

**Architecture:** A Python helper owns private profile directories and app-server JSON-RPC. The QML bar widget lists accounts, initiates ChatGPT login in an isolated profile, remembers the selected ID, and fetches limits only for that profile.

**Tech Stack:** QML/Quickshell, Python 3 standard library, Codex app-server, Git/GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-11-11-multi-account-design.md`

## Global Constraints

- Keep the existing account as reserved profile ID `default`; do not copy or move its credentials.
- Create each additional profile with a private `CODEX_HOME` under `$XDG_DATA_HOME/dms-chatgpt-limits` or `~/.local/share/dms-chatgpt-limits`.
- Use the ChatGPT managed login and rate-limit methods exposed by the local Codex app-server.
- Keep all authentication data and per-user settings out of the repository.
- Keep the plugin compatible with the installed DMS QML APIs and Python 3 standard library only.

## Review Focus

- Missing global Codex login still leaves the default account selectable and reports a useful status.
- Malformed or path-traversing profile IDs never access outside the profile directory.
- Cancelled or failed OAuth login does not register a profile as usable.
- A stale saved selection falls back to the default profile.
- App-server notifications may precede JSON-RPC responses and must not break login or rate-limit parsing.

---

### Task 1: Isolated account profiles and app-server operations

**Files:**
- Modify: `fetch_limits.py`
- Test: `tests/test_fetch_limits.py`

**Interfaces:**
- `list_accounts() -> dict` returns the default profile plus registered additional profiles, with display identity and login state.
- `fetch_limits(account_id: str) -> dict` reads limits using that profile's `CODEX_HOME`.
- `begin_login() -> None` starts a new profile, emits a browser login URL event, and emits a completion event only after authenticated account details are read and persisted.
- CLI forms are `list`, `limits ACCOUNT_ID`, and `login`.

- [x] Write unit tests for the default profile, isolated profile path permissions, ID validation, stale state, RPC notification handling, and profile persistence after successful login only.
- [x] Run `python -m unittest -v` and confirm the new tests fail for the missing behavior.
- [x] Implement storage and app-server operations with filesystem permissions `0700` for profile directories and `0600` for account metadata.
- [x] Run `python -m unittest -v`; all 10 profile and protocol tests pass. Live `list` and `limits default` commands both returned `ok`.
- [x] Commit as `feat: support isolated Codex account profiles`.

### Task 2: Account selector and add-account flow

**Files:**
- Modify: `ChatGPTLimits.qml`

**Interfaces:**
- The widget remembers `selectedAccountId` using `pluginService.savePluginData("chatgptLimits", "selectedAccount", id)`.
- The popout lists account profiles and selects one; selection launches `limits ACCOUNT_ID` and never alters another profile.
- The add-account button launches `login`, opens each emitted browser URL, displays progress, and refreshes the account list after success.

- [x] Validate the widget through the running DMS shell; the first load exposed an unresolved Process id, which was corrected after inspecting the QML warning.
- [x] Implement the selector, add-account state, and selected-account bar label.
- [x] Run all Python checks and reload DMS; the plugin loads without widget errors and the top bar displays the live remaining percentage.
- [x] Open the widget popout; verified the existing profile appears once, shows its live limit windows, and exposes the add-account action. Multi-account login remains user initiated.
- [x] Commit as `feat: add account switching to DMS widget`.
- [ ] Commit as `feat: add account switching to DMS widget`.

### Task 3: Install and publish the standalone plugin

**Files:**
- Modify: `README.md`, `plugin.json`
- Create: `LICENSE`
- Install: `~/.config/dms/plugins/chatgptLimits/`

- [ ] Document manual installation, first-account behavior, additional-account login, supported limit data, and credential locations.
- [ ] Validate manifest JSON and run the helper's read-only list command.
- [ ] Install the finished files to the active DMS plugin directory and restart DMS; inspect logs for plugin load or QML errors.
- [ ] Commit as `docs: package and document DMS ChatGPT limits plugin`.
- [ ] Create public repository `luwili/dms-chatgpt-limits`, push the committed source, and verify the default branch and file list on GitHub.
