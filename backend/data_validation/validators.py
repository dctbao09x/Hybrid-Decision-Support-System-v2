"""
Data Validation Module - Schema & Business Rules Validation

Validates job posting data against defined schemas and business rules
"""

from typing import List, Dict, Any, Tuple, Optional
import json
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DataValidator:
    """
    Validates recruitment data against schemas and business rules
    """
    
    REQUIRED_FIELDS = [
        "job_title",
        "company_name",
        "salary_min",
        "salary_max",
        "skills",
        "experience_level",
        "location",
        "job_description",
        "posted_date",
    ]
    
    VALID_EXPERIENCE_LEVELS = ["entry", "mid", "senior", "lead", "cto"]
    VALID_JOB_TYPES = ["full_time", "contract", "part_time", "internship", "freelance"]
    
    # Vietnam regions
    VALID_LOCATIONS = [
        "Ha Noi", "Ho Chi Minh", "Da Nang", "Hai Phong",
        "Hai Duong", "Quang Ninh", "Thai Nguyen", "Hung Yen",
        "Ha Nam", "Nam Dinh", "Ninh Binh", "Thanh Hoa",
        "Nghe An", "Vinh Yen", "Vinh", "Bien Hoa", "Long Thanh",
        "Can Tho", "Nha Trang", "Hue", "Da Lat", "Buon Me Thuot",
        "Other"
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize validator
        
        Args:
            config: Validation configuration
        """
        self.config = config or {}
        self.errors = []
    
    def validate_batch(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate a batch of records
        
        Args:
            records: List of job records
            
        Returns:
            Validation report with statistics
        """
        valid_data = []
        invalid_data = []
        errors = []
        
        for i, record in enumerate(records):
            is_valid, error_msg = self.validate_record(record)
            
            if is_valid:
                valid_data.append(record)
            else:
                invalid_data.append({
                    "record_index": i,
                    "record": record,
                    "error": error_msg,
                })
                errors.append(error_msg)
        
        # Calculate statistics
        total = len(records)
        valid_count = len(valid_data)
        invalid_count = len(invalid_data)
        completeness = valid_count / total if total > 0 else 0
        
        # Check for duplicates
        duplicate_count = self._detect_duplicates(valid_data)
        duplicate_rate = duplicate_count / valid_count if valid_count > 0 else 0
        
        report = {
            "status": "success" if completeness >= 0.95 else "warning",
            "timestamp": datetime.now().isoformat(),
            "total_records": total,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "completeness": completeness,
            "duplicate_count": duplicate_count,
            "duplicate_rate": duplicate_rate,
            "valid_data": valid_data,
            "invalid_data": invalid_data,
            "errors": errors[:100],  # Keep first 100 errors
        }
        
        logger.info(f"Validation complete: {completeness:.1%} valid, "
                   f"{duplicate_rate:.1%} duplicates")
        
        return report
    
    def validate_record(self, record: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate a single record
        
        Args:
            record: Job record to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in record or not record[field]:
                return False, f"Missing required field: {field}"
        
        # Validate specific fields
        if not self._validate_job_title(record.get("job_title", "")):
            return False, "Invalid job_title"
        
        if not self._validate_company_name(record.get("company_name", "")):
            return False, "Invalid company_name"
        
        # Validate salary
        salary_valid, salary_msg = self._validate_salary(
            record.get("salary_min"),
            record.get("salary_max")
        )
        if not salary_valid:
            return False, salary_msg
        
        # Validate skills
        if not self._validate_skills(record.get("skills", [])):
            return False, "Invalid skills format or content"
        
        # Validate experience level
        if record.get("experience_level") not in self.VALID_EXPERIENCE_LEVELS:
            return False, f"Invalid experience_level: {record.get('experience_level')}"
        
        # Validate location
        if record.get("location") not in self.VALID_LOCATIONS:
            return False, f"Invalid location: {record.get('location')}"
        
        # Validate job type
        if "job_type" in record and record["job_type"] not in self.VALID_JOB_TYPES:
            return False, f"Invalid job_type: {record.get('job_type')}"
        
        # Validate dates
        if not self._validate_posted_date(record.get("posted_date")):
            return False, "Invalid posted_date"
        
        # Validate job description
        if not self._validate_job_description(record.get("job_description", "")):
            return False, "Invalid job_description (too short or empty)"
        
        return True, ""
    
    def _validate_job_title(self, title: str) -> bool:
        """Validate job title"""
        if not isinstance(title, str):
            return False
        if len(title) < 3 or len(title) > 200:
            return False
        # Should not contain excessive special characters
        special_count = sum(1 for c in title if c in "!@#$%^&*()")
        return special_count < 5
    
    def _validate_company_name(self, company: str) -> bool:
        """Validate company name"""
        if not isinstance(company, str):
            return False
        return 1 < len(company) < 300
    
    def _validate_salary(self, salary_min: Any, salary_max: Any) -> Tuple[bool, str]:
        """Validate salary range"""
        try:
            if not isinstance(salary_min, (int, float)) or not isinstance(salary_max, (int, float)):
                return False, "Salary must be numeric"
            
            if salary_min < 0 or salary_max < 0:
                return False, "Salary cannot be negative"
            
            if salary_min > 500_000_000 or salary_max > 500_000_000:
                return False, "Salary exceeds maximum (500M VND)"
            
            if salary_min > salary_max:
                return False, "salary_min is greater than salary_max"
            
            # Minimum difference
            if salary_max - salary_min < 1_000_000:
                return False, "Salary range too small"
            
            return True, ""
            
        except (TypeError, ValueError):
            return False, "Invalid salary format"
    
    def _validate_skills(self, skills: Any) -> bool:
        """Validate skills list"""
        if not isinstance(skills, list):
            return False
        
        if len(skills) == 0 or len(skills) > 50:
            return False
        
        for skill in skills:
            if not isinstance(skill, (str, dict)):
                return False
            
            if isinstance(skill, str):
                if len(skill) < 2 or len(skill) > 100:
                    return False
            elif isinstance(skill, dict):
                if "name" not in skill or not isinstance(skill["name"], str):
                    return False
        
        return True
    
    def _validate_posted_date(self, posted_date: Any) -> bool:
        """Validate posted date"""
        if not posted_date:
            return False
        
        try:
            if isinstance(posted_date, str):
                # Try to parse ISO format
                datetime.fromisoformat(posted_date.replace('Z', '+00:00'))
            elif isinstance(posted_date, (int, float)):
                # Assume timestamp
                if posted_date < 0:
                    return False
                # Check if reasonable (within last 10 years)
                if posted_date > datetime.now().timestamp() + 86400:  # Future
                    return False
            else:
                return False
            
            return True
            
        except (ValueError, TypeError):
            return False
    
    def _validate_job_description(self, description: str) -> bool:
        """Validate job description"""
        if not isinstance(description, str):
            return False
        
        # Minimum length
        if len(description.strip()) < 20:
            return False
        
        # Maximum length
        if len(description) > 50000:
            return False
        
        return True
    
    def _detect_duplicates(self, records: List[Dict[str, Any]]) -> int:
        """
        Detect duplicate records
        
        Uses MD5 hash for exact duplicates
        """
        import hashlib
        
        seen_hashes = set()
        duplicate_count = 0
        
        for record in records:
            # Create hash from key fields
            key_fields = json.dumps({
                "title": record.get("job_title", ""),
                "company": record.get("company_name", ""),
                "location": record.get("location", ""),
                "salary_min": record.get("salary_min", 0),
                "salary_max": record.get("salary_max", 0),
            }, sort_keys=True)
            
            record_hash = hashlib.md5(key_fields.encode()).hexdigest()
            
            if record_hash in seen_hashes:
                duplicate_count += 1
            else:
                seen_hashes.add(record_hash)
        
        return duplicate_count
    
    def generate_validation_report(self, report: Dict[str, Any]) -> str:
        """
        Generate human-readable validation report
        
        Args:
            report: Validation report dict
            
        Returns:
            Formatted report string
        """
        lines = [
            "=" * 80,
            "DATA VALIDATION REPORT",
            "=" * 80,
            f"Timestamp: {report['timestamp']}",
            f"Total Records: {report['total_records']:,}",
            f"Valid Records: {report['valid_count']:,} ({report['completeness']:.1%})",
            f"Invalid Records: {report['invalid_count']:,}",
            f"Duplicate Records: {report['duplicate_count']:,} ({report['duplicate_rate']:.1%})",
            "",
            f"Overall Status: {report['status'].upper()}",
            "=" * 80,
        ]
        
        if report['errors']:
            lines.extend([
                "",
                "ERRORS (first 10):",
                "-" * 80,
            ])
            for error in report['errors'][:10]:
                lines.append(f"  - {error}")
        
        return "\n".join(lines)
