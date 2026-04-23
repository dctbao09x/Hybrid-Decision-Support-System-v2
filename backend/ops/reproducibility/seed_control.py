"""
SeedController — deterministic seed management for reproducible runs.

Sets and tracks random seeds across ALL RNG sources:
  - Python stdlib `random`
  - `os.environ["PYTHONHASHSEED"]`
  - NumPy (optional)
  - PyTorch (optional)

Generates deterministic seeds from run_id so re-runs with the same
run_id always produce the same random sequence.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  Data models
# ─────────────────────────────────────────────────────────────
@dataclass
class SeedState:
    """Captured RNG state — enough to restore exact random sequence."""

    seed: int
    python_random_state: Optional[Any] = None
    numpy_state: Optional[Any] = None
    torch_state: Optional[Any] = None
    pythonhashseed: Optional[str] = None
    sources_set: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe serialization (RNG states omitted — not JSON-safe)."""
        return {
            "seed": self.seed,
            "pythonhashseed": self.pythonhashseed,
            "sources_set": self.sources_set,
        }


# ─────────────────────────────────────────────────────────────
#  SeedController
# ─────────────────────────────────────────────────────────────
class SeedController:
    """
    Manage deterministic seeding for reproducible pipeline runs.

    Usage
    -----
    >>> ctrl = SeedController()
    >>> state = ctrl.set_seeds(42)          # explicit seed
    >>> state = ctrl.set_from_run_id("r1")  # deterministic from run_id
    >>> captured = ctrl.capture_state()
    >>> ctrl.restore_state(captured)        # exact replay
    """

    # Upper bound for generated seeds (2^32 − 1)
    MAX_SEED = 2**32 - 1

    def __init__(self) -> None:
        self._current_seed: Optional[int] = None
        self._last_state: Optional[SeedState] = None

    # ── Public API ────────────────────────────────────────────

    def generate_seed(self, run_id: str) -> int:
        """
        Derive a deterministic seed from a run_id string.

        Uses SHA-256 truncated to 32 bits so the same run_id
        always produces the same seed, regardless of platform.
        """
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % (self.MAX_SEED + 1)

    def set_seeds(self, seed: int) -> SeedState:
        """
        Set ALL available RNG sources to *seed*.

        Returns a SeedState recording which sources were set.
        """
        self._current_seed = seed
        sources: Dict[str, bool] = {}

        # 1. Python stdlib
        random.seed(seed)
        sources["python_random"] = True

        # 2. PYTHONHASHSEED (affects dict/set ordering in CPython)
        os.environ["PYTHONHASHSEED"] = str(seed)
        sources["pythonhashseed"] = True

        # 3. NumPy (optional)
        try:
            import numpy as np

            np.random.seed(seed)
            sources["numpy"] = True
        except ImportError:
            sources["numpy"] = False

        # 4. PyTorch (optional)
        try:
            import torch

            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
                sources["torch_cuda"] = True
            sources["torch"] = True
        except ImportError:
            sources["torch"] = False

        state = SeedState(
            seed=seed,
            pythonhashseed=str(seed),
            sources_set=sources,
        )
        self._last_state = state
        logger.info(f"Seeds set: seed={seed}, sources={sources}")
        return state

    def set_from_run_id(self, run_id: str) -> SeedState:
        """Derive seed from run_id and set all RNG sources."""
        seed = self.generate_seed(run_id)
        return self.set_seeds(seed)

    def capture_state(self) -> SeedState:
        """
        Capture current RNG state from all available sources.

        The captured state can be restored later for exact replay.
        """
        seed = self._current_seed or 0
        sources: Dict[str, bool] = {}

        # Python random
        py_state = random.getstate()
        sources["python_random"] = True

        # NumPy
        np_state = None
        try:
            import numpy as np

            np_state = np.random.get_state()
            sources["numpy"] = True
        except ImportError:
            sources["numpy"] = False

        # PyTorch
        torch_state = None
        try:
            import torch

            torch_state = torch.random.get_rng_state()
            sources["torch"] = True
        except ImportError:
            sources["torch"] = False

        state = SeedState(
            seed=seed,
            python_random_state=py_state,
            numpy_state=np_state,
            torch_state=torch_state,
            pythonhashseed=os.environ.get("PYTHONHASHSEED"),
            sources_set=sources,
        )
        self._last_state = state
        return state

    def restore_state(self, state: SeedState) -> None:
        """
        Restore RNG state from a previously captured SeedState.

        This enables exact replay of random sequences.
        """
        self._current_seed = state.seed

        # Python random
        if state.python_random_state is not None:
            random.setstate(state.python_random_state)

        # PYTHONHASHSEED (note: only effective before interpreter start,
        # but we set it for child-process inheritance)
        if state.pythonhashseed is not None:
            os.environ["PYTHONHASHSEED"] = state.pythonhashseed

        # NumPy
        if state.numpy_state is not None:
            try:
                import numpy as np

                np.random.set_state(state.numpy_state)
            except ImportError:
                pass

        # PyTorch
        if state.torch_state is not None:
            try:
                import torch

                torch.random.set_rng_state(state.torch_state)
            except ImportError:
                pass

        logger.info(f"RNG state restored: seed={state.seed}")

    @property
    def current_seed(self) -> Optional[int]:
        return self._current_seed

    @property
    def last_state(self) -> Optional[SeedState]:
        return self._last_state
