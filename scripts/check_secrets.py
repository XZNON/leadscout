#!/usr/bin/env python3
"""Pre-commit secret scan. Fails the commit if a likely API key is staged.

Run manually:  python scripts/check_secrets.py
As a hook:     installed at .git/hooks/pre-commit (see scripts/install_hooks.py).

Intentionally simple and dependency-free. Better a false positive you override with
intent than a key in git history.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Patterns that look like real secrets. Keep blunt; tune as false positives appear.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Generic secret assignment", re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
    )),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
]

# Files/paths that legitimately contain placeholder-looking strings.
ALLOWLIST = {".env.example", "scripts/check_secrets.py"}


def staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return [f.strip() for f in (out.stdout or "").splitlines() if f.strip()]


def staged_content(path: str) -> str:
    out = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return out.stdout or "" if out.returncode == 0 else ""


def main() -> int:
    findings: list[str] = []
    for path in staged_files():
        if path in ALLOWLIST or path.endswith(".env.example"):
            continue
        # A staged .env should never happen (gitignored) but guard anyway.
        if path == ".env" or path.startswith(".env."):
            findings.append(f"{path}: .env files must never be committed")
            continue
        content = staged_content(path)
        for line_no, line in enumerate(content.splitlines(), 1):
            for label, pat in PATTERNS:
                if pat.search(line):
                    findings.append(f"{path}:{line_no}: possible {label}")

    if findings:
        sys.stderr.write("\n[check_secrets] Commit blocked — possible secrets staged:\n")
        for f in findings:
            sys.stderr.write(f"  - {f}\n")
        sys.stderr.write(
            "\nRemove the secret (use .env), or if it is a false positive, "
            "commit with --no-verify and fix the pattern.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
