"""Inspect staged/tracked artifacts without exposing matching secret values."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

PATTERNS = (
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)


def main():
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={Path.cwd().as_posix()}", *args]
        )

    names = git("diff", "--cached", "--name-only", "--diff-filter=ACM").decode().splitlines()
    for name in names:
        raw = git("show", f":{name}")
        assert len(raw) < 15_000_000, f"Large artifact: {name}"
        assert not name.startswith(("output/", ".venv/", ".cache/", "data/raw/", ".local/")), name
        assert name != ".env", "Environment file cannot be published"
        if name.endswith((".png", ".zip")):
            continue
        content = raw.decode("utf-8-sig")
        assert not any(re.search(pattern, content) for pattern in PATTERNS), f"Secret in {name}"
    manifest = json.loads(git("show", ":data/sample/manifest.json"))
    for name, digest in manifest["files"].items():
        raw = git("show", f":data/sample/{name}")
        assert hashlib.sha256(raw).hexdigest() == digest, f"Staged snapshot byte mismatch: {name}"
    print(f"PASS: {len(names)} staged artifacts; all committed snapshot byte hashes match")


if __name__ == "__main__":
    main()
