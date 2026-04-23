# backend/scoring/security/token.py
"""
Control Token Generation & Verification
=======================================

GĐ2 PHẦN E: Controller Tokenization

MainController generates HMAC tokens that must be verified
by scoring core before any computation.

Flow:
1. MainController generates token: HMAC(secret, request_id + timestamp)
2. Token injected into scoring context
3. Core verifies token before compute
4. Invalid/missing token = SecurityException
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger("scoring.security.token")

# Token secret - should be from environment in production
_TOKEN_SECRET = os.environ.get(
    "SIMGR_CONTROL_SECRET",
    "simgr-control-secret-gd2-default"  # Default for development
)

# Token validity window (seconds)
TOKEN_VALIDITY_SECONDS = 300  # 5 minutes


@dataclass
class ControlToken:
    """Control token issued by MainController."""
    token: str
    request_id: str
    timestamp: float
    issuer: str
    expires_at: float
    
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return time.time() > self.expires_at
    
    def to_dict(self) -> dict:
        """Export token data."""
        return {
            "token": self.token,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "issuer": self.issuer,
            "expires_at": self.expires_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ControlToken:
        """Create from dict."""
        return cls(
            token=data["token"],
            request_id=data["request_id"],
            timestamp=data["timestamp"],
            issuer=data["issuer"],
            expires_at=data["expires_at"],
        )


def _compute_hmac(request_id: str, timestamp: float) -> str:
    """Compute HMAC for token."""
    message = f"{request_id}:{timestamp}"
    signature = hmac.new(
        _TOKEN_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


def generate_control_token(
    request_id: str,
    issuer: str = "MainController",
    validity_seconds: int = TOKEN_VALIDITY_SECONDS,
) -> ControlToken:
    """
    Generate control token for scoring request.
    
    Args:
        request_id: Unique request identifier
        issuer: Token issuer (should be MainController)
        validity_seconds: Token validity period
    
    Returns:
        ControlToken instance
    """
    timestamp = time.time()
    expires_at = timestamp + validity_seconds
    
    token = _compute_hmac(request_id, timestamp)
    
    control_token = ControlToken(
        token=token,
        request_id=request_id,
        timestamp=timestamp,
        issuer=issuer,
        expires_at=expires_at,
    )
    
    logger.debug(
        f"[TOKEN] Generated: request_id={request_id} "
        f"issuer={issuer} "
        f"hash={token[:16]}..."
    )
    
    return control_token


def verify_control_token(
    token: ControlToken,
    expected_request_id: Optional[str] = None,
    check_expiry: bool = True,
) -> bool:
    """
    Verify control token is valid.
    
    Args:
        token: Token to verify
        expected_request_id: Expected request ID (optional)
        check_expiry: Whether to check token expiry
    
    Returns:
        True if valid, False otherwise
    """
    # Check expiry
    if check_expiry and token.is_expired():
        logger.warning(
            f"[TOKEN] Expired: request_id={token.request_id} "
            f"expired_at={token.expires_at}"
        )
        return False
    
    # Check request_id match if provided
    if expected_request_id and token.request_id != expected_request_id:
        logger.warning(
            f"[TOKEN] Request ID mismatch: "
            f"expected={expected_request_id} got={token.request_id}"
        )
        return False
    
    # Recompute HMAC and verify
    expected_token = _compute_hmac(token.request_id, token.timestamp)
    
    if not hmac.compare_digest(token.token, expected_token):
        logger.error(
            f"[TOKEN] INVALID: request_id={token.request_id} "
            f"possible tampering"
        )
        return False
    
    logger.debug(
        f"[TOKEN] Verified: request_id={token.request_id} "
        f"issuer={token.issuer}"
    )
    return True


def verify_token_dict(
    token_data: dict,
    expected_request_id: Optional[str] = None,
    check_expiry: bool = True,
) -> bool:
    """
    Verify token from dict representation.
    
    Args:
        token_data: Token data dict
        expected_request_id: Expected request ID
        check_expiry: Check expiry
    
    Returns:
        True if valid
    """
    try:
        token = ControlToken.from_dict(token_data)
        return verify_control_token(token, expected_request_id, check_expiry)
    except (KeyError, TypeError) as e:
        logger.error(f"[TOKEN] Invalid token data: {e}")
        return False


class TokenManager:
    """
    Token manager for MainController.
    
    Usage:
        manager = TokenManager()
        token = manager.issue(request_id)
        # Pass token to scoring core
        if manager.verify(token):
            # Proceed
    """
    
    def __init__(self, issuer: str = "MainController"):
        self.issuer = issuer
        self._issued_tokens: dict = {}  # request_id -> token
    
    def issue(self, request_id: str) -> ControlToken:
        """Issue new control token."""
        token = generate_control_token(request_id, self.issuer)
        self._issued_tokens[request_id] = token
        return token
    
    def verify(self, token: ControlToken) -> bool:
        """Verify token is valid."""
        return verify_control_token(token)
    
    def revoke(self, request_id: str) -> None:
        """Revoke token for request."""
        if request_id in self._issued_tokens:
            del self._issued_tokens[request_id]
            logger.info(f"[TOKEN] Revoked: request_id={request_id}")
    
    def get_token(self, request_id: str) -> Optional[ControlToken]:
        """Get issued token for request."""
        return self._issued_tokens.get(request_id)
    
    def cleanup_expired(self) -> int:
        """Remove expired tokens. Returns count removed."""
        now = time.time()
        expired = [
            rid for rid, token in self._issued_tokens.items()
            if token.expires_at < now
        ]
        for rid in expired:
            del self._issued_tokens[rid]
        return len(expired)
