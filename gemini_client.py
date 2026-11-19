"""Tiny Gemini REST client (generateContent)."""
import requests

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SYSTEM = ("You are a cautious equity research assistant for an Indian retail investor (NSE/BSE, prices in ₹). "
          "Use the app data provided as context and say when something is not in it. Give reasoning, entry/stop-loss "
          "ideas and key risks. Never promise or guarantee returns; say plainly that targets like +10-20% in a month "
          "or +100% in a year are uncertain and often not achieved. Mention that this is not SEBI-registered "
          "investment advice. Keep answers concise.")

def ask(api_key, model, history, context="", grounded=False, timeout=60):
    """history: list of {'role': 'user'|'model', 'text': str}. Returns reply text or raises RuntimeError."""
    contents = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history]
    body = {"system_instruction": {"parts": [{"text": SYSTEM + ("\n\nApp data:\n" + context if context else "")}]},
            "contents": contents}
    if grounded:
        body["tools"] = [{"google_search": {}}]
    r = requests.post(URL.format(model=model), json=body, timeout=timeout,
                      headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
    if r.status_code != 200:
        try: msg = r.json()["error"]["message"]
        except Exception: msg = r.text[:300]
        raise RuntimeError(f"Gemini error {r.status_code}: {msg}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip() or "(empty reply)"
    except Exception:
        raise RuntimeError("Gemini returned no answer (it may have been blocked). Try rephrasing.")
