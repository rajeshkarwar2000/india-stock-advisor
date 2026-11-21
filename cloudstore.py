"""Cloud copy of the demo account in a *secret GitHub Gist* (free), so it survives Streamlit restarts and updates.

Streamlit Community Cloud wipes its disk on every update or reboot, so the account is also saved here.
Needs a GitHub token with the "gist" permission in Streamlit secrets (GITHUB_TOKEN). Without it everything else still works.
One gist (description "india-stock-advisor-data") holds one file per demo account: <name>.json
"""
import hashlib
import threading
import time

import requests

HTTP = requests                       # tests replace this with a fake
API = "https://api.github.com"
DESC = "india-stock-advisor-data"
STATUS = {}                           # user -> dict(ts, ok, msg): shown in the Account tab
_LOCK = threading.Lock()
_GID = {}                             # token fingerprint -> gist id
_LAST = {}                            # user -> dict(hash, ts)


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _fp(token):
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def find_gist(token):
    """Id of our gist, or None. Remembered after the first lookup."""
    k = _fp(token)
    if k in _GID:
        return _GID[k]
    for page in range(1, 6):
        r = HTTP.get(f"{API}/gists", headers=_headers(token), params={"per_page": 100, "page": page}, timeout=15)
        r.raise_for_status()
        items = r.json()
        for g in items:
            if g.get("description") == DESC:
                _GID[k] = g["id"]
                return g["id"]
        if len(items) < 100:
            break
    return None


def load(token, user):
    """Saved account text for this user, or None if nothing is saved yet."""
    gid = find_gist(token)
    if not gid:
        return None
    r = HTTP.get(f"{API}/gists/{gid}", headers=_headers(token), timeout=15)
    r.raise_for_status()
    f = (r.json().get("files") or {}).get(f"{user}.json")
    if not f:
        return None
    if f.get("truncated") and f.get("raw_url"):
        raw = HTTP.get(f["raw_url"], headers=_headers(token), timeout=15)
        raw.raise_for_status()
        return raw.text
    return f.get("content")


def save(token, user, text):
    """Write the account text (creates the secret gist on first use). Returns the gist id."""
    files = {f"{user}.json": {"content": text}}
    gid = find_gist(token)
    if gid:
        r = HTTP.patch(f"{API}/gists/{gid}", headers=_headers(token), json={"files": files}, timeout=20)
    else:
        r = HTTP.post(f"{API}/gists", headers=_headers(token), json={"description": DESC, "public": False, "files": files}, timeout=20)
    r.raise_for_status()
    gid = r.json().get("id") or gid
    _GID[_fp(token)] = gid
    return gid


def sync_async(token, user, text, min_gap=5, force=False):
    """Save in the background when the text changed since the last good save (force=True: save anyway, e.g. when the app is
    opened). Returns True if an upload was started."""
    h = hashlib.sha256(text.encode()).hexdigest()
    now = time.time()
    with _LOCK:
        last = _LAST.get(user, {})
        if not force and (last.get("hash") == h or now - last.get("ts", 0) < min_gap):
            return False
        _LAST[user] = {"hash": last.get("hash"), "ts": now}

    def work():
        try:
            save(token, user, text)
            with _LOCK:
                _LAST[user] = {"hash": h, "ts": time.time()}
            STATUS[user] = dict(ts=time.time(), ok=True, msg="saved")
        except Exception as e:                                   # network down, token wrong, rate limit...
            STATUS[user] = dict(ts=time.time(), ok=False, msg=str(e)[:160])

    threading.Thread(target=work, daemon=True).start()
    return True
