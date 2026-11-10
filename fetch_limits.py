#!/usr/bin/env python3
"""Manage isolated ChatGPT sign-ins and read their Codex usage limits."""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable


CLIENT_INFO = {
    "name": "dms-chatgpt-limits",
    "version": "1.1.0",
    "title": "DMS ChatGPT Limits",
}
PROFILE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
PROFILE_CONFIG = 'cli_auth_credentials_store = "file"\n'


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def get_data_directory(data_dir: Path | str | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return base / "dms-chatgpt-limits"


def default_codex_home(default_home: Path | str | None = None) -> Path:
    if default_home is not None:
        return Path(default_home).expanduser()
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Каталог профиля небезопасен: {path.name}")
    path.chmod(0o700)


def validate_profile_id(account_id: str) -> str:
    if account_id == "default":
        return account_id
    if not PROFILE_ID_PATTERN.fullmatch(account_id):
        raise ValueError("Некорректный идентификатор аккаунта")
    return account_id


def profile_home(
    account_id: str,
    *,
    data_dir: Path | str | None = None,
    default_home: Path | str | None = None,
    create: bool = False,
) -> Path:
    validate_profile_id(account_id)
    if account_id == "default":
        return default_codex_home(default_home)

    state_dir = get_data_directory(data_dir)
    profiles_dir = state_dir / "profiles"
    ensure_private_directory(state_dir)
    ensure_private_directory(profiles_dir)
    home = profiles_dir / account_id
    if home.is_symlink():
        raise RuntimeError("Каталог профиля не может быть символической ссылкой")

    resolved_profiles = profiles_dir.resolve()
    resolved_home = home.resolve(strict=False)
    if not resolved_home.is_relative_to(resolved_profiles):
        raise ValueError("Каталог профиля выходит за пределы хранилища")

    if create:
        ensure_private_directory(home)
        config_path = home / "config.toml"
        if not config_path.exists():
            descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as config_file:
                config_file.write(PROFILE_CONFIG)
        else:
            config_path.chmod(0o600)
    return home


def _profile_registry_path(data_dir: Path | str | None = None) -> Path:
    return get_data_directory(data_dir) / "accounts.json"


def load_profiles(data_dir: Path | str | None = None) -> list[dict[str, str | None]]:
    registry_path = _profile_registry_path(data_dir)
    if not registry_path.exists():
        return []

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Не удалось прочитать список аккаунтов") from error

    accounts = registry.get("accounts") if isinstance(registry, dict) else None
    if not isinstance(accounts, list):
        raise RuntimeError("Файл списка аккаунтов имеет неверный формат")

    profiles: list[dict[str, str | None]] = []
    seen_ids: set[str] = set()
    for entry in accounts:
        if not isinstance(entry, dict):
            continue
        account_id = entry.get("id")
        if not isinstance(account_id, str):
            continue
        try:
            validate_profile_id(account_id)
        except ValueError:
            continue
        if account_id == "default" or account_id in seen_ids:
            continue
        seen_ids.add(account_id)
        email = entry.get("email") if isinstance(entry.get("email"), str) else None
        plan_type = entry.get("planType") if isinstance(entry.get("planType"), str) else None
        profiles.append({"id": account_id, "email": email, "planType": plan_type})
    return profiles


def save_profile(profile: dict[str, Any], data_dir: Path | str | None = None) -> None:
    account_id = profile.get("id")
    if not isinstance(account_id, str):
        raise ValueError("В профиле отсутствует идентификатор")
    validate_profile_id(account_id)
    if account_id == "default":
        raise ValueError("Основной профиль нельзя сохранять как дополнительный")

    state_dir = get_data_directory(data_dir)
    ensure_private_directory(state_dir)
    safe_profile = {
        "id": account_id,
        "email": profile.get("email") if isinstance(profile.get("email"), str) else None,
        "planType": profile.get("planType") if isinstance(profile.get("planType"), str) else None,
    }
    accounts = [item for item in load_profiles(state_dir) if item["id"] != account_id]
    accounts.append(safe_profile)
    accounts.sort(key=lambda item: str(item["id"]))

    registry_path = _profile_registry_path(state_dir)
    descriptor, temporary_name = tempfile.mkstemp(prefix="accounts-", suffix=".tmp", dir=state_dir)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as registry_file:
            json.dump({"accounts": accounts}, registry_file, ensure_ascii=False, indent=2)
            registry_file.write("\n")
            registry_file.flush()
            os.fsync(registry_file.fileno())
        os.replace(temporary_path, registry_path)
        registry_path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


class JsonLineReader:
    """Read complete JSONL messages from a pipe without losing buffered events."""

    def __init__(self, file_descriptor: int) -> None:
        self.file_descriptor = file_descriptor
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""

    def read_message(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    return message
                continue

            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([self.file_descriptor], [], [], remaining)
            if not readable:
                break
            chunk = os.read(self.file_descriptor, 4096)
            if not chunk:
                self.buffer += self.decoder.decode(b"", final=True)
                if self.buffer.strip():
                    try:
                        message = json.loads(self.buffer)
                    except json.JSONDecodeError:
                        break
                    self.buffer = ""
                    if isinstance(message, dict):
                        return message
                raise EOFError("Codex app-server завершил работу")
            self.buffer += self.decoder.decode(chunk)

        raise TimeoutError("Codex app-server не ответил вовремя")


def codex_command() -> list[str]:
    executable = shutil.which("codex")
    if executable:
        return [executable, "app-server", "--stdio"]
    local_executable = Path.home() / ".local" / "bin" / "codex"
    if local_executable.is_file() and os.access(local_executable, os.X_OK):
        return [str(local_executable), "app-server", "--stdio"]
    raise RuntimeError("Команда codex не найдена")


class AppServer:
    def __init__(self, home: Path) -> None:
        if not home.is_dir():
            raise RuntimeError("Каталог Codex-профиля не найден")
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(home)
        self.process = subprocess.Popen(
            codex_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=environment,
        )
        if self.process.stdin is None or self.process.stdout is None:
            self.close()
            raise RuntimeError("Не удалось открыть канал Codex app-server")
        self.reader = JsonLineReader(self.process.stdout.fileno())
        self.request_id = 0
        self.pending_messages: list[dict[str, Any]] = []
        try:
            self.request(
                "initialize",
                {"clientInfo": CLIENT_INFO, "capabilities": {}},
                timeout=8.0,
            )
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("stdin Codex app-server уже закрыт")
        payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        remaining = memoryview(payload)
        while remaining:
            written = self.process.stdin.write(remaining)
            if not written:
                raise RuntimeError("Не удалось отправить запрос Codex app-server")
            remaining = remaining[written:]
        self.process.stdin.flush()

    def next_message(self, timeout: float) -> dict[str, Any]:
        if self.pending_messages:
            return self.pending_messages.pop(0)
        return self.reader.read_message(timeout)

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 18.0,
    ) -> dict[str, Any]:
        self.request_id += 1
        request_id = self.request_id
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        self.send(message)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.reader.read_message(max(0.0, deadline - time.monotonic()))
            if response.get("id") == request_id:
                if "error" in response:
                    error = response["error"]
                    detail = error.get("message", "Ошибка Codex app-server") if isinstance(error, dict) else str(error)
                    raise RuntimeError(detail)
                result = response.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Codex app-server вернул неожиданный ответ")
                return result
            self.pending_messages.append(response)
        raise TimeoutError("Codex app-server не ответил вовремя")

    def close(self) -> None:
        if getattr(self, "process", None) is None:
            return
        if self.process.stdin is not None and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2.0)


def list_accounts(
    *,
    data_dir: Path | str | None = None,
    default_home: Path | str | None = None,
    app_server_factory: Callable[[Path], Any] = AppServer,
) -> dict[str, Any]:
    default_account: dict[str, Any] = {
        "id": "default",
        "email": None,
        "planType": None,
        "label": "Основной Codex",
        "authenticated": False,
    }
    server = None
    try:
        server = app_server_factory(profile_home("default", default_home=default_home))
        result = server.request("account/read", {"refreshToken": False})
        account = result.get("account")
        if isinstance(account, dict):
            default_account["email"] = account.get("email")
            default_account["planType"] = account.get("planType")
            default_account["label"] = account.get("email") or "Основной Codex"
            default_account["authenticated"] = account.get("type") == "chatgpt"
    except Exception as error:
        default_account["error"] = str(error)
    finally:
        if server is not None:
            server.close()

    additional_accounts = []
    for profile in load_profiles(data_dir):
        additional_accounts.append(
            {
                **profile,
                "label": profile["email"] or "Дополнительный аккаунт",
                "authenticated": True,
            }
        )
    return {"ok": True, "accounts": [default_account, *additional_accounts]}


def fetch_limits(
    account_id: str,
    *,
    data_dir: Path | str | None = None,
    default_home: Path | str | None = None,
    app_server_factory: Callable[[Path], Any] = AppServer,
) -> dict[str, Any]:
    validate_profile_id(account_id)
    profile = None
    if account_id != "default":
        profile = next((item for item in load_profiles(data_dir) if item["id"] == account_id), None)
        if profile is None:
            raise ValueError("Аккаунт не найден в списке")

    home = profile_home(
        account_id,
        data_dir=data_dir,
        default_home=default_home,
        create=False,
    )
    if not home.is_dir():
        raise RuntimeError("Профиль Codex не найден")

    server = app_server_factory(home)
    try:
        result = server.request("account/rateLimits/read")
    finally:
        server.close()

    limits = result.get("rateLimitsByLimitId")
    if not isinstance(limits, dict):
        single_limit = result.get("rateLimits")
        limits = {single_limit.get("limitId", "codex"): single_limit} if isinstance(single_limit, dict) else {}

    normalized: list[dict[str, Any]] = []
    for limit_id, limit in limits.items():
        if not isinstance(limit, dict):
            continue
        normalized.append(
            {
                "id": str(limit.get("limitId") or limit_id),
                "name": limit.get("limitName"),
                "primary": limit.get("primary"),
                "secondary": limit.get("secondary"),
                "planType": limit.get("planType") or (profile or {}).get("planType"),
                "reached": limit.get("rateLimitReachedType"),
            }
        )
    normalized.sort(key=lambda item: (item["id"] != "codex", item["id"]))
    return {
        "ok": True,
        "accountId": account_id,
        "limits": normalized,
        "resetCredits": result.get("rateLimitResetCredits"),
        "fetchedAt": int(time.time()),
    }


def begin_login(
    *,
    data_dir: Path | str | None = None,
    default_home: Path | str | None = None,
    app_server_factory: Callable[[Path], Any] = AppServer,
    emit: Callable[[dict[str, Any]], None] = emit,
) -> str:
    account_id = uuid.uuid4().hex
    home = profile_home(account_id, data_dir=data_dir, default_home=default_home, create=True)
    server = None
    try:
        server = app_server_factory(home)
        login = server.request(
            "account/login/start",
            {
                "type": "chatgpt",
                "useHostedLoginSuccessPage": True,
                "appBrand": "chatgpt",
            },
            timeout=20.0,
        )
        login_id = login.get("loginId")
        auth_url = login.get("authUrl")
        if not isinstance(login_id, str) or not isinstance(auth_url, str):
            raise RuntimeError("Codex не вернул данные для входа ChatGPT")
        emit(
            {
                "event": "login_started",
                "profileId": account_id,
                "authUrl": auth_url,
            }
        )

        while True:
            message = server.next_message(300.0)
            if message.get("method") != "account/login/completed":
                continue
            params = message.get("params")
            if not isinstance(params, dict) or params.get("loginId") != login_id:
                continue
            if not params.get("success"):
                raise RuntimeError(str(params.get("error") or "Вход ChatGPT не завершён"))

            account_result = server.request("account/read", {"refreshToken": False})
            account = account_result.get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                raise RuntimeError("Codex не подтвердил вход в ChatGPT")
            save_profile(
                {
                    "id": account_id,
                    "email": account.get("email"),
                    "planType": account.get("planType"),
                },
                data_dir=data_dir,
            )
            emit(
                {
                    "event": "login_completed",
                    "profileId": account_id,
                    "email": account.get("email"),
                    "planType": account.get("planType"),
                }
            )
            return account_id
    except Exception:
        shutil.rmtree(home, ignore_errors=True)
        raise
    finally:
        if server is not None:
            server.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List available ChatGPT accounts")
    limits_parser = commands.add_parser("limits", help="Read one account's Codex limits")
    limits_parser.add_argument("account_id")
    commands.add_parser("login", help="Add a ChatGPT account")
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "list":
            emit(list_accounts())
        elif arguments.command == "limits":
            emit(fetch_limits(arguments.account_id))
        else:
            begin_login()
        return 0
    except Exception as error:
        emit({"ok": False, "error": str(error), "event": "login_error" if arguments.command == "login" else None})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
