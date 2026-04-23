**Breaking Changes**

1. `backend/taxonomy.py` is now a deprecated compatibility layer that re-exports data from the new taxonomy package. Direct edits to this file no longer affect taxonomy behavior.
1. `KnowledgeBaseService.get_education_hierarchy()` now derives its hierarchy from taxonomy datasets instead of the database.
1. `KnowledgeBaseService.get_job_requirements()` now normalizes `required_skills`, `preferred_skills`, and `min_education` via taxonomy. Output may differ in casing (e.g., `"HighSchool"` → `"High School"`).
1. `InputProcessor` now resolves `education_level`, `interest_tags`, and `skill_tags` through taxonomy. Canonical labels are returned; unknown education is normalized to `"unknown"`.
1. `backend/api.py` renamed to `backend/api_legacy.py` to avoid shadowing the `backend/api/` package used by `main.py`.
