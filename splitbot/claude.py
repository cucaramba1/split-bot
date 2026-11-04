"""Обёртка claude -p (перенос из idea-bot/ideabot/brain.py): Haiku, без MCP и тулов."""
from __future__ import annotations

import asyncio
import json
import os
import re

from splitbot.config import Settings

CLAUDE_STALL = 60  # claude молчит столько секунд (ни одного события потока): завис
MODEL = "haiku"

_LOGIN = re.compile(r"not logged in|please run /login|login required|invalid api key|authentication", re.I)
_LIMIT = re.compile(r"usage limit|rate limit|limit reached|quota|overloaded|too many requests|\b429\b", re.I)


class BrainError(RuntimeError):
    """kind: login | limit | timeout | error."""

    def __init__(self, msg: str, kind: str | None = None):
        super().__init__(msg)
        t = msg.lower()
        self.kind = kind or ("login" if _LOGIN.search(t) else "limit" if _LIMIT.search(t) and "context limit" not in t
                             else "error")


async def run_claude(s: Settings, prompt: str, *, system: str, schema: dict | None = None,
                     timeout: int = 90) -> dict | str:
    args = [s.claude_bin, "-p", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--no-session-persistence", "--system-prompt", system, "--tools", "", "--model", MODEL]
    if schema is not None:
        args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    s.data_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PATH": f"{os.path.dirname(s.claude_bin)}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(s.data_dir), env=env, limit=16 * 1024 * 1024)
    except OSError as e:
        raise BrainError(f"не смог запустить claude: {e}")
    data, err = None, b""
    try:
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        err_task = asyncio.create_task(proc.stderr.read())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            left = deadline - loop.time()
            if left <= 0:
                raise BrainError(f"claude не ответил за {timeout} с", kind="timeout")
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), min(CLAUDE_STALL, left))
            except asyncio.TimeoutError:
                if loop.time() >= deadline:
                    raise BrainError(f"claude не ответил за {timeout} с", kind="timeout")
                raise BrainError(f"claude молчит {CLAUDE_STALL} с, похоже завис", kind="timeout")
            if not line:
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("type") in (None, "result"):
                data = ev
        await proc.wait()
        err = await err_task
    finally:
        if proc.returncode is None:  # таймаут, зависание или отмена: не оставляем сироту claude
            proc.kill()
            await proc.wait()
    if proc.returncode != 0:
        raise BrainError(f"claude exit {proc.returncode}: {err.decode(errors='ignore')[-300:]}")
    if data is None:
        raise BrainError("claude вернул не JSON")
    if data.get("is_error"):
        raise BrainError(f"claude: {str(data.get('result'))[:300]}")
    if schema is not None:
        so = data.get("structured_output")
        if not isinstance(so, dict):
            raise BrainError("claude не вернул structured_output")
        return so
    return str(data.get("result") or "")
