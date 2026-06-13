#!/usr/bin/env python3
"""Install the pre-commit secret check into .git/hooks. Run once: python scripts/install_hooks.py"""

from __future__ import annotations

import os
import stat
from pathlib import Path

HOOK = """#!/bin/sh
# LeadScout pre-commit: block staged secrets.
python scripts/check_secrets.py || exit 1
"""


def main() -> int:
    hooks_dir = Path(".git/hooks")
    if not hooks_dir.exists():
        print("No .git/hooks directory — run `git init` first.")
        return 1
    hook_path = hooks_dir / "pre-commit"
    hook_path.write_text(HOOK, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed pre-commit hook at {hook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
