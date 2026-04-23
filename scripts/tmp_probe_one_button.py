import time
import requests

payload = {
    "contract_version": "2026-04-02.v1",
    "request_schema_version": "one_button.request.v1",
    "user_id": "probe_ui_user",
    "scoring_input": {
        "personal_profile": {
            "ability_score": 0.72,
            "confidence_score": 0.66,
            "interests": ["technology", "science"],
        },
        "experience": {"years": 3, "domains": ["software engineering"]},
        "goals": {"career_aspirations": ["software engineer"], "timeline_years": 4},
        "skills": ["python", "sql"],
        "education": {"level": "Bachelor", "field_of_study": "Computer Science"},
        "preferences": {"preferred_domains": ["technology"], "work_style": "hybrid"},
    },
}

for path in ["/api/v1/one-button/run", "/api/v1/decision/run"]:
    t0 = time.perf_counter()
    response = requests.post(f"http://127.0.0.1:8000{path}", json=payload, timeout=120)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    body = response.json()

    print(f"PATH {path} STATUS {response.status_code} LAT_MS {elapsed_ms:.2f}")
    if response.status_code >= 400:
        detail = body.get("detail", {})
        print("ERROR", detail.get("error"), "MESSAGE", detail.get("message"))
    else:
        market_stage_status = body.get("stages", {}).get("market_data", {}).get("status")
        fallback_events = body.get("diagnostics", {}).get("fallback_taxonomy_events", [])
        missing_market_events = [
            event for event in fallback_events if event.get("taxonomy") == "missing_market_signal"
        ]
        print(
            "OK",
            body.get("status"),
            "MARKET_STAGE",
            market_stage_status,
            "MISSING_MARKET_EVENTS",
            len(missing_market_events),
        )
