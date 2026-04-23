from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256
from threading import RLock
from typing import Dict, Optional


class CommandSigningVerifier:
    """Verifies HMAC signatures with nonce+timestamp replay protection."""

    def __init__(self, ttl_seconds: int = 300):
        self._secret = os.getenv("LIVEOPS_SIGNING_SECRET", "liveops-dev-secret")
        self._ttl_seconds = ttl_seconds
        self._nonces: Dict[str, float] = {}
        self._lock = RLock()

    def verify(
        self,
        *,
        user_id: str,
        command_type: str,
        target: str,
        timestamp: int,
        nonce: str,
        signature: str,
    ) -> bool:
        self._cleanup_expired_nonces()

        now = int(time.time())
        if abs(now - int(timestamp)) > self._ttl_seconds:
            return False

        nonce_key = f"{user_id}:{nonce}"
        with self._lock:
            if nonce_key in self._nonces:
                return False

        payload = f"{user_id}:{command_type}:{target}:{timestamp}:{nonce}"
        digest = hmac.new(self._secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()

        if not hmac.compare_digest(digest, signature):
            return False

        with self._lock:
            self._nonces[nonce_key] = time.time()

        return True

    def _cleanup_expired_nonces(self) -> None:
        cutoff = time.time() - self._ttl_seconds
        with self._lock:
            expired = [key for key, ts in self._nonces.items() if ts < cutoff]
            for key in expired:
                del self._nonces[key]


verifier = CommandSigningVerifier()
