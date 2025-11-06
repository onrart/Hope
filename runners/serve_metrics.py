import os
import time
from core.monitoring import start_http_server


def main():
    port = int(os.getenv("MONITOR_PORT", "9108") or 9108)
    p = start_http_server(port)
    print(f"Monitoring server is up on :{p} (GET /metrics, /health)")
    keep = int(os.getenv("MONITOR_KEEPALIVE_SECONDS", "0") or 0)
    if keep <= 0:
        keep = 24 * 60 * 60
    try:
        time.sleep(keep)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


