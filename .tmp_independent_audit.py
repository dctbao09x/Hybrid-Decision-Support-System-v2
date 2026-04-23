import json, random, statistics
import numpy as np
from backend.scoring.scoring import SIMGRScorer
from backend.scoring.engine import RankingEngine
from backend.scoring.models import UserProfile, CareerData
from backend.scoring.config import DEFAULT_CONFIG

out = {}
scorer = SIMGRScorer(debug=True)
base = {"study":0.0,"interest":0.0,"market":0.0,"growth":0.0,"risk":0.0}
base_score = scorer.score(base)["total_score"]
weights = DEFAULT_CONFIG.simgr_weights.to_dict()
probe = {}
for k in ["study","interest","market","growth","risk"]:
    sample = base.copy(); sample[k]=1.0
    probe[k]=scorer.score(sample)["total_score"]
coeff = {k: probe[k]-base_score for k in probe}
out["formula_probe"]={"base_score":base_score,"weights":weights,"unit_outputs":probe,"differential":coeff}

n=600
rows=[]
for _ in range(n):
    S,I,M,G,R=[random.random() for _ in range(5)]
    y=scorer.score({"study":S,"interest":I,"market":M,"growth":G,"risk":R})["total_score"]
    rows.append((S,I,M,G,R,y))
arr=np.array(rows)
S,I,M,G,R,Y=[arr[:,i] for i in range(6)]
correls={
    "S": float(np.corrcoef(S,Y)[0,1]),
    "I": float(np.corrcoef(I,Y)[0,1]),
    "M": float(np.corrcoef(M,Y)[0,1]),
    "G": float(np.corrcoef(G,Y)[0,1]),
    "R": float(np.corrcoef(R,Y)[0,1]),
}
out["fuzz"]={
    "n":n,
    "corr":correls,
    "sat_zero":int(np.sum(np.isclose(Y,0.0))),
    "sat_one":int(np.sum(np.isclose(Y,1.0))),
    "mean_score":float(np.mean(Y)),
    "min_score":float(np.min(Y)),
    "max_score":float(np.max(Y)),
}

risk_curve=[]
for step in range(21):
    r=round(step*0.05,2)
    score=scorer.score({"study":0.8,"interest":0.8,"market":0.8,"growth":0.8,"risk":r})["total_score"]
    risk_curve.append((r,score))
out["risk_curve"]=risk_curve
out["risk_monotonic_nonincreasing"]=all(risk_curve[i][1]>=risk_curve[i+1][1] for i in range(len(risk_curve)-1))

bypass={"import_ok":False,"compute_ok":False,"result_len":0,"error":None}
try:
    engine=RankingEngine(default_config=DEFAULT_CONFIG)
    bypass["import_ok"]=True
    user=UserProfile(skills=["python"],interests=["ai"],education_level="Bachelor",ability_score=0.5,confidence_score=0.5)
    careers=[CareerData(name="test_career",required_skills=["python"],preferred_skills=[],domain="ai",domain_interests=["ai"],ai_relevance=0.8,growth_rate=0.8,competition=0.2)]
    res=engine.rank(user=user,careers=careers)
    bypass["compute_ok"]=True
    bypass["result_len"]=len(res)
except Exception as e:
    bypass["error"]=str(e)
out["bypass"]=bypass

fixed_input={"study":0.73,"interest":0.41,"market":0.66,"growth":0.52,"risk":0.37}
vals=[scorer.score(fixed_input)["total_score"] for _ in range(100)]
out["stability"]={
    "runs":100,
    "mean":float(statistics.mean(vals)),
    "variance":float(statistics.pvariance(vals)),
    "min":float(min(vals)),
    "max":float(max(vals)),
    "unique":len(set(vals)),
}

cases={
    "none_input":None,
    "nan_study":{"study":float('nan'),"interest":0.5,"market":0.5,"growth":0.5,"risk":0.5},
    "out_of_range":{"study":1.2,"interest":0.5,"market":0.5,"growth":0.5,"risk":0.5},
    "missing_keys":{"study":0.5,"interest":0.5},
}
inj={}
for name,payload in cases.items():
    try:
        result=scorer.score(payload)
        inj[name]={"ok":True,"result":result}
    except Exception as e:
        inj[name]={"ok":False,"error":str(e)}
out["failure_injection"]=inj

print(json.dumps(out, ensure_ascii=False))
