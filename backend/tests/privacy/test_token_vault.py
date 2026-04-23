import time
import importlib
from concurrent.futures import ThreadPoolExecutor

from backend.core.privacy.token_vault import TokenVault


def test_token_generation_and_mapping():
    vault = TokenVault(ttl_seconds=10)
    vault_id = vault.start_session()
    token = vault.generate_token("PERSON", 1)
    vault.store_mapping(vault_id, token, "Nguyen Van A")

    assert token == "<PERSON_1>"
    assert vault.get_original(vault_id, token) == "Nguyen Van A"
    assert vault.reverse_lookup(vault_id, "Nguyen Van A") == token


def test_missing_token_fallback():
    vault = TokenVault(ttl_seconds=10)
    vault_id = vault.start_session()
    assert vault.get_original(vault_id, "<PERSON_999>") is None


def test_ttl_expiration_and_cleanup():
    vault = TokenVault(ttl_seconds=0.1)
    vault_id = vault.start_session()
    token = vault.generate_token("EMAIL", 1)
    vault.store_mapping(vault_id, token, "test@example.com")

    time.sleep(0.2)

    # Lazy cleanup should remove expired mapping
    assert vault.get_mapping(vault_id) == {}
    assert vault.get_original(vault_id, token) is None


def test_serialization_deserialization():
    vault = TokenVault(ttl_seconds=10)
    vault_id = vault.start_session()
    token = vault.generate_token("PHONE_NUMBER", 1)
    vault.store_mapping(vault_id, token, "0901234567")

    payload = vault.serialize_session(vault_id, redact=True)
    data = vault.deserialize_session(payload)

    assert data["vault_id"] == vault_id
    assert token in data["mapping"]
    assert len(data["mapping"][token]) == 64


def test_concurrent_access():
    vault = TokenVault(ttl_seconds=10)
    vault_id = vault.start_session()

    def _store(i: int):
        token = vault.generate_token("EMAIL", i)
        vault.store_mapping(vault_id, token, f"user{i}@example.com")

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(_store, range(1, 51)))

    mapping = vault.get_mapping(vault_id)
    assert len(mapping) == 50


def test_import_resolution():
    importlib.import_module("backend.core.privacy.token_vault")
    importlib.import_module("backend.core.privacy.anonymizer")
