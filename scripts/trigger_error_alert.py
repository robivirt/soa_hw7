from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request


def main() -> None:
    api_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    deadline = time.time() + duration
    requests_sent = 0
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{api_url}/products", timeout=2)
        except urllib.error.HTTPError:
            pass
        except Exception as exc:
            print(f"request failed: {exc}")
        requests_sent += 1
        time.sleep(0.5)
    print(f"sent {requests_sent} unauthenticated API requests")


if __name__ == "__main__":
    main()
