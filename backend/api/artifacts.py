# backend/api/artifacts.py
"""
Pipeline Artifact Schema and Utilities
======================================

ARTIFACT TRACE PROPAGATION IMPLEMENTATION

Provides standardized artifact schema for all pipeline stages.
Every stage produces an artifact with:
  - decision_trace_id: Unique trace identifier
  - stage_name: Name of the pipeline stage
  - stage_timestamp: ISO8601 timestamp
  - stage_hash: SHA256 hash of payload
  - payload: Stage-specific data

INVARIANTS:
  - trace_id is IMMUTABLE once set
  - stage_hash is computed from payload only
  - No stage can overwrite previous trace_id
  
USAGE:
  artifact = PipelineArtifact.create(
      trace_id="dec-abc123",
      stage_name="input_normalize",
      payload={"skills": [...], "interests": [...]}
  )
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api.artifacts")


def compute_stage_hash(payload: Dict[str, Any]) -> str:
    """
    Compute SHA256 hash of stage payload.
    
    Args:
        payload: Stage data to hash.
        
    Returns:
        Lowercase hex SHA256 hash.
    """
    # Deterministic JSON serialization
    serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


@dataclass
class PipelineArtifact:
    """
    Immutable pipeline stage artifact.
    
    Schema:
    {
        "decision_trace_id": str,
        "stage_name": str,
        "stage_timestamp": iso8601,
        "stage_hash": str,
        "payload": dict
    }
    """
    decision_trace_id: str
    stage_name: str
    stage_timestamp: str
    stage_hash: str
    payload: Dict[str, Any]
    
    # Internal metadata (not serialized by default)
    _previous_artifact: Optional["PipelineArtifact"] = field(default=None, repr=False)
    
    @classmethod
    def create(
        cls,
        trace_id: str,
        stage_name: str,
        payload: Dict[str, Any],
        previous: Optional["PipelineArtifact"] = None,
    ) -> "PipelineArtifact":
        """
        Create a new pipeline artifact.
        
        Args:
            trace_id: Decision trace ID (must start with "dec-" or "test-").
            stage_name: Name of the pipeline stage.
            payload: Stage-specific data.
            previous: Previous artifact in chain (for validation).
            
        Returns:
            New PipelineArtifact instance.
            
        Raises:
            ValueError: If trace_id format is invalid or mismatched.
        """
        # Validate trace_id format
        if not trace_id or not trace_id.startswith(("dec-", "test-")):
            raise ValueError(f"Invalid trace_id format: {trace_id}")
        
        # Validate trace_id consistency with previous artifact
        if previous is not None:
            if previous.decision_trace_id != trace_id:
                raise ValueError(
                    f"Trace ID mismatch: previous={previous.decision_trace_id} "
                    f"current={trace_id}. Cannot overwrite trace_id."
                )
        
        # Compute stage hash
        stage_hash = compute_stage_hash(payload)
        
        # Create timestamp
        timestamp = datetime.now(timezone.utc).isoformat()
        
        artifact = cls(
            decision_trace_id=trace_id,
            stage_name=stage_name,
            stage_timestamp=timestamp,
            stage_hash=stage_hash,
            payload=payload,
            _previous_artifact=previous,
        )
        
        logger.debug(
            f"[ARTIFACT] Created: stage={stage_name} "
            f"trace_id={trace_id} hash={stage_hash[:16]}..."
        )
        
        return artifact
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Export artifact as dictionary (schema-compliant).
        
        Returns:
            Dict matching the required schema.
        """
        return {
            "decision_trace_id": self.decision_trace_id,
            "stage_name": self.stage_name,
            "stage_timestamp": self.stage_timestamp,
            "stage_hash": self.stage_hash,
            "payload": self.payload,
        }
    
    def verify_hash(self) -> bool:
        """
        Verify payload hash matches stored hash.
        
        Returns:
            True if hash matches, False otherwise.
        """
        computed = compute_stage_hash(self.payload)
        return computed == self.stage_hash
    
    def get_chain(self) -> List["PipelineArtifact"]:
        """
        Get full artifact chain from first to current.
        
        Returns:
            List of artifacts in order.
        """
        chain = []
        current: Optional[PipelineArtifact] = self
        while current is not None:
            chain.append(current)
            current = current._previous_artifact
        return list(reversed(chain))


@dataclass
class ArtifactChain:
    """
    Complete artifact chain for a decision pipeline run.
    
    Collects all stage artifacts and provides chain verification.
    """
    trace_id: str
    artifacts: List[PipelineArtifact] = field(default_factory=list)
    
    def add(self, artifact: PipelineArtifact) -> None:
        """
        Add artifact to chain.
        
        Args:
            artifact: Artifact to add.
            
        Raises:
            ValueError: If trace_id doesn't match chain.
        """
        if artifact.decision_trace_id != self.trace_id:
            raise ValueError(
                f"Artifact trace_id mismatch: chain={self.trace_id} "
                f"artifact={artifact.decision_trace_id}"
            )
        self.artifacts.append(artifact)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Export full chain as dictionary.
        
        Returns:
            Dict with metadata and all artifacts.
        """
        return {
            "decision_trace_id": self.trace_id,
            "artifact_count": len(self.artifacts),
            "stages": [a.stage_name for a in self.artifacts],
            "artifacts": [a.to_dict() for a in self.artifacts],
        }
    
    def verify_all(self) -> Dict[str, bool]:
        """
        Verify all artifact hashes in chain.
        
        Returns:
            Dict mapping stage_name to verification result.
        """
        return {a.stage_name: a.verify_hash() for a in self.artifacts}
    
    def compute_chain_root(self) -> str:
        """
        Compute cryptographic root hash of artifact chain.
        
        Algorithm:
            1. Collect all stage_hash values in order
            2. Concatenate hashes
            3. Return sha256(concatenated_hashes)
            
        Returns:
            Hex-encoded SHA256 root hash.
            
        Raises:
            ValueError: If chain is empty.
        """
        if not self.artifacts:
            raise ValueError("Cannot compute root hash of empty artifact chain")
        
        # Collect stage hashes in order
        stage_hashes = [a.stage_hash for a in self.artifacts]
        
        # Concatenate all hashes
        concatenated = "".join(stage_hashes)
        
        # Compute root hash
        root_hash = hashlib.sha256(concatenated.encode('utf-8')).hexdigest()
        
        logger.debug(
            f"[ARTIFACT] Chain root computed: "
            f"stages={len(stage_hashes)} root={root_hash[:16]}..."
        )
        
        return root_hash
    
    def get_stage(self, stage_name: str) -> Optional[PipelineArtifact]:
        """
        Get artifact by stage name.
        
        Args:
            stage_name: Name of stage to find.
            
        Returns:
            Artifact if found, None otherwise.
        """
        for a in self.artifacts:
            if a.stage_name == stage_name:
                return a
        return None


# Stage name constants
STAGE_INPUT_NORMALIZE = "input_normalize"
STAGE_FEATURE_EXTRACTION = "feature_extraction"
STAGE_KB_ALIGNMENT = "kb_alignment"
STAGE_MERGE = "merge"
STAGE_SIMGR_SCORING = "simgr_scoring"
STAGE_DRIFT_CHECK = "drift_check"
STAGE_RULE_ENGINE = "rule_engine"
STAGE_MARKET_DATA = "market_data"
STAGE_EXPLANATION = "explanation"
STAGE_RESPONSE = "response"

ALL_STAGES = [
    STAGE_INPUT_NORMALIZE,
    STAGE_FEATURE_EXTRACTION,
    STAGE_KB_ALIGNMENT,
    STAGE_MERGE,
    STAGE_SIMGR_SCORING,
    STAGE_DRIFT_CHECK,
    STAGE_RULE_ENGINE,
    STAGE_MARKET_DATA,
    STAGE_EXPLANATION,
    STAGE_RESPONSE,
]
