import json
import time
import uuid
import hashlib
from typing import Dict, Optional


class TokenVault:
    def __init__(self, ttl_seconds: int = 900, use_in_memory_cache: bool = True):
        # In production this should be backed by Redis with TTL
        self._vault: Dict[str, Dict[str, str]] = {}
        self._reverse: Dict[str, Dict[str, str]] = {}
        self._expiry: Dict[str, float] = {}
        self._ttl_seconds = ttl_seconds
        self._use_in_memory_cache = use_in_memory_cache

    def start_session(self, ttl_seconds: Optional[int] = None) -> str:
        vault_id = str(uuid.uuid4())
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        self._expiry[vault_id] = time.time() + ttl if ttl > 0 else float("inf")
        if self._use_in_memory_cache:
            self._vault[vault_id] = {}
            self._reverse[vault_id] = {}
        return vault_id

    def _is_expired(self, vault_id: str) -> bool:
        expiry = self._expiry.get(vault_id)
        if expiry is None:
            return True
        return time.time() > expiry

    def cleanup_expired(self) -> None:
        expired_ids = [vault_id for vault_id in self._expiry if self._is_expired(vault_id)]
        for vault_id in expired_ids:
            self.clear_session(vault_id)

    def generate_token(self, entity_type: str, counter: int) -> str:
        return self.create_token(entity_type, counter)

    def create_token(self, entity_type: str, counter: int) -> str:
        # Keep backward compatible token format
        return f"<{entity_type}_{counter}>"

    def store_mapping(self, vault_id: str, token: str, original_value: str) -> None:
        self.store_token(vault_id, token, original_value)

    def store_token(self, vault_id: str, token: str, original_value: str) -> None:
        if not self._use_in_memory_cache:
            return
        if vault_id not in self._vault:
            self._vault[vault_id] = {}
            self._reverse[vault_id] = {}
        self._vault[vault_id][token] = original_value
        self._reverse[vault_id][original_value] = token

    def get_mapping(self, vault_id: str, purge_expired: bool = True) -> Dict[str, str]:
        if purge_expired and self._is_expired(vault_id):
            self.clear_session(vault_id)
            return {}
        return self._vault.get(vault_id, {})

    def get_original(self, vault_id: str, token: str) -> Optional[str]:
        if self._is_expired(vault_id):
            self.clear_session(vault_id)
            return None
        return self._vault.get(vault_id, {}).get(token)

    def reverse_lookup(self, vault_id: str, original_value: str) -> Optional[str]:
        if self._is_expired(vault_id):
            self.clear_session(vault_id)
            return None
        return self._reverse.get(vault_id, {}).get(original_value)

    def serialize_session(self, vault_id: str, redact: bool = True) -> str:
        mapping = self.get_mapping(vault_id)
        if redact:
            safe_mapping = {
                token: hashlib.sha256(value.encode("utf-8")).hexdigest()
                for token, value in mapping.items()
            }
        else:
            safe_mapping = mapping
        payload = {
            "vault_id": vault_id,
            "expires_at": self._expiry.get(vault_id),
            "mapping": safe_mapping,
        }
        return json.dumps(payload, ensure_ascii=True)

    def deserialize_session(self, payload: str) -> Dict[str, object]:
        data = json.loads(payload)
        return {
            "vault_id": data.get("vault_id"),
            "expires_at": data.get("expires_at"),
            "mapping": data.get("mapping", {}),
        }

    def clear_session(self, vault_id: str) -> None:
        if vault_id in self._vault:
            del self._vault[vault_id]
        if vault_id in self._reverse:
            del self._reverse[vault_id]
        if vault_id in self._expiry:
            del self._expiry[vault_id]


# Singleton instance for simplicity in this prototype.
token_vault = TokenVault()
