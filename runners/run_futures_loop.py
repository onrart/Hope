import os
import time
from dotenv import load_dotenv

from core.monitoring import start_http_server
from runners.run_futures import main as run_once


def main():
    load_dotenv()
    # Monitoring server tek sefer açılır
    try:
        port_env = os.getenv("MONITOR_PORT", "9108")
        port = int(port_env) if port_env else 9108
        p = start_http_server(port)
        print(f"[MONITOR] metrics on :{p}/metrics")
    except Exception:
        pass

    interval = int(os.getenv("LOOP_SECONDS", "60"))
    print(f"[LOOP] running futures every {interval}s; Ctrl+C to stop")
    while True:
        try:
            run_once()
        except Exception as e:
            print("[LOOP][ERROR]", repr(e))
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()


