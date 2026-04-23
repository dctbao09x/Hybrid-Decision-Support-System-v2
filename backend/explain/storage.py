from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.explain.models import ExplanationRecord, RuleFire, EvidenceItem, TraceEdge, TraceGraph
from backend.explain.unified_schema import UnifiedExplanation


def _canonical(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ExplanationStorage:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or Path("storage/explanations.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._initialized = False

    async def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
            self._initialized = True

    def _create_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS explanations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                explanation_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                kb_version TEXT NOT NULL,
                rule_path TEXT NOT NULL,
                weights TEXT NOT NULL,
                evidence TEXT NOT NULL,
                confidence REAL NOT NULL,
                feature_snapshot TEXT NOT NULL,
                prediction TEXT,
                created_at TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                prev_hash TEXT,
                is_deleted INTEGER DEFAULT 0,
                legal_hold INTEGER DEFAULT 0,
                weight_version TEXT,
                breakdown TEXT,
                per_component_contributions TEXT,
                reasoning TEXT,
                input_summary TEXT,
                stage3_input_hash TEXT,
                stage3_output_hash TEXT,
                explanation_hash TEXT
            )
            """
        )

        self._migrate_unified_columns()

        # Migration: add legal_hold column if not exists (for existing DBs)
        try:
            self._conn.execute("ALTER TABLE explanations ADD COLUMN legal_hold INTEGER DEFAULT 0")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS explanation_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                trace_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_expl_trace ON explanations(trace_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_expl_created ON explanations(created_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_trace ON trace_graph_edges(trace_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_nodes ON trace_graph_edges(source, target)")
        self._conn.commit()

    async def append_record(self, record: ExplanationRecord) -> ExplanationRecord:
        if not self._initialized:
            await self.initialize()

        with self._lock:
            prev_hash = self._get_last_hash()
            next_id = self._conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM explanations"
            ).fetchone()["next_id"]
            explanation_id = f"exp-{int(next_id):010d}"
            record.explanation_id = explanation_id
            payload = record.to_dict()
            payload["prev_hash"] = prev_hash
            record_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

            cursor = self._conn.execute(
                """
                INSERT INTO explanations
                (explanation_id, trace_id, model_id, kb_version, rule_path, weights,
                 evidence, confidence, feature_snapshot, prediction, created_at,
                 record_hash, prev_hash, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    explanation_id,
                    record.trace_id,
                    record.model_id,
                    record.kb_version,
                    _canonical({"rule_path": [r.to_dict() for r in record.rule_path]}),
                    _canonical(record.weights),
                    _canonical({"evidence": [e.to_dict() for e in record.evidence]}),
                    float(record.confidence),
                    _canonical(record.feature_snapshot),
                    _canonical(record.prediction or {}),
                    record.created_at,
                    record_hash,
                    prev_hash,
                ),
            )
            _ = cursor.lastrowid
            self._conn.commit()

            record.explanation_id = explanation_id
            record.record_hash = record_hash  # surface chain-hash to caller
            self._log_action("append_explanation", record.trace_id, {"explanation_id": explanation_id})
            return record

    async def append_graph_edges(self, trace_id: str, edges: List[TraceEdge]) -> None:
        if not self._initialized:
            await self.initialize()

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO trace_graph_edges (trace_id, source, target, edge_type, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        trace_id,
                        edge.source,
                        edge.target,
                        edge.edge_type,
                        _canonical(edge.metadata),
                        now,
                    )
                    for edge in edges
                ],
            )
            self._conn.commit()
            self._log_action("append_graph", trace_id, {"edges": len(edges)})

    async def get_by_trace_id(self, trace_id: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM explanations
                WHERE trace_id = ? AND is_deleted = 0
                ORDER BY id DESC LIMIT 1
                """,
                (trace_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return self._row_to_record(row)

    async def get_history(self, from_date: Optional[str], to_date: Optional[str], limit: int = 500) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()

        from_filter = from_date or (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
        to_filter = to_date or datetime.now(timezone.utc).isoformat()

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM explanations
                WHERE created_at >= ? AND created_at <= ? AND is_deleted = 0
                ORDER BY id DESC
                LIMIT ?
                """,
                (from_filter, to_filter, int(limit)),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    async def get_trace_graph(self, trace_id: str) -> TraceGraph:
        if not self._initialized:
            await self.initialize()

        with self._lock:
            cursor = self._conn.execute(
                "SELECT source, target, edge_type, metadata FROM trace_graph_edges WHERE trace_id = ? ORDER BY id ASC",
                (trace_id,),
            )
            rows = cursor.fetchall()

        edges: List[TraceEdge] = []
        node_ids = set()
        adjacency: Dict[str, List[str]] = {}

        for row in rows:
            edge = TraceEdge(
                source=row["source"],
                target=row["target"],
                edge_type=row["edge_type"],
                metadata=json.loads(row["metadata"] or "{}"),
            )
            edges.append(edge)
            node_ids.add(edge.source)
            node_ids.add(edge.target)
            adjacency.setdefault(edge.source, []).append(edge.target)

        nodes = [{"id": node_id} for node_id in sorted(node_ids)]
        return TraceGraph(trace_id=trace_id, nodes=nodes, edges=edges, adjacency=adjacency)

    async def get_stats(self) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()

        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM explanations WHERE is_deleted = 0"
            ).fetchone()[0]
            unique_traces = self._conn.execute(
                "SELECT COUNT(DISTINCT trace_id) FROM explanations WHERE is_deleted = 0"
            ).fetchone()[0]
            min_created = self._conn.execute(
                "SELECT MIN(created_at) FROM explanations WHERE is_deleted = 0"
            ).fetchone()[0]
            max_created = self._conn.execute(
                "SELECT MAX(created_at) FROM explanations WHERE is_deleted = 0"
            ).fetchone()[0]

        return {
            "total_records": int(total),
            "unique_traces": int(unique_traces),
            "range": {
                "from": min_created,
                "to": max_created,
            },
            "tamper_ok": await self.verify_integrity(),
        }

    async def verify_integrity(self, trace_id: Optional[str] = None) -> bool:
        if not self._initialized:
            await self.initialize()

        where = "WHERE is_deleted = 0"
        params: List[Any] = []
        if trace_id:
            where = "WHERE is_deleted = 0 AND trace_id = ?"
            params.append(trace_id)

        with self._lock:
            cursor = self._conn.execute(
                f"SELECT * FROM explanations {where} ORDER BY id ASC",
                params,
            )
            rows = cursor.fetchall()

        last_hash = ""
        for row in rows:
            payload = {
                "explanation_id": row["explanation_id"],
                "trace_id": row["trace_id"],
                "model_id": row["model_id"],
                "kb_version": row["kb_version"],
                "rule_path": json.loads(row["rule_path"] or "{}").get("rule_path", []),
                "weights": json.loads(row["weights"] or "{}"),
                "evidence": json.loads(row["evidence"] or "{}").get("evidence", []),
                "confidence": float(row["confidence"]),
                "feature_snapshot": json.loads(row["feature_snapshot"] or "{}"),
                "prediction": json.loads(row["prediction"] or "{}"),
                "created_at": row["created_at"],
                "prev_hash": row["prev_hash"] or "",
            }
            if payload["prev_hash"] != last_hash:
                return False
            recomputed = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
            if recomputed != row["record_hash"]:
                return False
            last_hash = row["record_hash"]

        return True

    async def cleanup_expired(self, retention_days: int = 180) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(retention_days))).isoformat()
        with self._lock:
            # Count records that would be deleted but are on legal hold
            skipped_cursor = self._conn.execute(
                """
                SELECT COUNT(*) FROM explanations
                WHERE created_at < ? AND is_deleted = 0 AND legal_hold = 1
                """,
                (cutoff,),
            )
            skipped_legal_hold = skipped_cursor.fetchone()[0]

            # Only delete records that are NOT on legal hold
            cursor = self._conn.execute(
                """
                UPDATE explanations
                SET is_deleted = 1
                WHERE created_at < ? AND is_deleted = 0 AND legal_hold = 0
                """,
                (cutoff,),
            )
            deleted = cursor.rowcount
            self._conn.commit()

        details = {
            "deleted": int(deleted),
            "skipped_legal_hold": int(skipped_legal_hold),
            "retention_days": int(retention_days),
            "cutoff": cutoff,
        }
        self._log_action("retention_cleanup", None, details)
        return details

    async def backtrack(self, trace_id: str, target_node: str) -> List[str]:
        graph = await self.get_trace_graph(trace_id)
        reverse_adj: Dict[str, List[str]] = {}
        for source, targets in graph.adjacency.items():
            for target in targets:
                reverse_adj.setdefault(target, []).append(source)

        path: List[str] = [target_node]
        current = target_node
        visited = set()
        while current in reverse_adj:
            parents = reverse_adj[current]
            if not parents:
                break
            parent = parents[0]
            if parent in visited:
                break
            visited.add(parent)
            path.append(parent)
            current = parent
        return list(reversed(path))

    # ─────────────────────────────────────────────────────────────────────────
    # Unified schema support
    # ─────────────────────────────────────────────────────────────────────────

    def _migrate_unified_columns(self) -> None:
        """
        Idempotent migration: add the eight columns introduced by UnifiedExplanation.
        Safe to call on both fresh and legacy databases.
        """
        new_columns = [
            ("weight_version", "TEXT"),
            ("breakdown", "TEXT"),
            ("per_component_contributions", "TEXT"),
            ("reasoning", "TEXT"),
            ("input_summary", "TEXT"),
            ("stage3_input_hash", "TEXT"),
            ("stage3_output_hash", "TEXT"),
            ("explanation_hash", "TEXT"),
        ]
        for col_name, col_type in new_columns:
            try:
                self._conn.execute(
                    f"ALTER TABLE explanations ADD COLUMN {col_name} {col_type}"
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

    async def append_unified(
        self, unified: UnifiedExplanation
    ) -> tuple["UnifiedExplanation", str, str]:
        """
        Persist a UnifiedExplanation to the explanations table.

        Architecture
        ------------
        Delegates to ``append_record()`` for the canonical hash-chain write
        (legacy-compatible fields + crypto chain link), then UPDATEs the same
        row with the eight UnifiedExplanation-only columns.  This guarantees:

        * ``append_record()`` is the single, authoritative chain-hash writer.
        * ``verify_integrity()`` sees a correctly chained row regardless of
          which insertion path was used.
        * Unified schema fields are never orphaned — they co-exist in the same
          row as the chain-hash fields.

        Returns
        -------
        tuple[UnifiedExplanation, str, str]
            ``(unified, record_hash, explanation_id)``
            ``record_hash`` — SHA-256 chain link for the caller to embed in the
            Stage-9 pipeline artifact.
            ``explanation_id`` — storage-generated row identifier.
        """
        if not self._initialized:
            await self.initialize()

        # ── Step 1: chain-hash write via append_record() ─────────────────────
        record = ExplanationRecord.from_unified(unified)
        stored_record = await self.append_record(record)
        record_hash = stored_record.record_hash
        explanation_id = stored_record.explanation_id

        # ── Step 2: enrich the same row with UnifiedExplanation columns ───────
        with self._lock:
            self._conn.execute(
                """
                UPDATE explanations SET
                    weight_version             = ?,
                    breakdown                  = ?,
                    per_component_contributions = ?,
                    reasoning                  = ?,
                    input_summary              = ?,
                    stage3_input_hash          = ?,
                    stage3_output_hash         = ?,
                    explanation_hash           = ?
                WHERE explanation_id = ?
                """,
                (
                    unified.weight_version,
                    _canonical(dict(unified.breakdown)),
                    _canonical(dict(unified.per_component_contributions)),
                    _canonical(list(unified.reasoning)),
                    _canonical(dict(unified.input_summary)),
                    unified.stage3_input_hash,
                    unified.stage3_output_hash,
                    unified.explanation_hash,
                    explanation_id,
                ),
            )
            self._conn.commit()

        self._log_action(
            "append_unified",
            unified.trace_id,
            {
                "explanation_id": explanation_id,
                "record_hash": record_hash[:16],
                "explanation_hash": unified.explanation_hash[:16],
            },
        )
        return unified, record_hash, explanation_id

    async def get_unified_by_trace_id(self, trace_id: str) -> Optional[UnifiedExplanation]:
        """
        Retrieve the most recent UnifiedExplanation for *trace_id*.

        Returns None if no matching row exists or if the most recent row was
        inserted via the legacy ``append_record()`` path (no explanation_hash).
        """
        if not self._initialized:
            await self.initialize()

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM explanations
                WHERE trace_id = ? AND is_deleted = 0
                ORDER BY id DESC LIMIT 1
                """,
                (trace_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

        return self._row_to_unified(row)

    def _row_to_unified(self, row: sqlite3.Row) -> UnifiedExplanation:
        """
        Reconstruct a UnifiedExplanation from a raw SQLite row.

        Handles both unified rows and legacy rows (NULL new columns) by
        using sentinel empty values for missing fields.
        """
        keys = row.keys()

        def _col(name: str, default: Any = None) -> Any:
            return row[name] if name in keys and row[name] is not None else default

        def _load_json(name: str, default: Any) -> Any:
            raw = _col(name)
            if raw is None:
                return default
            if isinstance(raw, (dict, list)):
                return raw
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return default

        # Reconstruct rule_path from the wrapped column (legacy format)
        rule_path = _load_json("rule_path", [])
        if isinstance(rule_path, dict) and "rule_path" in rule_path:
            rule_path = rule_path["rule_path"]

        # Reconstruct evidence from the wrapped column (legacy format)
        evidence = _load_json("evidence", [])
        if isinstance(evidence, dict) and "evidence" in evidence:
            evidence = evidence["evidence"]

        row_dict = {
            "trace_id": _col("trace_id", ""),
            "model_id": _col("model_id", ""),
            "kb_version": _col("kb_version", ""),
            "weight_version": _col("weight_version") or "",
            "breakdown": _load_json("breakdown", {}),
            "per_component_contributions": _load_json("per_component_contributions", {}),
            "reasoning": _load_json("reasoning", []),
            "input_summary": _load_json("input_summary", {}),
            "feature_snapshot": _load_json("feature_snapshot", {}),
            "rule_path": rule_path,
            "weights": _load_json("weights", {}),
            "evidence": evidence,
            "confidence": float(_col("confidence") or 0.0),
            "prediction": _load_json("prediction", {}),
            "stage3_input_hash": _col("stage3_input_hash") or "",
            "stage3_output_hash": _col("stage3_output_hash") or "",
            "explanation_hash": _col("explanation_hash") or "",
        }
        return UnifiedExplanation.from_storage_row(row_dict)

    def _get_last_hash(self) -> str:
        cursor = self._conn.execute(
            "SELECT record_hash FROM explanations ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row["record_hash"] if row else ""

    def _row_to_record(self, row: sqlite3.Row) -> Dict[str, Any]:
        rule_items = json.loads(row["rule_path"] or "{}").get("rule_path", [])
        evidence_items = json.loads(row["evidence"] or "{}").get("evidence", [])
        rule_path = [RuleFire(**item).to_dict() for item in rule_items]
        evidence = [EvidenceItem(**item).to_dict() for item in evidence_items]

        return {
            "explanation_id": row["explanation_id"],
            "trace_id": row["trace_id"],
            "model_id": row["model_id"],
            "kb_version": row["kb_version"],
            "rule_path": rule_path,
            "weights": json.loads(row["weights"] or "{}"),
            "evidence": evidence,
            "confidence": float(row["confidence"]),
            "feature_snapshot": json.loads(row["feature_snapshot"] or "{}"),
            "prediction": json.loads(row["prediction"] or "{}"),
            "created_at": row["created_at"],
            "legal_hold": bool(row["legal_hold"]) if "legal_hold" in row.keys() else False,
            "integrity": {
                "record_hash": row["record_hash"],
                "prev_hash": row["prev_hash"],
            },
        }

    def _log_action(self, action: str, trace_id: Optional[str], details: Dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO explanation_audit (action, trace_id, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                action,
                trace_id,
                _canonical(details),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    async def set_legal_hold(self, trace_id: str, hold: bool = True, user: str = "system") -> Dict[str, Any]:
        """Set or clear legal hold on a trace."""
        if not self._initialized:
            await self.initialize()

        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE explanations
                SET legal_hold = ?
                WHERE trace_id = ? AND is_deleted = 0
                """,
                (1 if hold else 0, trace_id),
            )
            affected = cursor.rowcount
            self._conn.commit()

        action = "set_legal_hold" if hold else "clear_legal_hold"
        self._log_action(action, trace_id, {"user": user, "affected_rows": affected})

        return {
            "trace_id": trace_id,
            "legal_hold": hold,
            "affected_rows": affected,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_legal_hold_status(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get legal hold status for a trace."""
        if not self._initialized:
            await self.initialize()

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT trace_id, legal_hold, created_at
                FROM explanations
                WHERE trace_id = ? AND is_deleted = 0
                ORDER BY id DESC LIMIT 1
                """,
                (trace_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return {
                "trace_id": row["trace_id"],
                "legal_hold": bool(row["legal_hold"]) if row["legal_hold"] is not None else False,
                "created_at": row["created_at"],
            }

    async def list_legal_holds(self) -> List[Dict[str, Any]]:
        """List all traces with active legal holds."""
        if not self._initialized:
            await self.initialize()

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT DISTINCT trace_id, created_at
                FROM explanations
                WHERE legal_hold = 1 AND is_deleted = 0
                ORDER BY created_at DESC
                """,
            )
            return [
                {"trace_id": row["trace_id"], "created_at": row["created_at"]}
                for row in cursor.fetchall()
            ]


_storage_singleton: Optional[ExplanationStorage] = None


def get_explanation_storage() -> ExplanationStorage:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = ExplanationStorage()
    return _storage_singleton
