# backend/ops/security/secrets.py
"""
Secret Management for pipeline operations.

Manages:
- API keys
- Database credentials
- Webhook URLs
- Encryption keys

Uses environment variables with .env file support
and optional encryption-at-rest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ops.security.secrets")


class SecretManager:
    """
    Secure secret management for pipeline operations.

    Priority order:
    1. Environment variables
    2. Encrypted secrets file
    3. .env file (development only)

    Secrets are never logged or exposed in API responses.
    """

    # Secrets that the pipeline needs
    REQUIRED_SECRETS = [
        "LLM_API_KEY",
        "DATABASE_URL",
    ]

    OPTIONAL_SECRETS = [
        "SLACK_WEBHOOK_URL",
        "ALERT_EMAIL",
        "ENCRYPTION_KEY",
        "CRAWLER_PROXY_URL",
        "BACKUP_S3_KEY",
        "BACKUP_S3_SECRET",
    ]

    def __init__(
        self,
        env_file: Optional[Path] = None,
        secrets_file: Optional[Path] = None,
    ):
        self._env_file = env_file or Path("backend/.env")
        self._secrets_file = secrets_file or Path("backend/data/.secrets.enc")
        self._cache: Dict[str, str] = {}
        self._loaded = False

    def load(self) -> None:
        """Load secrets from all sources."""
        # Load .env file if exists
        if self._env_file.exists():
            self._load_env_file()

        # Load encrypted secrets if available
        if self._secrets_file.exists():
            self._load_encrypted_secrets()

        self._loaded = True
        logger.info("Secrets loaded successfully")

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a secret value."""
        if not self._loaded:
            self.load()

        # Priority: env var > cache > default
        value = os.environ.get(key)
        if value:
            return value

        value = self._cache.get(key)
        if value:
            return value

        return default

    def get_required(self, key: str) -> str:
        """Get a required secret, raising if not found."""
        value = self.get(key)
        if not value:
            raise EnvironmentError(
                f"Required secret '{key}' not found. "
                f"Set it as environment variable or in {self._env_file}"
            )
        return value

    def set(self, key: str, value: str) -> None:
        """Set a secret in the cache (not persisted)."""
        self._cache[key] = value
        logger.info(f"Secret '{key}' set in cache (not persisted)")

    def validate(self) -> Dict[str, Any]:
        """Validate that all required secrets are available."""
        results = {
            "required": {},
            "optional": {},
            "all_required_present": True,
        }

        for key in self.REQUIRED_SECRETS:
            present = self.get(key) is not None
            results["required"][key] = present
            if not present:
                results["all_required_present"] = False

        for key in self.OPTIONAL_SECRETS:
            results["optional"][key] = self.get(key) is not None

        return results

    def mask(self, key: str) -> str:
        """Get a masked version of a secret for logging."""
        value = self.get(key)
        if not value:
            return "<not set>"
        if len(value) <= 8:
            return "****"
        return value[:4] + "****" + value[-4:]

    def _load_env_file(self) -> None:
        """Parse .env file."""
        try:
            with open(self._env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        if key and value:
                            self._cache[key] = value
        except Exception as e:
            logger.warning(f"Failed to load .env file: {e}")

    def _load_encrypted_secrets(self) -> None:
        """Load encrypted secrets file using Fernet (AES-128-CBC)."""
        try:
            enc_key = os.environ.get("ENCRYPTION_KEY", "default-dev-key")
            fernet_key = self._derive_fernet_key(enc_key)

            from cryptography.fernet import Fernet
            f = Fernet(fernet_key)
            data = self._secrets_file.read_bytes()
            decrypted = f.decrypt(data)
            secrets = json.loads(decrypted)
            self._cache.update(secrets)
        except ImportError:
            # Fallback: try legacy XOR format
            try:
                data = self._secrets_file.read_bytes()
                decrypted = self._xor_decrypt(data, enc_key)
                secrets = json.loads(decrypted)
                self._cache.update(secrets)
                logger.warning("Loaded secrets with legacy XOR. Run save_encrypted() to upgrade to Fernet.")
            except Exception:
                logger.warning("Failed to load encrypted secrets (cryptography package not installed)")
        except Exception as e:
            logger.warning(f"Failed to load encrypted secrets: {e}")

    def save_encrypted(self, secrets: Dict[str, str]) -> None:
        """Save secrets to encrypted file using Fernet (AES-128-CBC)."""
        enc_key = os.environ.get("ENCRYPTION_KEY", "default-dev-key")

        try:
            from cryptography.fernet import Fernet
            fernet_key = self._derive_fernet_key(enc_key)
            f = Fernet(fernet_key)
            data = json.dumps(secrets).encode()
            encrypted = f.encrypt(data)
        except ImportError:
            logger.warning("cryptography package not installed, falling back to XOR (NOT SECURE)")
            data = json.dumps(secrets).encode()
            encrypted = self._xor_encrypt(data, enc_key)

        self._secrets_file.parent.mkdir(parents=True, exist_ok=True)
        self._secrets_file.write_bytes(encrypted)
        logger.info("Secrets saved to encrypted file")

    @staticmethod
    def _derive_fernet_key(passphrase: str) -> bytes:
        """Derive a Fernet-compatible key from a passphrase using PBKDF2."""
        import base64
        # Use PBKDF2 with SHA256 to derive 32-byte key, then base64url-encode
        dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), b"ops-secrets-salt", 100_000, dklen=32)
        return base64.urlsafe_b64encode(dk)

    @staticmethod
    def _xor_encrypt(data: bytes, key: str) -> bytes:
        key_bytes = hashlib.sha256(key.encode()).digest()
        return bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data))

    @staticmethod
    def _xor_decrypt(data: bytes, key: str) -> str:
        key_bytes = hashlib.sha256(key.encode()).digest()
        return bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data)).decode()

    @staticmethod
    def generate_env_template() -> str:
        """Generate .env.template with all required/optional secrets."""
        lines = [
            "# Pipeline Secrets Configuration",
            "# Copy to .env and fill in values",
            "",
            "# === Required ===",
        ]
        for key in SecretManager.REQUIRED_SECRETS:
            lines.append(f"{key}=")

        lines.extend(["", "# === Optional ==="])
        for key in SecretManager.OPTIONAL_SECRETS:
            lines.append(f"# {key}=")

        return "\n".join(lines)
