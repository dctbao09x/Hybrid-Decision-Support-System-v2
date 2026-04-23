import pandas as pd
from typing import List, Tuple, Set
from .schema import RawJobRecord, ValidationReport
import logging

logger = logging.getLogger(__name__)

class DataValidator:
    def __init__(self):
        self.seen_ids: Set[str] = set()

    def load_csv(self, file_path: str) -> List[dict]:
        """Load CSV và chuyển thành list dict, xử lý NaN"""
        try:
            df = pd.read_csv(file_path)
            df = df.where(pd.notnull(df), None) # Convert NaN to None
            return df.to_dict('records')
        except Exception as e:
            logger.error(f"Lỗi đọc file CSV {file_path}: {e}")
            return []

    def validate_batch(self, raw_data: List[dict]) -> Tuple[List[RawJobRecord], ValidationReport]:
        """
        Validate một lô dữ liệu.
        Trả về: (List các record hợp lệ, Báo cáo lỗi)
        """
        valid_records = []
        report = ValidationReport(total_records=len(raw_data))
        
        # Reset deduplication set cho batch mới (hoặc giữ lại nếu muốn dedup xuyên suốt session)
        # self.seen_ids.clear() 

        for row in raw_data:
            # 1. Basic Schema Validation
            try:
                record = RawJobRecord(**row)
            except Exception as e:
                report.rejected_records += 1
                report.add_error("UNKNOWN", "schema_error", str(e))
                continue

            job_id = record.job_id or "UNKNOWN"

            # 2. Critical Fields Check
            missing_fields = []
            if not record.job_id: missing_fields.append("job_id")
            if not record.title: missing_fields.append("title")
            if not record.company: missing_fields.append("company")
            if not record.url: missing_fields.append("url")

            if missing_fields:
                report.rejected_records += 1
                report.add_error(job_id, "missing_critical_fields", f"Missing: {', '.join(missing_fields)}")
                continue

            # 3. Deduplication (Job ID + URL)
            # Tạo unique key. Một số job có thể cùng ID nhưng khác URL (ít gặp) hoặc ngược lại.
            # Ở đây dùng job_id làm chính.
            dedup_key = f"{record.job_id}_{record.url}"
            if dedup_key in self.seen_ids:
                report.rejected_records += 1
                report.add_error(job_id, "duplicate", "Duplicate record in batch")
                continue
            
            self.seen_ids.add(dedup_key)

            # 4. Logic Checks (Optional - e.g. title too short)
            if len(record.title) < 3:
                report.rejected_records += 1
                report.add_error(job_id, "invalid_data", "Title too short")
                continue

            valid_records.append(record)

        report.valid_records = len(valid_records)
        return valid_records, report

    def check_expiration(self, posted_date_str: str) -> bool:
        """
        Kiểm tra job hết hạn chưa. 
        Logic này sẽ được gọi trong Processor vì cần parse date trước.
        """
        pass