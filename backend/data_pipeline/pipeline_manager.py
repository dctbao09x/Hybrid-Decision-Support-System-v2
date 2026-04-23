"""
Pipeline Manager - Orchestrates the entire data pipeline

Responsibilities:
- Orchestrate data collection, validation, enrichment
- Manage versioning and storage
- Handle error recovery and rollback
- Monitor pipeline health
- Coordinate with scoring integration
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from .config import PipelineConfig
from data_sources.base_scraper import BaseScraper
from data_validation.validators import DataValidator
from data_enrichment.skill_mapper import SkillMapper
from data_storage.version_manager import VersionManager
from data_storage.storage_manager import StorageManager
from data_integration.scoring_integrator import ScoringIntegrator
from logging_monitoring.logger import PipelineLogger

logger = logging.getLogger(__name__)


class PipelineManager:
    """
    Main orchestrator for the data pipeline
    
    Workflow:
    1. Acquisition: Scrape data from sources
    2. Validation: Check schema and business rules
    3. Enrichment: Add semantic information
    4. Storage: Save versioned data
    5. Integration: Feed to scoring engine
    6. Monitoring: Track health and metrics
    """
    
    def __init__(self, config: PipelineConfig):
        """
        Initialize pipeline with configuration
        
        Args:
            config: Pipeline configuration object
        """
        self.config = config
        self.logger = PipelineLogger(config.log_path)
        
        # Initialize components
        self.storage = StorageManager(config.storage_path)
        self.version_manager = VersionManager(config.storage_path)
        self.validator = DataValidator(config.validation_rules)
        self.skill_mapper = SkillMapper()
        self.scoring_integrator = ScoringIntegrator()
        
        # Pipeline state
        self.current_version = None
        self.pipeline_state = "idle"
        self.start_time = None
        self.stats = {}
        
    async def run_full_pipeline(self) -> Dict[str, Any]:
        """
        Execute complete pipeline from acquisition to integration
        
        Returns:
            dict: Pipeline execution results and metrics
        """
        self.logger.info("=" * 80)
        self.logger.info("STARTING FULL DATA PIPELINE")
        self.logger.info("=" * 80)
        
        self.start_time = datetime.now()
        self.pipeline_state = "running"
        results = {}
        
        try:
            # Phase 1: Acquisition
            self.logger.info("📥 PHASE 1: DATA ACQUISITION")
            acquisition_results = await self._phase_acquisition()
            results["acquisition"] = acquisition_results
            
            # Phase 2: Validation
            self.logger.info("✓ PHASE 2: DATA VALIDATION")
            validation_results = await self._phase_validation(
                acquisition_results["raw_data_path"]
            )
            results["validation"] = validation_results
            
            if not validation_results["status"] == "success":
                raise Exception("Validation failed - aborting pipeline")
            
            # Phase 3: Enrichment
            self.logger.info("✨ PHASE 3: DATA ENRICHMENT")
            enrichment_results = await self._phase_enrichment(
                validation_results["validated_data_path"]
            )
            results["enrichment"] = enrichment_results
            
            # Phase 4: Storage & Versioning
            self.logger.info("💾 PHASE 4: STORAGE & VERSIONING")
            storage_results = await self._phase_storage(
                enrichment_results["enriched_data_path"]
            )
            results["storage"] = storage_results
            self.current_version = storage_results["version"]
            
            # Phase 5: Integration
            self.logger.info("🔗 PHASE 5: SCORING INTEGRATION")
            integration_results = await self._phase_integration(
                storage_results["version"]
            )
            results["integration"] = integration_results
            
            # Phase 6: Archive Management
            self.logger.info("📦 PHASE 6: ARCHIVE MANAGEMENT")
            archive_results = await self._phase_archive()
            results["archive"] = archive_results
            
            # Summary
            self.pipeline_state = "completed"
            execution_time = (datetime.now() - self.start_time).total_seconds()
            
            summary = {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "execution_time_seconds": execution_time,
                "current_version": self.current_version,
                "total_records_processed": self._calculate_total_records(results),
                "results": results,
            }
            
            self.logger.info("=" * 80)
            self.logger.info(f"✅ PIPELINE COMPLETED SUCCESSFULLY in {execution_time:.1f}s")
            self.logger.info(f"   Version: {self.current_version}")
            self.logger.info(f"   Records: {summary['total_records_processed']:,}")
            self.logger.info("=" * 80)
            
            return summary
            
        except Exception as e:
            self.pipeline_state = "failed"
            self.logger.error(f"❌ PIPELINE FAILED: {str(e)}", exc_info=True)
            results["error"] = str(e)
            results["status"] = "failed"
            raise
    
    async def _phase_acquisition(self) -> Dict[str, Any]:
        """Phase 1: Acquire data from sources"""
        try:
            # Get previous version to detect changes
            previous_version = self.version_manager.get_latest_version()
            
            # Scrape from all sources
            raw_data_path = self.storage.create_raw_data_dir()
            sources_data = {}
            
            for source_name, source_config in self.config.sources.items():
                if not source_config.get("enabled", True):
                    continue
                
                self.logger.info(f"  Scraping {source_name}...")
                scraper = self._get_scraper(source_name, source_config)
                
                try:
                    data = await scraper.scrape()
                    sources_data[source_name] = {
                        "record_count": len(data),
                        "timestamp": datetime.now().isoformat(),
                        "status": "success",
                    }
                    
                    # Save raw data
                    self.storage.save_raw_data(
                        raw_data_path, 
                        source_name, 
                        data
                    )
                    
                    self.logger.info(
                        f"    ✓ {source_name}: {len(data):,} records"
                    )
                    
                except Exception as e:
                    sources_data[source_name] = {
                        "status": "failed",
                        "error": str(e),
                    }
                    self.logger.error(f"    ✗ {source_name} failed: {str(e)}")
            
            return {
                "status": "success",
                "raw_data_path": str(raw_data_path),
                "sources_data": sources_data,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            self.logger.error(f"Acquisition phase failed: {str(e)}")
            raise
    
    async def _phase_validation(self, raw_data_path: str) -> Dict[str, Any]:
        """Phase 2: Validate data"""
        try:
            validated_data_path = self.storage.create_validated_data_dir()
            
            # Load raw data
            raw_data = self.storage.load_raw_data(raw_data_path)
            
            self.logger.info(f"  Total raw records: {len(raw_data):,}")
            
            # Validate
            validation_report = self.validator.validate_batch(raw_data)
            
            # Log validation results
            self.logger.info(f"  Valid records: {validation_report['valid_count']:,}")
            self.logger.info(f"  Invalid records: {validation_report['invalid_count']:,}")
            self.logger.info(f"  Completeness: {validation_report['completeness']:.1%}")
            
            # Save validated data
            self.storage.save_validated_data(
                validated_data_path,
                validation_report["valid_data"]
            )
            
            # Save validation report
            self.storage.save_json(
                Path(validated_data_path) / "validation_report.json",
                validation_report
            )
            
            return {
                "status": "success",
                "validated_data_path": str(validated_data_path),
                "validation_report": validation_report,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            self.logger.error(f"Validation phase failed: {str(e)}")
            raise
    
    async def _phase_enrichment(self, validated_data_path: str) -> Dict[str, Any]:
        """Phase 3: Enrich data with semantic information"""
        try:
            enriched_data_path = self.storage.create_enriched_data_dir()
            
            # Load validated data
            data = self.storage.load_validated_data(validated_data_path)
            
            self.logger.info(f"  Enriching {len(data):,} records...")
            
            enrichment_stats = {
                "skills_mapped": 0,
                "careers_classified": 0,
                "trends_analyzed": 0,
                "errors": 0,
            }
            
            enriched_data = []
            
            for record in data:
                try:
                    # Map skills
                    skills = self.skill_mapper.extract_and_map(
                        record.get("job_description", "")
                    )
                    record["mapped_skills"] = skills
                    enrichment_stats["skills_mapped"] += 1
                    
                    # TODO: Add career classification
                    # TODO: Add market trend analysis
                    
                    enriched_data.append(record)
                    
                except Exception as e:
                    enrichment_stats["errors"] += 1
                    self.logger.warning(f"Enrichment error for record: {str(e)}")
                    enriched_data.append(record)  # Keep original
            
            # Save enriched data
            self.storage.save_enriched_data(enriched_data_path, enriched_data)
            
            self.logger.info(f"  Skills mapped: {enrichment_stats['skills_mapped']:,}")
            
            return {
                "status": "success",
                "enriched_data_path": str(enriched_data_path),
                "enrichment_stats": enrichment_stats,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            self.logger.error(f"Enrichment phase failed: {str(e)}")
            raise
    
    async def _phase_storage(self, enriched_data_path: str) -> Dict[str, Any]:
        """Phase 4: Store versioned data"""
        try:
            # Create version
            version = self.version_manager.create_version(
                data_path=enriched_data_path,
                metadata={
                    "pipeline_execution": datetime.now().isoformat(),
                    "data_sources": list(self.config.sources.keys()),
                }
            )
            
            self.logger.info(f"  Version created: {version}")
            
            return {
                "status": "success",
                "version": version,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            self.logger.error(f"Storage phase failed: {str(e)}")
            raise
    
    async def _phase_integration(self, version: str) -> Dict[str, Any]:
        """Phase 5: Integrate with scoring engine"""
        try:
            self.logger.info(f"  Preparing scoring inputs for version {version}...")
            
            integration_status = await self.scoring_integrator.integrate(version)
            
            self.logger.info(
                f"    ✓ Scoring integration successful"
            )
            
            return {
                "status": "success",
                "version": version,
                "integration_status": integration_status,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            self.logger.error(f"Integration phase failed: {str(e)}")
            # Don't fail pipeline, but log error
            return {
                "status": "warning",
                "error": str(e),
            }
    
    async def _phase_archive(self) -> Dict[str, Any]:
        """Phase 6: Manage data archival"""
        try:
            self.logger.info("  Checking archive policies...")
            
            archive_actions = self.storage.apply_archive_policy()
            
            self.logger.info(
                f"    Archived: {archive_actions.get('archived', 0)} versions"
            )
            self.logger.info(
                f"    Deleted: {archive_actions.get('deleted', 0)} versions"
            )
            
            return {
                "status": "success",
                "archive_actions": archive_actions,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            self.logger.error(f"Archive phase failed: {str(e)}")
            return {
                "status": "warning",
                "error": str(e),
            }
    
    def _get_scraper(self, source_name: str, config: Dict) -> BaseScraper:
        """Factory method to get scraper for source"""
        if source_name == "vietnamworks":
            from data_sources.vietnamworks_scraper import VietnamWorksScraper
            return VietnamWorksScraper(config)
        elif source_name == "topcv":
            from data_sources.topcv_scraper import TopCVScraper
            return TopCVScraper(config)
        else:
            raise ValueError(f"Unknown source: {source_name}")
    
    def _calculate_total_records(self, results: Dict) -> int:
        """Calculate total records processed"""
        try:
            validation = results.get("validation", {})
            return validation.get("validation_report", {}).get("valid_count", 0)
        except (KeyError, AttributeError, TypeError) as e:
            logger.debug(f"Could not extract record count: {e}")
            return 0
