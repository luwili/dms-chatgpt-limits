#!/usr/bin/env python3
"""Read ChatGPT-backed Codex rate limits through the local Codex app-server."""

from __future__ import annotations

import codecs
import json
import os
import select
import shutil
import subprocess
import sys
import time
from typing import Any


CLIENT_INFO = {
    "name": "dms-chatgpt-limits",
    "version": "1.0.0",
    "title": "DMS ChatGPT Limits",
}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    sys.stdout.flush()


def codex_command() -> list[str]:
    executable = shutil.which("codex")
    if executable:
        return [executable, "app-server", "--stdio"]

    local_executable = os.path.expanduser("~/.local/bin/codex")
    if os.path.isfile(local_executable) and os.access(local_executable, os.X_OK):
        return [local_executable, "app-server", "--stdio"]

    raise RuntimeError("Команда codex не найдена")


def send(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("Не удалось открыть stdin Codex app-server")
    process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
    process.stdin.flush()


class ResponseReader:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None:
            raise RuntimeError("Не удалось открыть stdout Codex app-server")
        self.stdout = process.stdout
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.pending = ""

    def read_response(self, process: subprocess.Popen[bytes], request_id: int, timeout: float) -> dict[str, Any]:
        if process.stdout is None:
            raise RuntimeError("Не удалось открыть stdout Codex app-server")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if message.get("id") == request_id:
                    if "error" in message:
                        error = message["error"]
                        detail = error.get("message", "Ошибка Codex app-server") if isinstance(error, dict) else str(error)
                        raise RuntimeError(detail)
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise RuntimeError("Codex app-server вернул неожиданный ответ")
                    return result
                continue

            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([self.stdout], [], [], remaining)
            if not ready:
                break

            chunk = os.read(self.stdout.fileno(), 4096)
            if not chunk:
                break
            self.pending += self.decoder.decode(chunk)

        raise TimeoutError("Codex app-server не ответил вовремя")


def fetch_limits() -> dict[str, Any]:
    process = subprocess.Popen(
        codex_command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )

    try:
        reader = ResponseReader(process)
        send(
            process,
            {
                "method": "initialize",
                "id": 1,
                "params": {"clientInfo": CLIENT_INFO, "capabilities": {}},
            },
        )
        reader.read_response(process, 1, 8.0)
        send(process, {"method": "initialized"})
        send(process, {"method": "account/rateLimits/read", "id": 2})
        return reader.read_response(process, 2, 18.0)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)


def main() -> int:
    try:
        result = fetch_limits()
        limits = result.get("rateLimitsByLimitId")
        if not isinstance(limits, dict):
            single_limit = result.get("rateLimits")
            limits = {single_limit.get("limitId", "codex"): single_limit} if isinstance(single_limit, dict) else {}

        normalized: list[dict[str, Any]] = []
        for limit_id, limit in limits.items():
            if not isinstance(limit, dict):
                continue
            entry: dict[str, Any] = {
                "id": str(limit.get("limitId") or limit_id),
                "name": limit.get("limitName"),
                "primary": limit.get("primary"),
                "secondary": limit.get("secondary"),
                "planType": limit.get("planType"),
                "reached": limit.get("rateLimitReachedType"),
            }
            normalized.append(entry)

        normalized.sort(key=lambda item: (item["id"] != "codex", item["id"]))
        emit(
            {
                "ok": True,
                "limits": normalized,
                "resetCredits": result.get("rateLimitResetCredits"),
                "fetchedAt": int(time.time()),
            }
        )
        return 0
    except Exception as error:  # Report actionable errors to the widget without exposing credentials.
        emit({"ok": False, "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
