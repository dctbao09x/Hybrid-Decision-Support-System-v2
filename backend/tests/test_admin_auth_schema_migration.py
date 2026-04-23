from __future__ import annotations

import sqlite3
from pathlib import Path

import bcrypt

from backend.modules.admin_auth.service import AdminAuthService


def _create_legacy_admins_table(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE admins (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        )
        """
    )
    password_hash = bcrypt.hashpw(b"legacy-pass", bcrypt.gensalt()).decode("utf-8")
    conn.execute(
        "INSERT INTO admins (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
        ("adm_legacy", "admin", password_hash, "admin"),
    )
    conn.commit()
    conn.close()


def test_login_migrates_missing_last_login_column(tmp_path: Path) -> None:
    db_path = tmp_path / "admin_feedback.db"
    _create_legacy_admins_table(db_path)

    service = AdminAuthService(db_path=db_path)
    result = service.login("admin", "legacy-pass", "127.0.0.1")

    assert result.admin.adminId == "adm_legacy"
    assert result.admin.role == "admin"

    with sqlite3.connect(str(db_path)) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(admins)").fetchall()]
        assert "last_login" in cols

        row = conn.execute("SELECT last_login FROM admins WHERE id = ?", ("adm_legacy",)).fetchone()
        assert row is not None
        assert row[0]
