import socket
import time
from urllib.request import urlopen

from core.monitoring import start_http_server, stop_http_server, inc_counter, observe_histogram, set_health


def _get_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_metrics_http_serves_and_updates():
    port = _get_free_port()
    actual = start_http_server(port)
    assert isinstance(actual, int)

    inc_counter("test_counter", 1, {"a": "b"})
    observe_histogram("test_latency_seconds", 0.12, {"op": "x"})
    time.sleep(0.05)

    with urlopen(f"http://127.0.0.1:{actual}/metrics", timeout=2) as r:
        body = r.read().decode("utf-8")
        assert "test_counter" in body
        assert 'a="b"' in body
        assert "test_latency_seconds_bucket" in body
        assert "_sum" in body and "_count" in body

    # health
    set_health({"last_snapshot_ts": 123.0})
    with urlopen(f"http://127.0.0.1:{actual}/health", timeout=2) as r:
        body = r.read().decode("utf-8")
        assert "last_snapshot_ts" in body

    stop_http_server()

