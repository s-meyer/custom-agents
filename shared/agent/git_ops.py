from __future__ import annotations

import asyncio
from pathlib import Path


class GitError(RuntimeError):
    pass


async def git(cwd: Path, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise GitError(stderr.decode(errors="replace").strip() or f"git {' '.join(args)} failed")
    return stdout.decode().strip()


async def checkout(repository: str, base_branch: str, work_branch: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    await git(target.parent, "clone", repository, str(target))
    await git(target, "checkout", "-b", work_branch, f"origin/{base_branch}")


async def publish(target: Path, branch: str, base_branch: str) -> tuple[str | None, str]:
    changed = await git(target, "status", "--porcelain")
    commit_hash = None
    if changed:
        await git(target, "add", "-A")
        await git(target, "commit", "-m", "Agent task changes")
        commit_hash = await git(target, "rev-parse", "HEAD")
        await git(target, "push", "origin", branch)
    patch = await git(target, "diff", f"origin/{base_branch}...HEAD")
    return commit_hash, patch
