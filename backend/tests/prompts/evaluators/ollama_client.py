import json
import os
import time
import urllib.request
import urllib.error

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("PROMPT_EVAL_MODEL", "llama3.2:1b")

class OllamaError(RuntimeError):
    pass

def _post(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise OllamaError(str(exc))
    return json.loads(raw)

def generate(prompt: str, model: str = None, format_json: bool = False, temperature: float = 0.1, timeout: int = 60):
    model_name = model or DEFAULT_MODEL
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature}
    }
    if format_json:
        payload["format"] = "json"

    url = f"{DEFAULT_HOST}/api/generate"
    start = time.time()
    data = _post(url, payload, timeout)
    latency_ms = int((time.time() - start) * 1000)

    response_text = data.get("response", "")
    prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(data.get("eval_count", 0) or 0)
    total_tokens = prompt_tokens + completion_tokens

    meta = {
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }
    return response_text, meta
