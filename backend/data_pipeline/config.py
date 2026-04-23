"""
Pipeline Configuration Module

Handles all configuration for the data pipeline including:
- Data source settings
- Validation rules
- Storage paths
- Archive policies
- Monitoring thresholds
- Logging configuration
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from pathlib import Path
import yaml
import json


@dataclass
class SourceConfig:
    """Configuration for a data source (VietnamWorks, TopCV, etc)"""
    name: str
    enabled: bool = True
    start_url: str = ""
    rate_limit: int = 1000  # requests per day
    timeout: int = 30  # seconds
    retry_max: int = 3
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StorageConfig:
    """Configuration for data storage paths"""
    raw_path: str = "data_storage/raw"
    processed_path: str = "data_storage/processed"
    archive_path: str = "data_storage/archive"
    backup_path: str = "data_storage/backups"
    log_path: str = "data_storage/logs"
    
    def create_directories(self):
        """Create all configured directories"""
        for path in [self.raw_path, self.processed_path, self.archive_path, 
                     self.backup_path, self.log_path]:
            Path(path).mkdir(parents=True, exist_ok=True)


@dataclass
class ValidationConfig:
    """Configuration for data validation rules"""
    min_completeness: float = 0.98  # 98%
    max_duplicates: float = 0.01    # 1%
    max_invalid: float = 0.02       # 2%
    required_fields: list = field(
        default_factory=lambda: [
            "job_title",
            "company_name",
            "salary_range",
            "skills",
            "experience_level",
            "location",
        ]
    )
    field_constraints: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class ArchiveConfig:
    """Configuration for data archival and retention policies"""
    hot_retention_months: int = 12
    warm_retention_years: int = 3
    cold_retention_years: int = 999  # Essentially forever
    compression_format: str = "tar.gz"
    encryption: Optional[str] = "gpg"
    
    archive_schedule: Dict[str, str] = field(
        default_factory=lambda: {
            "hot_archival": "0 0 1 * *",      # 1st of month
            "warm_consolidation": "0 0 1 1,4,7,10 *",  # Quarterly
            "cold_archival": "0 0 1 1 *",      # Yearly
            "delete_expired": "0 0 1 1 *",
        }
    )


@dataclass
class MonitoringConfig:
    """Configuration for monitoring and alerts"""
    log_level: str = "INFO"
    metrics_interval: int = 300  # seconds
    
    # Alert thresholds
    scraper_success_threshold: float = 0.99  # 99%
    validation_pass_threshold: float = 0.98  # 98%
    max_pipeline_runtime: int = 7200  # 2 hours
    max_duplicate_rate: float = 0.01  # 1%
    max_error_rate: float = 0.001  # 0.1%
    
    # Notification
    alert_email: Optional[str] = None
    slack_webhook: Optional[str] = None
    alert_on_warning: bool = True


@dataclass
class PipelineConfig:
    """Main pipeline configuration"""
    version_format: str = "YYYYMM"
    
    # Component configs
    sources: Dict[str, SourceConfig] = field(default_factory=dict)
    storage: StorageConfig = field(default_factory=StorageConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    
    # Scheduling
    schedules: Dict[str, str] = field(
        default_factory=lambda: {
            "scraper": "0 0 * * *",         # Daily at midnight
            "validation": "0 6 * * *",      # 6 AM
            "enrichment": "0 8 * * *",      # 8 AM
            "archival": "0 0 1 * *",        # 1st of month
        }
    )
    
    # Paths
    config_path: str = "config/data_pipeline.yaml"
    log_path: str = "data_storage/logs"
    data_path: str = "data_storage"
    
    # Features
    enable_deduplication: bool = True
    enable_versioning: bool = True
    enable_archival: bool = True
    enable_scoring_integration: bool = True
    
    @classmethod
    def from_yaml(cls, filepath: str) -> "PipelineConfig":
        """Load configuration from YAML file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            config_dict = yaml.safe_load(f)
        
        return cls.from_dict(config_dict)
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PipelineConfig":
        """Create configuration from dictionary"""
        
        # Parse sources
        sources = {}
        for source_name, source_config in config_dict.get("sources", {}).items():
            sources[source_name] = SourceConfig(
                name=source_name,
                **source_config
            )
        
        # Parse storage
        storage_config = StorageConfig(
            **config_dict.get("storage", {})
        )
        
        # Parse validation
        validation_config = ValidationConfig(
            **config_dict.get("validation", {})
        )
        
        # Parse archive
        archive_config = ArchiveConfig(
            **config_dict.get("archive", {})
        )
        
        # Parse monitoring
        monitoring_config = MonitoringConfig(
            **config_dict.get("monitoring", {})
        )
        
        # Create main config
        pipeline_config = cls(
            version_format=config_dict.get("pipeline", {}).get("version_format", "YYYYMM"),
            sources=sources,
            storage=storage_config,
            validation=validation_config,
            archive=archive_config,
            monitoring=monitoring_config,
            schedules=config_dict.get("pipeline", {}).get("schedule", {}),
            log_path=config_dict.get("log_path", "data_storage/logs"),
            data_path=config_dict.get("data_path", "data_storage"),
        )
        
        return pipeline_config
    
    def to_yaml(self, filepath: str):
        """Save configuration to YAML file"""
        config_dict = self.to_dict()
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, default_flow_style=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            "pipeline": {
                "version_format": self.version_format,
                "schedule": self.schedules,
            },
            "sources": {
                source_name: {
                    "enabled": source.enabled,
                    "start_url": source.start_url,
                    "rate_limit": source.rate_limit,
                    "timeout": source.timeout,
                    "retry_max": source.retry_max,
                }
                for source_name, source in self.sources.items()
            },
            "storage": {
                "raw_path": self.storage.raw_path,
                "processed_path": self.storage.processed_path,
                "archive_path": self.storage.archive_path,
                "backup_path": self.storage.backup_path,
                "log_path": self.storage.log_path,
            },
            "validation": {
                "min_completeness": self.validation.min_completeness,
                "max_duplicates": self.validation.max_duplicates,
                "max_invalid": self.validation.max_invalid,
                "required_fields": self.validation.required_fields,
            },
            "archive": {
                "hot_retention_months": self.archive.hot_retention_months,
                "warm_retention_years": self.archive.warm_retention_years,
                "cold_retention_years": self.archive.cold_retention_years,
                "compression_format": self.archive.compression_format,
                "encryption": self.archive.encryption,
            },
            "monitoring": {
                "log_level": self.monitoring.log_level,
                "metrics_interval": self.monitoring.metrics_interval,
                "scraper_success_threshold": self.monitoring.scraper_success_threshold,
                "validation_pass_threshold": self.monitoring.validation_pass_threshold,
                "max_pipeline_runtime": self.monitoring.max_pipeline_runtime,
            },
            "log_path": self.log_path,
            "data_path": self.data_path,
        }
    
    def validate(self) -> bool:
        """Validate configuration integrity"""
        errors = []
        
        # Check sources
        if not self.sources:
            errors.append("No data sources configured")
        
        # Check storage paths
        if not self.storage.raw_path:
            errors.append("Raw data path not configured")
        if not self.storage.processed_path:
            errors.append("Processed data path not configured")
        
        # Check validation thresholds
        if not (0 < self.validation.min_completeness <= 1):
            errors.append("Invalid min_completeness threshold")
        
        # Check retention policies
        if self.archive.hot_retention_months < 1:
            errors.append("Hot retention must be >= 1 month")
        
        if errors:
            raise ValueError("\n".join(errors))
        
        return True


def create_default_config() -> PipelineConfig:
    """Create a default configuration"""
    config = PipelineConfig(
        sources={
            "vietnamworks": SourceConfig(
                name="vietnamworks",
                enabled=True,
                start_url="https://vietnamworks.com/",
                rate_limit=1000,
                timeout=30,
            ),
            "topcv": SourceConfig(
                name="topcv",
                enabled=True,
                start_url="https://topcv.vn/",
                rate_limit=1000,
                timeout=30,
            ),
        },
        storage=StorageConfig(),
        validation=ValidationConfig(),
        archive=ArchiveConfig(),
        monitoring=MonitoringConfig(),
    )
    
    config.validate()
    return config
