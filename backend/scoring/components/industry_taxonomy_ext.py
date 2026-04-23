# backend/scoring/components/industry_taxonomy_ext.py
"""
Industry Taxonomy Extension — 8 New Industry Groups (40 Roles)
==============================================================

Provides:
  INDUSTRY_ENUM          — canonical snake_case enum → display label + definition
  ROLE_INDUSTRY_MAP      — canonical English role name → industry_enum
  ROLE_SKILL_DOMAINS     — role → required skill domains (max 5)
  ROLE_EDUCATION_BASELINE— role → minimum education enum
  ROLE_SIMGR_INFLUENCE   — role → primary SIMGR dimensions affected
  SIMGR_GOAL_MULTIPLIERS — industry_enum → goal_alignment multiplier (match)
  SIMGR_EXCLUSION_PENALTY— industry_enum → goal_alignment score penalty (exclude)
  SIMGR_EDUCATION_CAP    — education_enum → score cap when below baseline
  SIMGR_SKILL_PENALTY    — missing skill domain → skill_score penalty (fraction)

All values are deterministic, numeric, and implementation-ready.

EDUCATION ENUM ORDER (ascending):
  high_school < vocational < bachelor < master < phd
"""

from __future__ import annotations
from typing import Dict, List, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — INDUSTRY ENUM NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════

# Format: enum_name → (display_label_vi, one_sentence_definition)
INDUSTRY_ENUM: Dict[str, Tuple[str, str]] = {
    "agriculture_aquaculture_food": (
        "Nông nghiệp – Thuỷ sản – Thực phẩm",
        "Ngành sản xuất, nuôi trồng, kiểm định và chế biến nông sản, thuỷ hải sản và thực phẩm.",
    ),
    "construction_architecture_infrastructure": (
        "Xây dựng – Kiến trúc – Hạ tầng",
        "Ngành thiết kế, thi công, giám sát và quản lý các công trình xây dựng dân dụng và hạ tầng.",
    ),
    "manufacturing_industrial_processing": (
        "Sản xuất – Công nghiệp chế biến",
        "Ngành vận hành, kiểm soát chất lượng và tối ưu hoá dây chuyền sản xuất công nghiệp.",
    ),
    "banking_insurance_investment": (
        "Ngân hàng – Bảo hiểm – Đầu tư",
        "Ngành cung cấp dịch vụ tài chính, tín dụng, bảo hiểm và quản lý danh mục đầu tư.",
    ),
    "tourism_hospitality_services": (
        "Du lịch – Khách sạn – Dịch vụ",
        "Ngành tổ chức, vận hành và quản lý các hoạt động du lịch, lưu trú và dịch vụ tiêu dùng.",
    ),
    "public_administration_diplomacy": (
        "Hành chính – Công vụ – Quan hệ quốc tế",
        "Ngành thực thi công vụ, hoạch định chính sách, đối ngoại và quản lý dự án công.",
    ),
    "science_research_biotechnology": (
        "Khoa học – Nghiên cứu – Công nghệ sinh học",
        "Ngành nghiên cứu khoa học cơ bản và ứng dụng, phát triển công nghệ sinh học và kiểm nghiệm.",
    ),
    "arts_culture_sports": (
        "Nghệ thuật – Văn hoá – Thể thao",
        "Ngành sáng tác, biểu diễn, huấn luyện thể thao và bảo tồn di sản văn hoá.",
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — ROLE STANDARDIZATION
# ══════════════════════════════════════════════════════════════════════════════

# role canonical key → industry_enum  (1:1, no duplicates)
ROLE_INDUSTRY_MAP: Dict[str, str] = {
    # Group 1 — agriculture_aquaculture_food
    "agricultural engineer":          "agriculture_aquaculture_food",
    "livestock engineer":             "agriculture_aquaculture_food",
    "aquaculture engineer":           "agriculture_aquaculture_food",
    "agricultural quality inspector": "agriculture_aquaculture_food",
    "food technology engineer":       "agriculture_aquaculture_food",
    # Group 2 — construction_architecture_infrastructure
    "civil construction engineer":    "construction_architecture_infrastructure",
    "bridge and road engineer":       "construction_architecture_infrastructure",
    "structural architect":           "construction_architecture_infrastructure",
    "construction site supervisor":   "construction_architecture_infrastructure",
    "construction project manager":   "construction_architecture_infrastructure",
    # Group 3 — manufacturing_industrial_processing
    "manufacturing engineer":         "manufacturing_industrial_processing",
    "quality assurance engineer":     "manufacturing_industrial_processing",
    "lean six sigma specialist":      "manufacturing_industrial_processing",
    "materials engineer":             "manufacturing_industrial_processing",
    "production line technician":     "manufacturing_industrial_processing",
    # Group 4 — banking_insurance_investment
    "bank credit specialist":         "banking_insurance_investment",
    "investment analyst":             "banking_insurance_investment",
    "risk management specialist":     "banking_insurance_investment",
    "insurance consultant":           "banking_insurance_investment",
    "securities trader":              "banking_insurance_investment",
    # Group 5 — tourism_hospitality_services
    "hotel manager":                  "tourism_hospitality_services",
    "tour operator":                  "tourism_hospitality_services",
    "tour guide":                     "tourism_hospitality_services",
    "restaurant manager":             "tourism_hospitality_services",
    "event coordinator":              "tourism_hospitality_services",
    # Group 6 — public_administration_diplomacy
    "government official":            "public_administration_diplomacy",
    "policy planning specialist":     "public_administration_diplomacy",
    "foreign affairs specialist":     "public_administration_diplomacy",
    "customs officer":                "public_administration_diplomacy",
    "public project manager":         "public_administration_diplomacy",
    # Group 7 — science_research_biotechnology
    "biology researcher":             "science_research_biotechnology",
    "applied chemistry researcher":   "science_research_biotechnology",
    "biotechnology engineer":         "science_research_biotechnology",
    "laboratory testing specialist":  "science_research_biotechnology",
    "applied physics researcher":     "science_research_biotechnology",
    # Group 8 — arts_culture_sports
    "show director":                  "arts_culture_sports",
    "screenwriter":                   "arts_culture_sports",
    "sports coach":                   "arts_culture_sports",
    "artist manager":                 "arts_culture_sports",
    "cultural heritage conservator":  "arts_culture_sports",
}

# role → required_skill_domains  (max 5 per role)
ROLE_SKILL_DOMAINS: Dict[str, List[str]] = {
    "agricultural engineer":          ["agronomy", "iot_sensing", "precision_farming", "data_analysis", "environmental_science"],
    "livestock engineer":             ["animal_husbandry", "veterinary_science", "feed_management", "disease_control", "data_analysis"],
    "aquaculture engineer":           ["aquatic_biology", "water_quality_management", "feed_science", "disease_prevention", "environmental_monitoring"],
    "agricultural quality inspector": ["quality_control", "food_safety_regulation", "laboratory_testing", "auditing", "documentation"],
    "food technology engineer":       ["food_science", "process_engineering", "quality_management", "microbiology", "product_development"],

    "civil construction engineer":    ["structural_engineering", "construction_management", "autocad_bim", "materials_science", "project_scheduling"],
    "bridge and road engineer":       ["geotechnical_engineering", "transportation_planning", "structural_analysis", "autocad_bim", "project_management"],
    "structural architect":           ["architectural_design", "urban_planning", "bim_revit", "structural_coordination", "building_codes"],
    "construction site supervisor":   ["site_management", "safety_compliance", "quality_inspection", "scheduling", "contractor_coordination"],
    "construction project manager":   ["project_management", "cost_estimation", "contract_management", "scheduling", "stakeholder_communication"],

    "manufacturing engineer":         ["process_optimization", "lean_manufacturing", "cad_cam", "materials_science", "quality_systems"],
    "quality assurance engineer":     ["iso_standards", "statistical_process_control", "root_cause_analysis", "documentation", "auditing"],
    "lean six sigma specialist":      ["lean_tools", "six_sigma_dmaic", "process_mapping", "statistical_analysis", "change_management"],
    "materials engineer":             ["metallurgy", "polymer_science", "materials_testing", "failure_analysis", "r_and_d"],
    "production line technician":     ["plc_programming", "mechanical_maintenance", "electrical_systems", "safety_procedures", "quality_inspection"],

    "bank credit specialist":         ["credit_analysis", "financial_modeling", "risk_assessment", "banking_regulations", "customer_relations"],
    "investment analyst":             ["financial_analysis", "equity_research", "valuation_models", "capital_markets", "quantitative_methods"],
    "risk management specialist":     ["risk_modeling", "regulatory_compliance", "scenario_analysis", "derivatives", "financial_reporting"],
    "insurance consultant":           ["insurance_products", "actuarial_concepts", "customer_advisory", "claims_processing", "compliance"],
    "securities trader":              ["trading_platforms", "market_analysis", "derivatives", "regulatory_knowledge", "quantitative_finance"],

    "hotel manager":                  ["hospitality_management", "revenue_management", "customer_service", "operations_management", "staff_training"],
    "tour operator":                  ["itinerary_planning", "supplier_negotiation", "geography_knowledge", "customer_service", "marketing"],
    "tour guide":                     ["cultural_knowledge", "multilingual_communication", "customer_service", "safety_awareness", "storytelling"],
    "restaurant manager":             ["food_beverage_management", "inventory_control", "staff_management", "customer_service", "cost_control"],
    "event coordinator":              ["event_planning", "vendor_management", "budget_control", "logistics", "stakeholder_communication"],

    "government official":            ["public_administration", "policy_analysis", "legal_knowledge", "documentation", "inter_agency_coordination"],
    "policy planning specialist":     ["policy_analysis", "research_methods", "economics", "regulatory_frameworks", "writing_reporting"],
    "foreign affairs specialist":     ["international_relations", "diplomatic_protocol", "multilingual_communication", "geopolitics", "negotiation"],
    "customs officer":                ["customs_law", "trade_compliance", "documentation", "inspection_procedures", "inter_agency_coordination"],
    "public project manager":         ["project_management", "public_procurement", "budget_management", "stakeholder_engagement", "reporting"],

    "biology researcher":             ["molecular_biology", "laboratory_techniques", "data_analysis", "scientific_writing", "experimental_design"],
    "applied chemistry researcher":   ["analytical_chemistry", "spectroscopy", "laboratory_safety", "r_and_d", "scientific_writing"],
    "biotechnology engineer":         ["genetic_engineering", "cell_culture", "bioinformatics", "regulatory_affairs", "laboratory_techniques"],
    "laboratory testing specialist":  ["laboratory_techniques", "quality_control", "instrumentation", "documentation", "safety_compliance"],
    "applied physics researcher":     ["computational_physics", "experimental_techniques", "data_analysis", "scientific_writing", "materials_characterization"],

    "show director":                  ["production_management", "creative_direction", "scriptwriting", "team_leadership", "budget_management"],
    "screenwriter":                   ["narrative_writing", "script_formatting", "story_development", "research", "collaboration"],
    "sports coach":                   ["sports_science", "training_methodology", "performance_analysis", "athlete_management", "communication"],
    "artist manager":                 ["artist_relations", "contract_negotiation", "marketing", "event_booking", "financial_management"],
    "cultural heritage conservator":  ["conservation_science", "art_history", "restoration_techniques", "documentation", "materials_analysis"],
}

# role → baseline_education enum
ROLE_EDUCATION_BASELINE: Dict[str, str] = {
    "agricultural engineer":          "bachelor",
    "livestock engineer":             "bachelor",
    "aquaculture engineer":           "bachelor",
    "agricultural quality inspector": "bachelor",
    "food technology engineer":       "bachelor",

    "civil construction engineer":    "bachelor",
    "bridge and road engineer":       "bachelor",
    "structural architect":           "bachelor",
    "construction site supervisor":   "vocational",
    "construction project manager":   "bachelor",

    "manufacturing engineer":         "bachelor",
    "quality assurance engineer":     "bachelor",
    "lean six sigma specialist":      "bachelor",
    "materials engineer":             "bachelor",
    "production line technician":     "vocational",

    "bank credit specialist":         "bachelor",
    "investment analyst":             "bachelor",
    "risk management specialist":     "bachelor",
    "insurance consultant":           "bachelor",
    "securities trader":              "bachelor",

    "hotel manager":                  "bachelor",
    "tour operator":                  "bachelor",
    "tour guide":                     "vocational",
    "restaurant manager":             "vocational",
    "event coordinator":              "bachelor",

    "government official":            "bachelor",
    "policy planning specialist":     "master",
    "foreign affairs specialist":     "master",
    "customs officer":                "bachelor",
    "public project manager":         "bachelor",

    "biology researcher":             "master",
    "applied chemistry researcher":   "master",
    "biotechnology engineer":         "bachelor",
    "laboratory testing specialist":  "bachelor",
    "applied physics researcher":     "master",

    "show director":                  "bachelor",
    "screenwriter":                   "bachelor",
    "sports coach":                   "vocational",
    "artist manager":                 "bachelor",
    "cultural heritage conservator":  "bachelor",
}

# role → list of primary SIMGR dimensions most affected (ordered by impact)
ROLE_SIMGR_INFLUENCE: Dict[str, List[str]] = {
    "agricultural engineer":          ["skill", "education", "goal_alignment"],
    "livestock engineer":             ["skill", "education", "goal_alignment"],
    "aquaculture engineer":           ["skill", "education", "goal_alignment"],
    "agricultural quality inspector": ["skill", "experience", "goal_alignment"],
    "food technology engineer":       ["skill", "education", "goal_alignment"],

    "civil construction engineer":    ["skill", "experience", "education"],
    "bridge and road engineer":       ["skill", "experience", "education"],
    "structural architect":           ["skill", "education", "goal_alignment"],
    "construction site supervisor":   ["experience", "skill", "preference"],
    "construction project manager":   ["experience", "skill", "goal_alignment"],

    "manufacturing engineer":         ["skill", "experience", "education"],
    "quality assurance engineer":     ["skill", "experience", "goal_alignment"],
    "lean six sigma specialist":      ["skill", "experience", "goal_alignment"],
    "materials engineer":             ["skill", "education", "experience"],
    "production line technician":     ["skill", "experience", "preference"],

    "bank credit specialist":         ["skill", "experience", "education"],
    "investment analyst":             ["skill", "education", "goal_alignment"],
    "risk management specialist":     ["skill", "education", "experience"],
    "insurance consultant":           ["skill", "preference", "goal_alignment"],
    "securities trader":              ["skill", "experience", "goal_alignment"],

    "hotel manager":                  ["experience", "skill", "preference"],
    "tour operator":                  ["skill", "experience", "preference"],
    "tour guide":                     ["skill", "preference", "experience"],
    "restaurant manager":             ["experience", "skill", "preference"],
    "event coordinator":              ["skill", "experience", "preference"],

    "government official":            ["education", "experience", "goal_alignment"],
    "policy planning specialist":     ["education", "skill", "goal_alignment"],
    "foreign affairs specialist":     ["education", "skill", "preference"],
    "customs officer":                ["experience", "education", "skill"],
    "public project manager":         ["experience", "skill", "education"],

    "biology researcher":             ["education", "skill", "goal_alignment"],
    "applied chemistry researcher":   ["education", "skill", "goal_alignment"],
    "biotechnology engineer":         ["skill", "education", "goal_alignment"],
    "laboratory testing specialist":  ["skill", "experience", "education"],
    "applied physics researcher":     ["education", "skill", "goal_alignment"],

    "show director":                  ["skill", "experience", "preference"],
    "screenwriter":                   ["skill", "preference", "goal_alignment"],
    "sports coach":                   ["experience", "skill", "preference"],
    "artist manager":                 ["skill", "experience", "preference"],
    "cultural heritage conservator":  ["skill", "education", "goal_alignment"],
}


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — SIMGR WEIGHT IMPACT RULES
# ══════════════════════════════════════════════════════════════════════════════

# goal_alignment_score multiplier when preferred_industry matches role industry
# Applied as: effective_goal_score = base_goal_score * multiplier  (capped at 100)
SIMGR_GOAL_MULTIPLIERS: Dict[str, float] = {
    "agriculture_aquaculture_food":            1.15,
    "construction_architecture_infrastructure": 1.15,
    "manufacturing_industrial_processing":     1.12,
    "banking_insurance_investment":            1.20,
    "tourism_hospitality_services":            1.10,
    "public_administration_diplomacy":         1.10,
    "science_research_biotechnology":          1.18,
    "arts_culture_sports":                     1.08,
}

# goal_alignment_score additive penalty when excluded_industry matches role industry
# Applied as: effective_goal_score = base_goal_score - penalty  (floored at 0)
SIMGR_EXCLUSION_PENALTY: Dict[str, float] = {
    "agriculture_aquaculture_food":            20.0,
    "construction_architecture_infrastructure": 18.0,
    "manufacturing_industrial_processing":     18.0,
    "banking_insurance_investment":            22.0,
    "tourism_hospitality_services":            15.0,
    "public_administration_diplomacy":         15.0,
    "science_research_biotechnology":          20.0,
    "arts_culture_sports":                     12.0,
}

# education_score upper cap (0-100) applied when user education is below role baseline
# Key = role's baseline, value = score cap when user is exactly one level below
SIMGR_EDUCATION_CAP: Dict[str, float] = {
    # user is one tier below baseline  →  cap applied to education_score
    "vocational_below_bachelor":   60.0,
    "high_school_below_vocational": 40.0,
    "high_school_below_bachelor":  40.0,
    "bachelor_below_master":       70.0,
    "master_below_phd":            80.0,
}

# skill_score multiplicative penalty per missing required skill domain
# Applied as: skill_score *= (1 - penalty_per_domain) ^ missing_domain_count
SIMGR_SKILL_PENALTY_PER_MISSING_DOMAIN: float = 0.08   # 8% reduction per absent domain
SIMGR_SKILL_PENALTY_MAX_REDUCTION: float = 0.40        # total penalty capped at -40%

# Education level ordering for cap lookups (ascending rank)
EDUCATION_LEVEL_ORDER: Dict[str, int] = {
    "high_school": 0,
    "vocational":  1,
    "bachelor":    2,
    "master":      3,
    "phd":         4,
}


def get_education_cap(user_education: str, role: str) -> float:
    """
    Return the education_score cap for *user_education* against *role* baseline.

    Returns 100.0 (no cap) when user meets or exceeds the baseline.
    """
    baseline = ROLE_EDUCATION_BASELINE.get(role, "bachelor")
    user_rank = EDUCATION_LEVEL_ORDER.get(user_education.lower(), 2)
    base_rank = EDUCATION_LEVEL_ORDER.get(baseline.lower(), 2)
    gap = base_rank - user_rank
    if gap <= 0:
        return 100.0
    if user_rank == 0 and base_rank == 1:
        return SIMGR_EDUCATION_CAP["high_school_below_vocational"]
    if user_rank == 0 and base_rank >= 2:
        return SIMGR_EDUCATION_CAP["high_school_below_bachelor"]
    if user_rank == 1 and base_rank == 2:
        return SIMGR_EDUCATION_CAP["vocational_below_bachelor"]
    if user_rank == 2 and base_rank == 3:
        return SIMGR_EDUCATION_CAP["bachelor_below_master"]
    if user_rank == 3 and base_rank == 4:
        return SIMGR_EDUCATION_CAP["master_below_phd"]
    return 40.0  # multiple tiers below: hard cap


def compute_skill_penalty(user_skill_domains: List[str], role: str) -> float:
    """
    Return a skill_score multiplier in (0, 1] accounting for missing domains.

    multiplier = max(1 - PENALTY * missing_count, 1 - MAX_REDUCTION)
    """
    required = set(ROLE_SKILL_DOMAINS.get(role, []))
    if not required:
        return 1.0
    user_set = {d.lower().strip() for d in user_skill_domains}
    missing = len(required - user_set)
    reduction = min(
        SIMGR_SKILL_PENALTY_PER_MISSING_DOMAIN * missing,
        SIMGR_SKILL_PENALTY_MAX_REDUCTION,
    )
    return round(1.0 - reduction, 4)


def apply_goal_multiplier(base_score: float, preferred_industries: List[str], role: str) -> float:
    """Apply goal_alignment multiplier when industry preference matches role."""
    industry = ROLE_INDUSTRY_MAP.get(role, "")
    if industry in preferred_industries:
        mult = SIMGR_GOAL_MULTIPLIERS.get(industry, 1.0)
        return min(100.0, base_score * mult)
    return base_score


def apply_exclusion_penalty(base_score: float, excluded_industries: List[str], role: str) -> float:
    """Apply goal_alignment penalty when role industry is excluded."""
    industry = ROLE_INDUSTRY_MAP.get(role, "")
    if industry in excluded_industries:
        penalty = SIMGR_EXCLUSION_PENALTY.get(industry, 0.0)
        return max(0.0, base_score - penalty)
    return base_score


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — 6-STEP PROFILE COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════════

# For each profile step: list of new keys required by the extended taxonomy
# Format: step_id → list of (key_name, type, description)
STEP_COMPATIBILITY: Dict[str, List[tuple]] = {
    "step1_profile": [
        # No new keys required; mobility + languages already collected
    ],
    "step2_skills": [
        ("skill_domains",    "List[str]", "Normalised skill domain tags per skill entry"),
        ("years_used",       "float",     "Years of practical usage per skill (existing key)"),
        ("certified",        "bool",      "Whether skill is certified (existing key)"),
        ("real_world_used",  "bool",      "Whether skill has real-world project usage (existing key)"),
    ],
    "step3_interests": [
        ("preferred_industry", "List[str]", "Industry enum list from INDUSTRY_ENUM keys (existing key)"),
        ("excluded_industry",  "List[str]", "Industry enums to exclude (existing key)"),
        ("work_style",         "str",       "remote|hybrid|onsite (existing key)"),
    ],
    "step4_education": [
        # education_level already collected; no new keys needed
        # education_field_of_study already collected; no new keys needed
    ],
    "step5_experience": [
        ("domains",         "List[str]", "Industry domains from INDUSTRY_ENUM keys (existing key, extend enum)"),
        ("years",           "float",     "Total years of professional experience (existing key)"),
    ],
    "step6_goals": [
        ("career_aspirations", "List[str]", "Target role names from ROLE_INDUSTRY_MAP keys (extend values)"),
        ("timeline_years",     "int",       "Target achievement horizon in years (existing key)"),
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — VALIDATION CONSTRAINTS
# ══════════════════════════════════════════════════════════════════════════════

VALID_INDUSTRY_ENUMS = frozenset(INDUSTRY_ENUM.keys())
VALID_ROLE_KEYS      = frozenset(ROLE_INDUSTRY_MAP.keys())


def validate_industry_enum(value: str) -> bool:
    """Return True iff value is a registered industry enum."""
    return value in VALID_INDUSTRY_ENUMS


def validate_role_industry_mapping(role: str) -> bool:
    """Return True iff role has exactly one primary industry mapping."""
    return role in ROLE_INDUSTRY_MAP


def get_primary_industry(role: str) -> str:
    """
    Return the single primary industry for a role.
    Raises KeyError if role is not registered (prevents duplicate classification).
    """
    if role not in ROLE_INDUSTRY_MAP:
        raise KeyError(
            f"Role '{role}' has no primary industry mapping. "
            "Register it in ROLE_INDUSTRY_MAP before use."
        )
    return ROLE_INDUSTRY_MAP[role]


def assert_no_duplicate_classification(role: str) -> None:
    """
    Assert that role maps to exactly one industry.
    This is guaranteed by the dict structure — each key appears once.
    Raises AssertionError if the invariant is somehow violated.
    """
    industry = get_primary_industry(role)
    candidates = [r for r, ind in ROLE_INDUSTRY_MAP.items() if ind == industry and r == role]
    assert len(candidates) == 1, (
        f"Duplicate classification detected for role '{role}': {candidates}"
    )


__all__ = [
    "INDUSTRY_ENUM",
    "ROLE_INDUSTRY_MAP",
    "ROLE_SKILL_DOMAINS",
    "ROLE_EDUCATION_BASELINE",
    "ROLE_SIMGR_INFLUENCE",
    "SIMGR_GOAL_MULTIPLIERS",
    "SIMGR_EXCLUSION_PENALTY",
    "SIMGR_EDUCATION_CAP",
    "SIMGR_SKILL_PENALTY_PER_MISSING_DOMAIN",
    "SIMGR_SKILL_PENALTY_MAX_REDUCTION",
    "EDUCATION_LEVEL_ORDER",
    "STEP_COMPATIBILITY",
    "VALID_INDUSTRY_ENUMS",
    "VALID_ROLE_KEYS",
    "get_education_cap",
    "compute_skill_penalty",
    "apply_goal_multiplier",
    "apply_exclusion_penalty",
    "validate_industry_enum",
    "validate_role_industry_mapping",
    "get_primary_industry",
    "assert_no_duplicate_classification",
]
