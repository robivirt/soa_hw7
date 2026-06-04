from __future__ import annotations

import shutil
import subprocess
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "generated" / "openapi"


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{ROOT}:/local",
        "openapitools/openapi-generator-cli:v7.10.0",
        "generate",
        "-i",
        "/local/docs/openapi.yaml",
        "-g",
        "python-fastapi",
        "-o",
        "/local/app/generated/openapi",
        "--additional-properties=packageName=generated_server",
    ]
    subprocess.run(command, check=True)
    subprocess.run(
        ["python3", "scripts/postprocess_generated_openapi.py"],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
