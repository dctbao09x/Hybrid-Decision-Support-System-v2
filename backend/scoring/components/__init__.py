# backend/scoring/components/__init__.py
"""
Scoring components (SIMGR standard).

Each component computes an atomic score [0, 1]:
- study: Skill match & education fit
- interest: Interest alignment
- market: Market attractiveness
- growth: Growth potential
- risk: Risk assessment (inverted, 1.0 = low risk)
"""
