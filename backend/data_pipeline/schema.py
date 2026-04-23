from typing import List, Optional, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime

class RawJobRecord(BaseModel):
    """Schema cho dữ liệu thô từ CSV crawler"""
    job_id: Optional[str] = None
    title: Optional[str] = Field(None, alias="job_title") # Alias để map với output của crawler
    company: Optional[str] = None
    salary: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    posted_date: Optional[str] = None
    skills: Optional[str] = None
    source: Optional[str] = None
    experience: Optional[str] = None
    description: Optional[str] = None
    
    class Config:
        extra = "ignore" # Bỏ qua các trường thừa
        allow_population_by_field_name = True

class CleanJobRecord(BaseModel):
    """Schema cho dữ liệu đã làm sạch và chuẩn hóa"""
    id: str
    title_raw: str
    title_normalized: str
    company: str
    
    # Salary normalized
    salary_min: int = 0
    salary_max: int = 0
    currency: str = "VND"
    
    # Location normalized
    location_raw: str
    province_code: str # e.g., SG, HN, DN
    
    # Skills
    skills: List[str] = []
    
    # Meta
    url: str
    source: str
    posted_date_iso: Optional[str] = None
    is_expired: bool = False
    
    # Audit
    processed_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    raw_reference: str # Lưu job_id gốc để trace ngược lại

class ValidationReport(BaseModel):
    """Báo cáo kết quả validation"""
    total_records: int = 0
    valid_records: int = 0
    rejected_records: int = 0
    errors: List[dict] = []
    
    def add_error(self, job_id: str, error_type: str, message: str):
        self.errors.append({
            "job_id": job_id,
            "type": error_type,
            "message": message
        })