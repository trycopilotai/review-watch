#!/usr/bin/env python3
"""Record the watch session again and refresh the evidence manifest.

    python3 scripts/record_session.py

The commands are the ones listed in ``evidence/demo-manifest.json``.
They run in a throwaway directory that holds a copy of ``skills/`` and
a synthetic worktree, ``worktree/``: a git repository with one commit
of the file in ``APP`` below. ``bin/`` holds a link to the ``rg`` found
on ``PATH``, so the session uses ripgrep; the script fails if there is
none. The transcript is what a shell would show: each command line,
the output (standard output and standard error together), and the exit
status. Nothing in it is edited; every path the commands print is
relative to the throwaway directory.

The manifest's hashes of ``SKILL.md``, the program and the transcript
are then rewritten, with the date, the ripgrep version and the bash
version. Run
``make demo`` afterwards to rebuild the images.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "demo-manifest.json"
APP = """def total(prices):
    return sum(prices)

"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(workdir: Path, environment: dict) -> None:
    """The skill copy and the synthetic worktree the session uses."""
    shutil.copytree(
        ROOT / "skills",
        workdir / "skills",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (workdir / "home").mkdir()
    (workdir / "tmp").mkdir()
    worktree = workdir / "worktree"
    worktree.mkdir()
    (worktree / "app.py").write_text(APP, encoding="utf-8")
    for arguments in (
        ["init", "--quiet", str(worktree)],
        ["-C", str(worktree), "add", "app.py"],
        ["-C", str(worktree), "commit", "--quiet", "-m", "Start"],
    ):
        subprocess.run(["git", *arguments], check=True, env=environment)


def record(commands: list, workdir: Path, environment: dict) -> str:
    define, steps = commands[0], commands[1:]
    lines = ["$ " + define]
    for step in steps:
        result = subprocess.run(
            ["bash", "-c", define + "\n" + step],
            cwd=str(workdir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lines.append("$ " + step)
        lines.extend(result.stdout.splitlines())
        lines.append('$ echo "exit status: $?"')
        lines.append("exit status: %d" % result.returncode)
    return "\n".join(lines) + "\n"


def main() -> int:
    ripgrep = shutil.which("rg")
    if ripgrep is None:
        print("rg is not on PATH; the session is recorded with ripgrep")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    commands = manifest["invocation"]["commands"]
    with tempfile.TemporaryDirectory() as scratch:
        workdir = Path(scratch).resolve() / "capture"
        bindir = workdir / "bin"
        bindir.mkdir(parents=True)
        (bindir / "rg").symlink_to(ripgrep)
        environment = {
            "PATH": "%s:/usr/bin:/bin" % bindir,
            "TMPDIR": str(workdir / "tmp"),
            "HOME": str(workdir / "home"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Example",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Example",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        prepare(workdir, environment)
        transcript_text = record(commands, workdir, environment)
        version = subprocess.run(
            ["rg", "--version"],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()[0]
        shell = subprocess.run(
            ["bash", "-c", 'echo "GNU bash $BASH_VERSION"'],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if str(workdir) in transcript_text or scratch in transcript_text:
            print("the transcript carries the capture path; not writing it")
            return 1

    transcript = ROOT / manifest["output"]["path"]
    transcript.write_text(transcript_text, encoding="utf-8")

    manifest["date"] = datetime.date.today().isoformat()
    manifest["invocation"]["search_tool"] = version
    manifest["invocation"]["shell"] = shell
    manifest["skill"]["sha256"] = sha256(ROOT / manifest["skill"]["path"])
    for program in manifest["programs"]:
        program["sha256"] = sha256(ROOT / program["path"])
    manifest["output"]["sha256"] = sha256(transcript)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("wrote %s" % transcript.relative_to(ROOT))
    print("wrote %s" % MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
