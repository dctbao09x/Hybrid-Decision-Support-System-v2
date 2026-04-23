# backend/ops/monitoring/alerts.py
"""
Alert System for pipeline operations.

Supports:
- Multi-channel alerts (log, file, webhook, email placeholder)
- Alert severity levels
- Alert aggregation and deduplication
- Cooldown to prevent alert storms
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ops.monitoring.alerts")


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"


class Alert:
    """A single alert instance."""

    def __init__(
        self,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
        source: str = "pipeline",
        context: Optional[Dict[str, Any]] = None,
    ):
        self.title = title
        self.message = message
        # Normalize plain strings to AlertSeverity enum
        if isinstance(severity, str) and not isinstance(severity, AlertSeverity):
            try:
                severity = AlertSeverity(severity.lower())
            except ValueError:
                severity = AlertSeverity.WARNING
        self.severity = severity
        self.source = source
        self.context = context or {}
        self.timestamp = datetime.now().isoformat()
        self.acknowledged = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "source": self.source,
            "context": self.context,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


class AlertChannel:
    """Base class for alert delivery channels."""

    async def send(self, alert: Alert) -> bool:
        raise NotImplementedError


class LogAlertChannel(AlertChannel):
    """Send alerts to Python logger."""

    async def send(self, alert: Alert) -> bool:
        level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.CRITICAL: logging.CRITICAL,
            AlertSeverity.FATAL: logging.CRITICAL,
        }.get(alert.severity, logging.WARNING)

        logger.log(level, f"[ALERT] {alert.severity.value.upper()}: {alert.title} - {alert.message}")
        return True


class FileAlertChannel(AlertChannel):
    """Write alerts to a JSON log file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path("backend/data/logs/alerts.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def send(self, alert: Alert) -> bool:
        try:
            with open(self.path, "a") as f:
                f.write(json.dumps(alert.to_dict()) + "\n")
            return True
        except Exception as e:
            logger.error(f"Failed to write alert to file: {e}")
            return False


class WebhookAlertChannel(AlertChannel):
    """Send alerts to a webhook URL (Slack, Discord, etc.)."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, alert: Alert) -> bool:
        try:
            import aiohttp
            payload = {
                "text": f"*[{alert.severity.value.upper()}]* {alert.title}\n{alert.message}",
                "attachments": [{"fields": [
                    {"title": k, "value": str(v), "short": True}
                    for k, v in alert.context.items()
                ]}] if alert.context else [],
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    return resp.status == 200
        except ImportError:
            logger.warning("aiohttp not available for webhook alerts")
            return False
        except Exception as e:
            logger.error(f"Webhook alert failed: {e}")
            return False


class EmailAlertChannel(AlertChannel):
    """
    Send alerts via SMTP email.

    Env vars:
      ALERT_SMTP_HOST, ALERT_SMTP_PORT,
      ALERT_SMTP_USER, ALERT_SMTP_PASS,
      ALERT_EMAIL_FROM, ALERT_EMAIL_TO (comma-separated)
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addrs: Optional[List[str]] = None,
    ):
        import os
        self.smtp_host = smtp_host or os.environ.get("ALERT_SMTP_HOST", "")
        self.smtp_port = smtp_port or int(os.environ.get("ALERT_SMTP_PORT", "587"))
        self.username = username or os.environ.get("ALERT_SMTP_USER", "")
        self.password = password or os.environ.get("ALERT_SMTP_PASS", "")
        self.from_addr = from_addr or os.environ.get("ALERT_EMAIL_FROM", "")
        self.to_addrs = to_addrs or [
            a.strip()
            for a in os.environ.get("ALERT_EMAIL_TO", "").split(",")
            if a.strip()
        ]

    async def send(self, alert: Alert) -> bool:
        if not self.smtp_host or not self.to_addrs:
            logger.debug("Email alert skipped — SMTP not configured")
            return False
        try:
            import smtplib
            from email.mime.text import MIMEText

            body = (
                f"Severity : {alert.severity.value.upper()}\n"
                f"Source   : {alert.source}\n"
                f"Time     : {alert.timestamp}\n"
                f"─────────────────────────────\n"
                f"{alert.message}\n"
            )
            if alert.context:
                body += "\nContext:\n"
                for k, v in alert.context.items():
                    body += f"  {k}: {v}\n"

            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = f"[HDSS {alert.severity.value.upper()}] {alert.title}"
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as srv:
                srv.ehlo()
                srv.starttls()
                if self.username:
                    srv.login(self.username, self.password)
                srv.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            return True
        except Exception as e:
            logger.error("Email alert failed: %s", e)
            return False


class AlertManager:
    """
    Central alert management system.

    Features:
    - Multi-channel delivery
    - Deduplication (same alert within cooldown period)
    - Alert history
    - Severity-based routing
    """

    def __init__(
        self,
        cooldown_seconds: float = 300.0,  # 5 minute dedup window
        max_history: int = 1000,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.max_history = max_history
        self._channels: List[AlertChannel] = []
        self._history: List[Alert] = []
        self._last_alert_time: Dict[str, datetime] = {}

        # Default: log channel always active
        self._channels.append(LogAlertChannel())
        self._channels.append(FileAlertChannel())

    def add_channel(self, channel: AlertChannel) -> None:
        """Add an alert delivery channel."""
        self._channels.append(channel)

    async def fire(
        self,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
        source: str = "pipeline",
        context: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> bool:
        """
        Fire an alert.

        Args:
            title: Alert title
            message: Alert message
            severity: Severity level
            source: Alert source
            context: Additional context
            force: Bypass cooldown deduplication
        """
        # Deduplication check
        dedup_key = f"{source}:{title}"
        now = datetime.now()

        if not force and dedup_key in self._last_alert_time:
            elapsed = (now - self._last_alert_time[dedup_key]).total_seconds()
            if elapsed < self.cooldown_seconds:
                logger.debug(f"Alert deduplicated: {title} (cooldown: {self.cooldown_seconds - elapsed:.0f}s remaining)")
                return False

        alert = Alert(
            title=title,
            message=message,
            severity=severity,
            source=source,
            context=context,
        )

        # Deliver to all channels
        delivered = False
        for channel in self._channels:
            try:
                if await channel.send(alert):
                    delivered = True
            except Exception as e:
                logger.error(f"Alert channel failed: {type(channel).__name__}: {e}")

        # Record
        self._history.append(alert)
        self._last_alert_time[dedup_key] = now

        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]

        return delivered

    async def fire_if(
        self,
        condition: bool,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
        **kwargs,
    ) -> bool:
        """Fire alert only if condition is True."""
        if condition:
            return await self.fire(title, message, severity, **kwargs)
        return False

    def get_recent(
        self,
        hours: float = 24.0,
        severity: Optional[AlertSeverity] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            a.to_dict()
            for a in reversed(self._history)
            if datetime.fromisoformat(a.timestamp) > cutoff
            and (severity is None or a.severity == severity)
        ]

    def get_summary(self) -> Dict[str, Any]:
        """Get alert summary statistics."""
        by_severity = defaultdict(int)
        for a in self._history:
            sev_key = a.severity.value if hasattr(a.severity, 'value') else str(a.severity)
            by_severity[sev_key] += 1

        return {
            "total_alerts": len(self._history),
            "by_severity": dict(by_severity),
            "channels": len(self._channels),
            "cooldown_seconds": self.cooldown_seconds,
        }
