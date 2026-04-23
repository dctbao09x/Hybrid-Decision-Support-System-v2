from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple

import bcrypt
import jwt
from fastapi import HTTPException, status

from .model import AdminContext, AdminLoginResponse


ROLE_PERMISSIONS: Dict[str, list[str]] = {
    "viewer": ["feedback:view"],
    "operator": ["feedback:view", "feedback:modify", "feedback:assign"],
    "admin": ["feedback:view", "feedback:modify", "feedback:assign", "feedback:delete", "feedback:export"],
}


class AdminAuthService:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or Path("storage/admin_feedback.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._login_attempts: Dict[str, Deque[float]] = defaultdict(deque)

        self._jwt_secret = os.getenv("ADMIN_JWT_SECRET", "change-me-in-production")
        self._refresh_secret = os.getenv("ADMIN_REFRESH_SECRET", "change-me-refresh-secret")
        self._access_exp_minutes = int(os.getenv("ADMIN_ACCESS_EXP_MINUTES", "30"))
        self._refresh_exp_days = int(os.getenv("ADMIN_REFRESH_EXP_DAYS", "7"))

    def initialize(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
            self._migrate_legacy_schema()
            self._seed_default_admin()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                last_login TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_actions (
                id TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_id TEXT,
                ip TEXT,
                details TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_id TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_actions_timestamp ON admin_actions(timestamp DESC)")
        self._conn.commit()

    def _table_columns(self, table_name: str) -> set[str]:
        assert self._conn is not None
        rows = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def _ensure_column(self, table_name: str, column_name: str, definition: str) -> bool:
        assert self._conn is not None
        if column_name in self._table_columns(table_name):
            return False
        self._conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
        return True

    def _migrate_legacy_schema(self) -> None:
        """Apply lightweight schema migrations for existing SQLite files."""
        assert self._conn is not None
        changed = False

        changed = self._ensure_column("admins", "id", "TEXT") or changed
        changed = self._ensure_column("admins", "role", "TEXT NOT NULL DEFAULT 'admin'") or changed
        changed = self._ensure_column("admins", "last_login", "TEXT") or changed

        rows_without_id = self._conn.execute("SELECT rowid FROM admins WHERE id IS NULL OR id = ''").fetchall()
        for row in rows_without_id:
            self._conn.execute(
                "UPDATE admins SET id = ? WHERE rowid = ?",
                (f"adm_{uuid.uuid4().hex[:12]}", int(row["rowid"])),
            )
            changed = True

        updated_roles = self._conn.execute(
            "UPDATE admins SET role = 'admin' WHERE role IS NULL OR TRIM(role) = ''"
        )
        if updated_roles.rowcount and updated_roles.rowcount > 0:
            changed = True

        if changed:
            self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_admins_username ON admins(username)")
            self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_admins_id ON admins(id)")
            self._conn.commit()

    def _seed_default_admin(self) -> None:
        assert self._conn is not None
        username = os.getenv("ADMIN_DEFAULT_USERNAME", "admin")
        password = os.getenv("ADMIN_DEFAULT_PASSWORD", "trongdongdongson")
        role = os.getenv("ADMIN_DEFAULT_ROLE", "admin")

        found = self._conn.execute("SELECT id FROM admins WHERE username = ?", (username,)).fetchone()
        if found:
            return
        admin_id = f"adm_{uuid.uuid4().hex[:12]}"
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        self._conn.execute(
            "INSERT INTO admins (id, username, password_hash, role, last_login) VALUES (?, ?, ?, ?, ?)",
            (admin_id, username, password_hash, role, None),
        )
        self._conn.commit()

    def login(self, username: str, password: str, ip: str) -> AdminLoginResponse:
        self.initialize()
        self._validate_bruteforce(ip)

        assert self._conn is not None
        row = self._conn.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if not row:
            self._mark_failed_attempt(ip)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sai mật khẩu rồi cưng")

        hashed = row["password_hash"].encode("utf-8")
        if not bcrypt.checkpw(password.encode("utf-8"), hashed):
            self._mark_failed_attempt(ip)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sai mật khẩu rồi cưng")

        self._clear_failed_attempts(ip)
        admin_id = str(row["id"]) if row["id"] else f"adm_{uuid.uuid4().hex[:12]}"
        if not row["id"]:
            self._conn.execute("UPDATE admins SET id = ? WHERE username = ?", (admin_id, username))
        now = datetime.now(timezone.utc)
        self._conn.execute("UPDATE admins SET last_login = ? WHERE id = ?", (now.isoformat(), admin_id))
        self._conn.commit()

        access_token, refresh_token, csrf_token, expires_in = self._issue_tokens(admin_id, str(row["role"]))
        self.write_audit(admin_id, "login", admin_id, ip, "")

        return AdminLoginResponse(
            accessToken=access_token,
            refreshToken=refresh_token,
            csrfToken=csrf_token,
            expiresIn=expires_in,
            admin=AdminContext(
                adminId=admin_id,
                role=str(row["role"]),
                permissions=ROLE_PERMISSIONS.get(str(row["role"]), []),
            ),
        )

    def refresh(self, refresh_token: str) -> AdminLoginResponse:
        self.initialize()
        payload = jwt.decode(refresh_token, self._refresh_secret, algorithms=["HS256"])
        token_id = payload.get("tokenId")
        admin_id = payload.get("adminId")
        role = payload.get("role")
        if not token_id or not admin_id or not role:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        assert self._conn is not None
        row = self._conn.execute("SELECT revoked, expires_at FROM refresh_tokens WHERE token_id = ?", (token_id,)).fetchone()
        if not row or int(row["revoked"]) == 1:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")
        if datetime.fromisoformat(str(row["expires_at"])) < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

        self._conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_id = ?", (token_id,))
        self._conn.commit()

        access_token, next_refresh, csrf_token, expires_in = self._issue_tokens(str(admin_id), str(role))
        return AdminLoginResponse(
            accessToken=access_token,
            refreshToken=next_refresh,
            csrfToken=csrf_token,
            expiresIn=expires_in,
            admin=AdminContext(adminId=str(admin_id), role=str(role), permissions=ROLE_PERMISSIONS.get(str(role), [])),
        )

    def verify_access_token(self, token: str) -> Dict[str, Any]:
        self.initialize()
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

        role = str(payload.get("role", ""))
        if role not in ROLE_PERMISSIONS:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid role")
        return payload

    def revoke_refresh_token(self, refresh_token: str) -> None:
        self.initialize()
        try:
            payload = jwt.decode(refresh_token, self._refresh_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        token_id = payload.get("tokenId")
        if not token_id:
            return
        assert self._conn is not None
        self._conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_id = ?", (token_id,))
        self._conn.commit()

    def write_audit(self, admin_id: str, action: str, target_id: str, ip: str, details: str) -> None:
        self.initialize()
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO admin_actions (id, admin_id, action, target_id, ip, details, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"act_{uuid.uuid4().hex[:16]}",
                admin_id,
                action,
                target_id,
                ip,
                details,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def _issue_tokens(self, admin_id: str, role: str) -> Tuple[str, str, str, int]:
        now = datetime.now(timezone.utc)
        access_exp = now + timedelta(minutes=self._access_exp_minutes)
        refresh_exp = now + timedelta(days=self._refresh_exp_days)
        csrf_token = secrets.token_urlsafe(24)
        session_id = f"sid_{uuid.uuid4().hex[:18]}"

        access_payload = {
            "adminId": admin_id,
            "role": role,
            "permissions": ROLE_PERMISSIONS.get(role, []),
            "sessionId": session_id,
            "csrf": csrf_token,
            "iat": int(now.timestamp()),
            "exp": int(access_exp.timestamp()),
        }
        access_token = jwt.encode(access_payload, self._jwt_secret, algorithm="HS256")

        refresh_token_id = f"rt_{uuid.uuid4().hex[:20]}"
        refresh_payload = {
            "tokenId": refresh_token_id,
            "adminId": admin_id,
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(refresh_exp.timestamp()),
        }
        refresh_token = jwt.encode(refresh_payload, self._refresh_secret, algorithm="HS256")

        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO refresh_tokens (token_id, admin_id, expires_at, revoked) VALUES (?, ?, ?, 0)",
            (refresh_token_id, admin_id, refresh_exp.isoformat()),
        )
        self._conn.commit()

        return access_token, refresh_token, csrf_token, int(self._access_exp_minutes * 60)

    def _validate_bruteforce(self, ip: str, max_attempts: int = 5, window_seconds: int = 900) -> None:
        q = self._login_attempts[ip]
        now = time.time()
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again later.",
            )

    def _mark_failed_attempt(self, ip: str) -> None:
        self._login_attempts[ip].append(time.time())

    def _clear_failed_attempts(self, ip: str) -> None:
        self._login_attempts.pop(ip, None)


_service: Optional[AdminAuthService] = None


def get_admin_auth_service() -> AdminAuthService:
    global _service
    if _service is None:
        _service = AdminAuthService()
    return _service
