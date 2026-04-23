"""
Data Pipeline Module - Vietnamese Recruitment Data Collection & Processing

This module handles:
- Data collection from multiple sources (VietnamWorks, TopCV)
- Data validation and cleaning
- Data enrichment and classification
- Version management and storage
- Integration with scoring engine
- Monitoring and logging

Version: 1.0.0
"""

from .pipeline_manager import PipelineManager
from .config import PipelineConfig

__version__ = "1.0.0"
__all__ = ["PipelineManager", "PipelineConfig"]
