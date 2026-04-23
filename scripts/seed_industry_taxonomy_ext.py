#!/usr/bin/env python
# scripts/seed_industry_taxonomy_ext.py
"""
KB Seed Script — Industry Taxonomy Extension (40 New Roles)
============================================================

Idempotently inserts the 8 new industry domains and 40 roles into the
Knowledge Base database.  Safe to run multiple times (upsert semantics).

Usage:
    python scripts/seed_industry_taxonomy_ext.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── ensure project root on path ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.kb.database import get_db_context
from backend.kb.models import Domain, Career, CareerSkill
from backend.scoring.components.industry_taxonomy_ext import (
    INDUSTRY_ENUM,
    ROLE_INDUSTRY_MAP,
    ROLE_SKILL_DOMAINS,
    ROLE_EDUCATION_BASELINE,
)


# ── canonical Vietnamese role names (id → display) ────────────────────────────
ROLE_DISPLAY_VI: dict[str, str] = {
    "agricultural engineer":          "Kỹ sư nông nghiệp công nghệ cao",
    "livestock engineer":             "Kỹ sư chăn nuôi",
    "aquaculture engineer":           "Kỹ sư nuôi trồng thuỷ sản",
    "agricultural quality inspector": "Chuyên viên kiểm định chất lượng nông sản",
    "food technology engineer":       "Kỹ sư công nghệ thực phẩm",
    "civil construction engineer":    "Kỹ sư xây dựng dân dụng",
    "bridge and road engineer":       "Kỹ sư cầu đường",
    "structural architect":           "Kiến trúc sư công trình",
    "construction site supervisor":   "Giám sát công trình",
    "construction project manager":   "Chuyên viên quản lý dự án xây dựng",
    "manufacturing engineer":         "Kỹ sư sản xuất",
    "quality assurance engineer":     "Kỹ sư quản lý chất lượng (QA/QC)",
    "lean six sigma specialist":      "Chuyên viên Lean / Six Sigma",
    "materials engineer":             "Kỹ sư vật liệu",
    "production line technician":     "Kỹ thuật viên vận hành dây chuyền",
    "bank credit specialist":         "Chuyên viên tín dụng ngân hàng",
    "investment analyst":             "Chuyên viên phân tích đầu tư",
    "risk management specialist":     "Chuyên viên quản lý rủi ro",
    "insurance consultant":           "Tư vấn bảo hiểm",
    "securities trader":              "Chuyên viên giao dịch chứng khoán",
    "hotel manager":                  "Quản lý khách sạn",
    "tour operator":                  "Điều hành tour du lịch",
    "tour guide":                     "Hướng dẫn viên du lịch",
    "restaurant manager":             "Quản lý nhà hàng",
    "event coordinator":              "Chuyên viên tổ chức sự kiện",
    "government official":            "Công chức hành chính nhà nước",
    "policy planning specialist":     "Chuyên viên hoạch định chính sách",
    "foreign affairs specialist":     "Chuyên viên đối ngoại",
    "customs officer":                "Cán bộ hải quan",
    "public project manager":         "Cán bộ quản lý dự án công",
    "biology researcher":             "Nhà nghiên cứu sinh học",
    "applied chemistry researcher":   "Nhà nghiên cứu hoá học ứng dụng",
    "biotechnology engineer":         "Kỹ sư công nghệ sinh học",
    "laboratory testing specialist":  "Chuyên viên kiểm nghiệm phòng thí nghiệm",
    "applied physics researcher":     "Nhà nghiên cứu vật lý ứng dụng",
    "show director":                  "Đạo diễn sản xuất chương trình",
    "screenwriter":                   "Biên kịch",
    "sports coach":                   "Huấn luyện viên thể thao",
    "artist manager":                 "Quản lý nghệ sĩ",
    "cultural heritage conservator":  "Bảo tồn viên di sản văn hoá",
}


def _upsert_domain(session, enum_key: str, dry_run: bool) -> Domain:
    label_vi, definition = INDUSTRY_ENUM[enum_key]
    existing = session.query(Domain).filter_by(name=enum_key).first()
    if existing:
        return existing
    if not dry_run:
        domain = Domain(name=enum_key, display_name=label_vi, description=definition)
        session.add(domain)
        session.flush()
        return domain
    print(f"  [DRY] Would insert Domain: {enum_key}")
    return None  # type: ignore[return-value]


def _upsert_career(session, role_key: str, domain: Domain, dry_run: bool) -> Career:
    existing = session.query(Career).filter_by(name=role_key).first()
    if existing:
        return existing
    display = ROLE_DISPLAY_VI.get(role_key, role_key)
    edu     = ROLE_EDUCATION_BASELINE.get(role_key, "bachelor")
    if not dry_run:
        career = Career(
            name=role_key,
            display_name=display,
            domain_id=domain.id,
            education_requirement=edu,
            active=True,
        )
        session.add(career)
        session.flush()
        return career
    print(f"  [DRY] Would insert Career: {role_key} → {domain.name if domain else '?'}")
    return None  # type: ignore[return-value]


def _upsert_skills(session, career: Career, role_key: str, dry_run: bool) -> None:
    domains = ROLE_SKILL_DOMAINS.get(role_key, [])
    for idx, skill_name in enumerate(domains):
        existing = (
            session.query(CareerSkill)
            .filter_by(career_id=career.id, skill_name=skill_name)
            .first()
        )
        if existing:
            continue
        if not dry_run:
            cs = CareerSkill(
                career_id=career.id,
                skill_name=skill_name,
                requirement_type="required",
                display_order=idx,
            )
            session.add(cs)
        else:
            print(f"    [DRY] Would link skill '{skill_name}' → {role_key}")


def run_seed(dry_run: bool = False) -> None:
    print(f"Seeding industry taxonomy extension — dry_run={dry_run}")

    # Group roles by industry
    industry_roles: dict[str, list[str]] = {}
    for role, industry in ROLE_INDUSTRY_MAP.items():
        industry_roles.setdefault(industry, []).append(role)

    with get_db_context() as session:
        for industry_key, roles in industry_roles.items():
            print(f"\n[{industry_key}]")
            domain = _upsert_domain(session, industry_key, dry_run)
            for role_key in roles:
                career = _upsert_career(session, role_key, domain, dry_run)
                if career:
                    _upsert_skills(session, career, role_key, dry_run)
                    print(f"  + {role_key}")

        if not dry_run:
            session.commit()
            print("\nCommit OK.")
        else:
            print("\n[DRY RUN] No changes written.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed industry taxonomy extension")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    run_seed(dry_run=args.dry_run)
