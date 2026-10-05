"""Notification service.

Phase 1 only writes local reports. The channel registry lets Phase 7 add
Email / Telegram / Discord / Slack sinks WITHOUT touching the scraping
engine: implement ``send(subject, body)`` and register it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..database import Database
from ..logging_config import get_logger
from ..models import utcnow_iso

Channel = Callable[[str, str], None]


class NotificationService:
    """Pluggable notification sink; local report is the only Phase-1 channel."""

    def __init__(self, export_dir: Path, db: Optional[Database] = None):
        self.export_dir = Path(export_dir)
        self.db = db
        self.log = get_logger("notifications")
        self._channels: dict[str, Channel] = {"local": self._send_local}

    def register_channel(self, name: str, sender: Channel) -> None:
        """Register a new notification channel (Phase 7: email/telegram/...)."""
        self._channels[name] = sender

    def available_channels(self) -> list[str]:
        return sorted(self._channels)

    def notify(self, subject: str, body: str,
               channels: tuple[str, ...] = ("local",)) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name in channels:
            sender = self._channels.get(name)
            if sender is None:
                results[name] = False
                continue
            try:
                sender(subject, body)
                results[name] = True
                if self.db is not None:
                    self.db._execute(
                        "INSERT INTO notifications (created_at, channel, subject, "
                        "body, status) VALUES (?, ?, ?, ?, 'SENT')",
                        (utcnow_iso(), name, subject, body))
                    self.db.conn.commit()
            except Exception as exc:  # notifications must never break a run
                results[name] = False
                self.log.error("Notification channel '%s' failed: %s", name, exc)
        return results

    # -- built-in channels -------------------------------------------------
    def _send_local(self, subject: str, body: str) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        stamp = utcnow_iso().replace(":", "").replace("-", "").replace("+0000", "Z")
        path = self.export_dir / f"report_{stamp}.txt"
        path.write_text(f"{subject}\n{'=' * len(subject)}\n\n{body}\n",
                        encoding="utf-8")
        latest = self.export_dir / "last_report.txt"
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
