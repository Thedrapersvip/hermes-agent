"""Optional Buzz transport bridge for Hermes ACP final responses.

Buzz's current ``buzz-acp`` harness forwards prompts over ACP but expects the
agent to publish visible channel messages through the Buzz CLI.  Asking the
model to perform that mechanical send adds another model/tool round trip and
can create accidental threads.  This module keeps the behavior opt-in via the
active Hermes profile and performs the transport step after reasoning finishes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_CHANNEL_RE = re.compile(
    r"(?m)^Channel:\s+.*?\(#([0-9a-fA-F-]{36})\)\s*$"
)
_EVENT_RE = re.compile(r"(?m)^Event ID:\s*([0-9a-fA-F]{64})\s*$")
_SCOPE_RE = re.compile(r"(?m)^Scope:\s*([a-zA-Z_-]+)\s*$")
_SENDER_RE = re.compile(r"(?m)^From:.*?hex:\s*([0-9a-fA-F]{64})\)")


@dataclass(frozen=True)
class BuzzPublishRequest:
    cli_path: str
    channel_id: str
    content: str
    reply_to: str | None = None
    mention_pubkey: str | None = None

    def argv(self) -> list[str]:
        argv = [
            self.cli_path,
            "messages",
            "send",
            "--channel",
            self.channel_id,
            "--content",
            "-",
        ]
        if self.reply_to:
            argv.extend(["--reply-to", self.reply_to])
        if self.mention_pubkey:
            # Supplying the sender identity also makes literal prose such as
            # "you do not need to @mention me" legal in buzz-cli. Without an
            # explicit identity, Buzz interprets every @word as a member lookup
            # and rejects the entire send when the word is not a display name.
            argv.extend(["--mention", self.mention_pubkey])
        return argv


def build_buzz_publish_request(
    *,
    user_text: str,
    final_response: str,
    config: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> BuzzPublishRequest | None:
    """Build an opt-in Buzz publish request from a buzz-acp prompt."""
    acp_cfg = config.get("acp") if isinstance(config, Mapping) else None
    if not isinstance(acp_cfg, Mapping) or acp_cfg.get("buzz_auto_publish") is not True:
        return None

    environment = env or os.environ
    if not environment.get("BUZZ_RELAY_URL") or not environment.get("BUZZ_PRIVATE_KEY"):
        return None

    channels = _CHANNEL_RE.findall(user_text or "")
    if not channels or not final_response.strip():
        return None

    scopes = _SCOPE_RE.findall(user_text or "")
    scope = scopes[-1].lower() if scopes else ""
    events = _EVENT_RE.findall(user_text or "")
    senders = _SENDER_RE.findall(user_text or "")
    flat_dms = acp_cfg.get("buzz_flat_dms", True) is not False
    reply_to = None if scope == "dm" and flat_dms else (events[-1] if events else None)

    cli_path = str(acp_cfg.get("buzz_cli_path") or (Path.home() / ".local/bin/buzz"))
    return BuzzPublishRequest(
        cli_path=cli_path,
        channel_id=channels[-1],
        content=final_response.rstrip() + "\n",
        reply_to=reply_to,
        mention_pubkey=senders[-1] if senders else None,
    )


async def maybe_publish_buzz_final_response(
    *,
    user_text: str,
    final_response: str,
) -> str | None:
    """Publish one final response through Buzz and return its event id.

    Returns ``None`` when the integration is disabled or the prompt is not from
    Buzz. Raises ``RuntimeError`` on an opted-in transport failure so the caller
    can log the visible-delivery failure distinctly from model completion.
    """
    from hermes_cli.config import load_config

    request = build_buzz_publish_request(
        user_text=user_text,
        final_response=final_response,
        config=load_config(),
    )
    if request is None:
        return None

    proc = await asyncio.create_subprocess_exec(
        *request.argv(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(request.content.encode("utf-8")), timeout=30
    )
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(f"Buzz CLI publish failed rc={proc.returncode}: {detail}")

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Buzz CLI publish returned invalid JSON") from exc
    event_id = payload.get("event_id") or payload.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise RuntimeError("Buzz CLI publish returned no event id")
    logger.info(
        "Published ACP final response to Buzz channel %s (event=%s, threaded=%s)",
        request.channel_id,
        event_id,
        bool(request.reply_to),
    )
    return event_id
