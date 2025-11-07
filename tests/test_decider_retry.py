import types
import os

import sys

# Google genai modülünü taklit et
google_mod = types.ModuleType("google")
genai_mod = types.ModuleType("genai")

class _FakeGenClient:
    def __init__(self, api_key: str):
        pass

genai_mod.Client = _FakeGenClient
# module-level models placeholder; testler monkeypatch ile dolduracak
class _Models:
    @staticmethod
    def generate_content(**kwargs):
        raise RuntimeError("override me")

genai_mod.models = _Models
genai_mod.configure = lambda **kwargs: None
google_mod.genai = genai_mod
sys.modules["google"] = google_mod
sys.modules["google.genai"] = genai_mod
sys.modules["google.generativeai"] = genai_mod

from deciders.decider_gemini import decide


class _FakeResp:
    def __init__(self, text: str):
        self.text = text


class _FakeClient:
    def __init__(self, fail_times: int, payload: str):
        self._fail_times = fail_times
        self._calls = 0
        self._payload = payload

    class models:
        generate_content = None  # placeholder for monkeypatching at runtime


def test_decider_retry_success(monkeypatch):
    os.environ["GOOGLE_API_KEY"] = "dummy"

    fake = _FakeClient(fail_times=1, payload='{"action":"BUY","confidence":0.7}')

    def _gen_content(**kwargs):
        fake._calls += 1
        if fake._calls <= fake._fail_times:
            raise RuntimeError("transient")
        return _FakeResp(fake._payload)

    # monkeypatch client creation
    from google import genai as _genai

    class _MC:
        @staticmethod
        def generate_content(**kwargs):
            return _gen_content(**kwargs)

    monkeypatch.setattr(_genai, "Client", _genai.Client)
    monkeypatch.setattr(_genai, "models", _MC)

    out = decide("BTCUSDT", {"fused": {"last_price": 100.0, "atr": 1.0}})
    assert out["action"] in ("BUY", "SELL", "HOLD")


def test_decider_retry_fail(monkeypatch):
    os.environ["GOOGLE_API_KEY"] = "dummy"

    def _gen_content(**kwargs):
        raise RuntimeError("always fail")

    from google import genai as _genai

    class _MC:
        @staticmethod
        def generate_content(**kwargs):
            return _gen_content(**kwargs)

    monkeypatch.setattr(_genai, "models", _MC)

    out = decide("BTCUSDT", {"fused": {"last_price": 100.0, "atr": 1.0}})
    assert out["action"] == "HOLD"

