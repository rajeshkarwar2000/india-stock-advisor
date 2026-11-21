import json, time
import cloudstore as C


class Resp:
    def __init__(self, data=None, text="", code=200):
        self._d, self.text, self.code = data, text, code
    def json(self): return self._d
    def raise_for_status(self):
        if self.code >= 400: raise RuntimeError(f"HTTP {self.code}")


class FakeGitHub:
    """Just enough of the Gist API: list, get, create, update."""
    def __init__(self): self.gists, self.calls = {}, []
    def get(self, url, headers=None, params=None, timeout=0):
        self.calls.append(("GET", url))
        assert headers["Authorization"].startswith("Bearer ")
        if url.endswith("/gists"): return Resp([dict(id=i, description=g["description"]) for i, g in self.gists.items()])
        if "/gists/" in url: return Resp(self.gists[url.rsplit("/", 1)[1]])
        return Resp(text="RAW")
    def post(self, url, headers=None, json=None, timeout=0):
        self.calls.append(("POST", url)); gid = f"g{len(self.gists) + 1}"
        assert json["public"] is False
        self.gists[gid] = dict(id=gid, description=json["description"], files={k: dict(content=v["content"]) for k, v in json["files"].items()})
        return Resp(self.gists[gid])
    def patch(self, url, headers=None, json=None, timeout=0):
        self.calls.append(("PATCH", url)); g = self.gists[url.rsplit("/", 1)[1]]
        for k, v in json["files"].items(): g["files"][k] = dict(content=v["content"])
        return Resp(g)


def _fresh(monkeypatch=None):
    C._GID.clear(); C._LAST.clear(); C.STATUS.clear(); C.HTTP = FakeGitHub(); return C.HTTP


def test_save_creates_secret_gist_then_updates_and_loads():
    gh = _fresh()
    assert C.load("tok", "me") is None                                   # nothing saved yet
    C.save("tok", "me", json.dumps({"trades": [1]})); C.save("tok", "me", json.dumps({"trades": [1, 2]})); C.save("tok", "rahul", "{}")
    assert [c[0] for c in gh.calls if c[0] in ("POST", "PATCH")] == ["POST", "PATCH", "PATCH"]   # one gist, one file per account
    assert json.loads(C.load("tok", "me"))["trades"] == [1, 2] and C.load("tok", "rahul") == "{}" and C.load("tok", "nobody") is None
    assert len(gh.gists) == 1


def test_finds_existing_gist_after_a_restart():
    gh = _fresh(); C.save("tok", "me", "{\"a\":1}")
    C._GID.clear()                                                        # server restarted: forgets the id, must find it again
    assert C.load("tok", "me") == "{\"a\":1}" and len(gh.gists) == 1


def test_sync_async_uploads_once_and_reports_errors():
    gh = _fresh()
    assert C.sync_async("tok", "me", "{\"x\":1}", min_gap=0)
    for _ in range(50):
        if C.STATUS.get("me"): break
        time.sleep(0.05)
    assert C.STATUS["me"]["ok"] and C.load("tok", "me") == "{\"x\":1}"
    assert not C.sync_async("tok", "me", "{\"x\":1}", min_gap=0)          # unchanged: no second upload
    class Down(FakeGitHub):
        def get(self, *a, **k): raise RuntimeError("network down")
    C.HTTP = Down(); C._GID.clear()
    assert C.sync_async("tok", "me", "{\"x\":2}", min_gap=0)
    for _ in range(50):
        if not C.STATUS["me"]["ok"]: break
        time.sleep(0.05)
    assert not C.STATUS["me"]["ok"] and "network down" in C.STATUS["me"]["msg"]
    assert C.sync_async("tok", "me", "{\"x\":2}", min_gap=0)              # a failed save is retried next time


def test_force_saves_even_when_nothing_changed():
    gh = _fresh()
    assert C.sync_async("tok", "me", "{\"x\":1}", min_gap=0)
    for _ in range(50):
        if C.STATUS.get("me"): break
        time.sleep(0.05)
    n = len([c for c in gh.calls if c[0] in ("POST", "PATCH")])
    assert not C.sync_async("tok", "me", "{\"x\":1}", min_gap=0)                 # unchanged: skipped
    C.STATUS.clear()
    assert C.sync_async("tok", "me", "{\"x\":1}", min_gap=0, force=True)         # app opened: saved anyway
    for _ in range(50):
        if C.STATUS.get("me"): break
        time.sleep(0.05)
    assert len([c for c in gh.calls if c[0] in ("POST", "PATCH")]) == n + 1
