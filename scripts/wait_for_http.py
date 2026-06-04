from __future__ import annotations

import sys
import time
import urllib.request


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: wait_for_http.py URL [timeout_seconds]")
    url = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return
        except Exception:
            time.sleep(1)
    raise SystemExit(f"{url} did not become ready within {timeout}s")


if __name__ == "__main__":
    main()
