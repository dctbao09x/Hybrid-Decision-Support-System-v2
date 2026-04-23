from __future__ import annotations

from typing import Any, Dict, Optional

from backend.explain.storage import ExplanationStorage
from backend.feedback.governance import RetentionPolicy


class ExplainRetentionManager:
    def __init__(
        self,
        storage: ExplanationStorage,
        retention_days: int = 180,
        governance_policy: Optional[RetentionPolicy] = None,
    ):
        self._storage = storage
        self._governance_policy = governance_policy or RetentionPolicy()
        self._retention_days = max(
            int(retention_days),
            180,
            int(getattr(self._governance_policy, "rejected_feedback_days", 180)),
        )

    @property
    def retention_days(self) -> int:
        return self._retention_days

    async def run_cleanup(self) -> Dict[str, Any]:
        await self._storage.initialize()
        return await self._storage.cleanup_expired(retention_days=self._retention_days)

    async def report(self) -> Dict[str, Any]:
        await self._storage.initialize()
        stats = await self._storage.get_stats()
        return {
            "retention_days": self._retention_days,
            "governance_reference": self._governance_policy.to_dict(),
            "storage_stats": stats,
        }
