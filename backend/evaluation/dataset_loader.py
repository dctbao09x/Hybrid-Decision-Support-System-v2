# backend/evaluation/dataset_loader.py
"""
Dataset Loader Layer
====================
Responsibilities:
  • Validate CSV schema against expected columns
  • Load data with type checking
  • Handle missing values (impute / drop)
  • Encode target labels (LabelEncoder)
  • Export NumPy arrays ready for sklearn

All operations are logged via the central logger.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger("ml_evaluation.dataset_loader")

# ── Required schema ──────────────────────────────────────────────
REQUIRED_COLUMNS = [
    "math_score",
    "physics_score",
    "interest_it",
    "logic_score",
    "target_career",
]

FEATURE_COLUMNS = [
    "math_score",
    "physics_score",
    "interest_it",
    "logic_score",
]

TARGET_COLUMN = "target_career"


class DatasetValidationError(Exception):
    """Raised when the dataset fails schema or integrity checks."""


class DatasetLoader:
    """
    Load, validate, preprocess, and export training data.

    Usage::

        loader = DatasetLoader(path="data/training.csv")
        loader.load()
        X, y, label_encoder = loader.export_arrays()
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._df: Optional[pd.DataFrame] = None
        self._label_encoder: Optional[LabelEncoder] = None
        self._is_loaded = False

    # ──────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────

    def validate_schema(self) -> None:
        """Check that the CSV exists and contains the required columns."""
        if not self._path.exists():
            raise DatasetValidationError(
                f"Dataset file not found: {self._path}"
            )

        # Peek at header only
        try:
            header = pd.read_csv(self._path, nrows=0).columns.tolist()
        except Exception as exc:
            raise DatasetValidationError(
                f"Cannot read CSV header: {exc}"
            ) from exc

        missing = set(REQUIRED_COLUMNS) - set(header)
        if missing:
            raise DatasetValidationError(
                f"Missing required columns: {sorted(missing)}"
            )
        logger.info("Schema validation passed — columns: %s", header)

    def load(self) -> pd.DataFrame:
        """Load CSV into a DataFrame after validating the schema."""
        self.validate_schema()

        self._df = pd.read_csv(self._path)
        logger.info(
            "Loaded dataset: %d rows × %d cols from %s",
            len(self._df), len(self._df.columns), self._path,
        )

        # Integrity checks
        if len(self._df) < 10:
            raise DatasetValidationError(
                f"Dataset too small ({len(self._df)} rows); need ≥ 10."
            )

        dup_count = self._df.duplicated().sum()
        if dup_count > 0:
            logger.warning("Dropping %d duplicate rows", dup_count)
            self._df = self._df.drop_duplicates().reset_index(drop=True)

        self.handle_missing()
        self._cast_feature_types()
        self._is_loaded = True
        return self._df

    def handle_missing(self) -> None:
        """Impute or drop rows with missing values."""
        if self._df is None:
            raise DatasetValidationError("Call load() first.")

        missing_before = self._df.isnull().sum().sum()
        if missing_before == 0:
            logger.info("No missing values detected.")
            return

        # Drop rows where the target is missing (cannot impute labels)
        target_nulls = self._df[TARGET_COLUMN].isnull().sum()
        if target_nulls:
            logger.warning(
                "Dropping %d rows with missing target", target_nulls
            )
            self._df = self._df.dropna(subset=[TARGET_COLUMN])

        # Impute numeric features with column median
        for col in FEATURE_COLUMNS:
            n_null = self._df[col].isnull().sum()
            if n_null > 0:
                median_val = self._df[col].median()
                self._df[col] = self._df[col].fillna(median_val)
                logger.info(
                    "Imputed %d missing in '%s' with median=%.2f",
                    n_null, col, median_val,
                )

        self._df = self._df.reset_index(drop=True)
        logger.info(
            "After missing-value handling: %d rows remain", len(self._df)
        )

    def encode_label(self) -> LabelEncoder:
        """Fit a LabelEncoder on the target column and transform in-place."""
        if self._df is None:
            raise DatasetValidationError("Call load() first.")

        self._label_encoder = LabelEncoder()
        self._df["target_encoded"] = self._label_encoder.fit_transform(
            self._df[TARGET_COLUMN]
        )
        classes = list(self._label_encoder.classes_)
        logger.info(
            "Label encoding complete — %d classes: %s",
            len(classes), classes,
        )
        return self._label_encoder

    def export_arrays(self) -> Tuple[np.ndarray, np.ndarray, LabelEncoder]:
        """
        Return (X, y, label_encoder) as NumPy arrays.

        Automatically encodes labels if not yet done.
        """
        if not self._is_loaded:
            raise DatasetValidationError("Call load() before export_arrays().")

        if self._label_encoder is None:
            self.encode_label()

        X = self._df[FEATURE_COLUMNS].values.astype(np.float64)
        y = self._df["target_encoded"].values.astype(np.int64)

        logger.info("Exported arrays — X shape: %s, y shape: %s", X.shape, y.shape)
        return X, y, self._label_encoder  # type: ignore[return-value]

    # ──────────────────────────────────────────────────────────────
    #  Introspection
    # ──────────────────────────────────────────────────────────────

    @property
    def dataframe(self) -> Optional[pd.DataFrame]:
        return self._df

    @property
    def label_encoder(self) -> Optional[LabelEncoder]:
        return self._label_encoder

    @property
    def num_samples(self) -> int:
        return len(self._df) if self._df is not None else 0

    @property
    def num_classes(self) -> int:
        if self._label_encoder is None:
            return 0
        return len(self._label_encoder.classes_)

    # ──────────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────────

    def _cast_feature_types(self) -> None:
        """Ensure feature columns are numeric."""
        for col in FEATURE_COLUMNS:
            self._df[col] = pd.to_numeric(self._df[col], errors="coerce")
        coerced_nulls = self._df[FEATURE_COLUMNS].isnull().sum().sum()
        if coerced_nulls:
            logger.warning(
                "%d values coerced to NaN during type cast — re-imputing",
                coerced_nulls,
            )
            self.handle_missing()
