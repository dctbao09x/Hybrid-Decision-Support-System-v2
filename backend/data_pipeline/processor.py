import re
import unidecode
from datetime import datetime, timedelta
from typing import List, Optional
from .schema import RawJobRecord, CleanJobRecord
import logging

logger = logging.getLogger(__name__)

class DataProcessor:
    
    # Mapping tỉnh thành cơ bản
    LOCATION_MAP = {
        "ho chi minh": "SG", "sai gon": "SG", "hcm": "SG",
        "ha noi": "HN",
        "da nang": "DN",
        "can tho": "CT",
        "hai phong": "HP",
        "binh duong": "BD",
        "dong nai": "DNA",
        "remote": "REMOTE",
        "online": "REMOTE"
    }

    def normalize_salary(self, salary_str: Optional[str]) -> tuple[int, int]:
        """
        Parse salary string sang min/max int.
        Input: "10 - 15 Triệu", "Tới 1000 USD", "Thỏa thuận"
        Output: (min, max)
        """
        if not salary_str:
            return 0, 0
        
        s = salary_str.lower().replace(",", "").replace(".", "")
        
        # Tỷ giá ước tính
        multiplier = 1
        if "usd" in s or "$" in s:
            multiplier = 25000
        elif "trieu" in s or "tr" in s:
            multiplier = 1000000
        
        # Case: "10 - 20 ..."
        range_match = re.search(r'(\d+)\s*-\s*(\d+)', s)
        if range_match:
            try:
                min_val = int(range_match.group(1)) * multiplier
                max_val = int(range_match.group(2)) * multiplier
                return min_val, max_val
            except (ValueError, TypeError):
                pass
            
        # Case: "Tới/Up to 20 ..."
        upto_match = re.search(r'(toi|up to|duoi)\s*(\d+)', s)
        if upto_match:
            try:
                val = int(upto_match.group(2)) * multiplier
                return 0, val
            except (ValueError, TypeError):
                pass

        # Case: "Trên/From 10 ..."
        from_match = re.search(r'(tren|from)\s*(\d+)', s)
        if from_match:
            try:
                val = int(from_match.group(2)) * multiplier
                return val, 0  # 0 means unlimited/negotiable upper
            except (ValueError, TypeError):
                pass
            
        return 0, 0

    def normalize_location(self, loc_str: Optional[str]) -> str:
        """Map location string sang Province Code"""
        if not loc_str:
            return "UNKNOWN"
        
        norm = unidecode.unidecode(loc_str).lower()
        for key, code in self.LOCATION_MAP.items():
            if key in norm:
                return code
        return "OTHER"

    def normalize_title(self, title: str) -> str:
        """Canonical form: lowercase, remove special chars"""
        if not title:
            return ""
        # Giữ lại chữ cái, số và khoảng trắng
        clean = re.sub(r'[^\w\s]', '', title)
        return " ".join(clean.lower().split())

    def normalize_skills(self, skills_str: Optional[str]) -> List[str]:
        """Convert string list sang list object"""
        if not skills_str:
            return []
        
        # Split by comma or newline
        parts = re.split(r'[,\n]', skills_str)
        return [p.strip() for p in parts if p.strip()]

    def parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse posted date tương đối hoặc tuyệt đối"""
        if not date_str:
            return None
            
        now = datetime.now()
        s = date_str.lower()
        
        try:
            if "hom qua" in s:
                return now - timedelta(days=1)
            if "gio truoc" in s:
                return now
            if "ngay truoc" in s:
                days = int(re.search(r'(\d+)', s).group(1))
                return now - timedelta(days=days)
            
            # Try standard formats dd/mm/yyyy
            match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)
            if match:
                return datetime(
                    int(match.group(3)), 
                    int(match.group(2)), 
                    int(match.group(1))
                )
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Could not parse date '{date_str}': {e}")
        
        return None

    def process_record(self, raw: RawJobRecord) -> CleanJobRecord:
        """Main processing logic for single record"""
        
        # 1. Normalize Fields
        salary_min, salary_max = self.normalize_salary(raw.salary)
        prov_code = self.normalize_location(raw.location)
        title_norm = self.normalize_title(raw.title)
        skill_list = self.normalize_skills(raw.skills)
        
        # 2. Date & Expiration
        posted_dt = self.parse_date(raw.posted_date)
        posted_iso = posted_dt.isoformat() if posted_dt else None
        
        is_expired = False
        if posted_dt:
            # Giả sử job hết hạn sau 30 ngày
            if (datetime.now() - posted_dt).days > 30:
                is_expired = True

        return CleanJobRecord(
            id=f"{raw.source}_{raw.job_id}" if raw.source else raw.job_id,
            title_raw=raw.title,
            title_normalized=title_norm,
            company=raw.company,
            salary_min=salary_min,
            salary_max=salary_max,
            location_raw=raw.location or "",
            province_code=prov_code,
            skills=skill_list,
            url=raw.url,
            source=raw.source or "unknown",
            posted_date_iso=posted_iso,
            is_expired=is_expired,
            raw_reference=raw.job_id
        )

    def process_batch(self, valid_records: List[RawJobRecord]) -> List[CleanJobRecord]:
        results = []
        for rec in valid_records:
            results.append(self.process_record(rec))
        return results