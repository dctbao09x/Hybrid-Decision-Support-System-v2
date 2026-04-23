import json
from functools import wraps

from backend.scoring.engine import RankingEngine
from backend.scoring.strategies import ScoringStrategy
from backend.scoring.calculator import SIMGRCalculator
from backend.scoring.models import UserProfile, CareerData

trace=[]

def trace_wrap(cls, method_name, label):
    orig=getattr(cls, method_name)
    @wraps(orig)
    def wrapped(*args, **kwargs):
        trace.append(label)
        return orig(*args, **kwargs)
    setattr(cls, method_name, wrapped)

trace_wrap(RankingEngine, "rank", "RankingEngine.rank")
trace_wrap(ScoringStrategy, "rank", "ScoringStrategy.rank")
trace_wrap(ScoringStrategy, "score_one", "ScoringStrategy.score_one")
trace_wrap(SIMGRCalculator, "calculate", "SIMGRCalculator.calculate")
trace_wrap(SIMGRCalculator, "_compute_component", "SIMGRCalculator._compute_component")

engine=RankingEngine()
user=UserProfile(skills=["python"],interests=["ai"],education_level="Bachelor",ability_score=0.5,confidence_score=0.5)
careers=[CareerData(name="ml_engineer",required_skills=["python","ml"],preferred_skills=["pytorch"],domain="ai",domain_interests=["ai"],ai_relevance=0.9,growth_rate=0.85,competition=0.4)]
results=engine.rank(user=user, careers=careers)

print(json.dumps({
    "trace": trace,
    "trace_len": len(trace),
    "result_len": len(results),
    "first_result_total_score": (results[0].total_score if results else None)
}, ensure_ascii=False))
