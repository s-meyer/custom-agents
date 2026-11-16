from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo"
BARE = ROOT / "shared/work/demo-repo.git"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def main() -> None:
    BARE.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(BARE, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix="agent-demo-") as temp:
        source = Path(temp) / "source"
        source.mkdir()
        for name in ("Makefile", "src", "include"):
            item = DEMO / name
            shutil.copytree(item, source / name) if item.is_dir() else shutil.copy2(item, source / name)
        git(source, "init", "-b", "main")
        git(source, "config", "user.name", "demo")
        git(source, "config", "user.email", "demo@localhost")
        git(source, "add", "Makefile", "src", "include")
        git(source, "commit", "-m", "Initial demo project")
        git(BARE.parent, "init", "--bare", str(BARE))
        git(source, "remote", "add", "origin", str(BARE))
        git(source, "push", "origin", "main")


if __name__ == "__main__":
    main()
