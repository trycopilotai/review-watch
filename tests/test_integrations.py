#!/usr/bin/env python3
"""The packaging contract.

Facts this repository states in more than one place are
pinned here where a script can compare them: the name and
version, the claim and the transcript behind it, the demo
images, the install blocks, and the evidence hashes.

Runs offline with the standard library and `git`:

    python3 tests/test_integrations.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "review-watch"
PACKAGE = ROOT / "skills" / NAME
PROGRAM = PACKAGE / "scripts" / "watch.sh"
SKILL = PACKAGE / "SKILL.md"
README = ROOT / "README.md"
TRANSCRIPT = ROOT / "evidence" / "transcripts" / "watch-session.txt"
MANIFEST = ROOT / "evidence" / "demo-manifest.json"
RECORDER = ROOT / "scripts" / "record_session.py"
CLAIM = "watch.sh reports a marker written while it watches."
MARKER = "# AGENT: rename total to subtotal"
REPOSITORY = "https://github.com/trycopilotai/" + NAME


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(product: str) -> dict:
    return json.loads(read(ROOT / product / "plugin.json"))


def frontmatter(text: str) -> dict:
    """The `key: value` pairs between the two `---` lines."""
    lines = text.splitlines()
    if lines[0] != "---":
        raise AssertionError("SKILL.md does not open with frontmatter")
    end = lines.index("---", 1)
    fields: dict = {}
    key = None
    for line in lines[1:end]:
        match = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if match:
            key = match.group(1)
            fields[key] = match.group(2).strip()
            continue
        if key is None or not line.startswith(" "):
            raise AssertionError("unexpected frontmatter line: " + line)
        fields[key] = (fields[key] + " " + line.strip()).strip()
    for name, value in fields.items():
        if value.startswith(">-"):
            fields[name] = value[2:].strip()
    return fields


def interface_yaml(text: str) -> dict:
    """The quoted scalars under `interface:` in agents/openai.yaml."""
    lines = text.splitlines()
    if lines[0] != "interface:":
        raise AssertionError("openai.yaml does not start with interface:")
    fields: dict = {}
    key = None
    for line in lines[1:]:
        match = re.match(r"^  ([a-z_]+):\s*(.*)$", line)
        if match:
            key = match.group(1)
            fields[key] = match.group(2).strip()
            continue
        fields[key] = (fields[key] + " " + line.strip()).strip()
    for name, value in fields.items():
        if not (value.startswith('"') and value.endswith('"')):
            raise AssertionError(name + " is not a double-quoted scalar")
        fields[name] = value[1:-1]
    return fields


def install_blocks() -> list:
    return re.findall(r"```sh\nset -eu\n(.*?)```", read(README), flags=re.S)


class LayoutTest(unittest.TestCase):
    def test_skill_is_a_symlink_into_the_canonical_package(self) -> None:
        link = ROOT / "skill"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(str(link)), "skills/" + NAME)
        self.assertFalse(PACKAGE.is_symlink())

    def test_package_holds_what_the_readme_says_it_installs(self) -> None:
        for relative in (
            "SKILL.md",
            "agents/openai.yaml",
            "scripts/watch.sh",
        ):
            self.assertTrue((PACKAGE / relative).is_file(), relative)

    def test_history_has_no_co_author_trailer(self) -> None:
        messages = git("log", "--all", "--format=%B")
        self.assertNotIn("co-authored-by", messages.lower())


class SkillTest(unittest.TestCase):
    def test_frontmatter_is_name_and_description_only(self) -> None:
        fields = frontmatter(read(SKILL))
        self.assertEqual(sorted(fields), ["description", "name"])
        self.assertEqual(fields["name"], NAME)
        self.assertRegex(NAME, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(NAME), 64)
        self.assertTrue(fields["description"])
        self.assertLessEqual(len(fields["description"]), 1024)

    def test_skill_stays_under_five_hundred_lines(self) -> None:
        self.assertLess(len(read(SKILL).splitlines()), 500)

    def test_files_the_skill_points_at_exist(self) -> None:
        text = read(SKILL)
        for relative in ("scripts/watch.sh",):
            self.assertIn(relative, text)
            self.assertTrue((PACKAGE / relative).is_file(), relative)


class ManifestTest(unittest.TestCase):
    def test_both_manifests_agree(self) -> None:
        claude = manifest(".claude-plugin")
        codex = manifest(".codex-plugin")
        for field in (
            "name",
            "version",
            "description",
            "license",
            "homepage",
            "repository",
            "skills",
        ):
            self.assertEqual(claude[field], codex[field], field)
        self.assertEqual(claude["name"], NAME)
        self.assertEqual(claude["skills"], "./skills/")
        self.assertEqual(claude["repository"], REPOSITORY)
        self.assertEqual(claude["license"], "MIT")
        self.assertRegex(claude["version"], r"^\d+\.\d+\.\d+$")

    def test_a_release_tag_on_head_is_the_manifest_version(self) -> None:
        tags = git("tag", "--points-at", "HEAD").split()
        releases = [tag for tag in tags if tag.startswith("v")]
        if not releases:
            self.skipTest("HEAD carries no release tag")
        self.assertEqual(releases, ["v" + manifest(".claude-plugin")["version"]])

    def test_codex_interface_matches_the_agent_file(self) -> None:
        interface = manifest(".codex-plugin")["interface"]
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
            "websiteURL",
        ):
            self.assertTrue(interface.get(field), field)
        prompts = interface["defaultPrompt"]
        self.assertEqual(len(prompts), 1)
        self.assertIn("$" + NAME, prompts[0])
        agent = interface_yaml(read(PACKAGE / "agents" / "openai.yaml"))
        self.assertEqual(agent["default_prompt"], prompts[0])
        self.assertEqual(agent["display_name"], interface["displayName"])
        self.assertEqual(agent["short_description"], interface["shortDescription"])


class ReadmeTest(unittest.TestCase):
    def test_claim_is_on_its_own_line(self) -> None:
        self.assertIn(CLAIM, read(README).splitlines())

    def test_claim_is_at_most_sixty_characters(self) -> None:
        self.assertLessEqual(len(CLAIM), 60)

    def test_transcript_shows_a_marker_written_during_the_watch(self) -> None:
        lines = read(TRANSCRIPT).splitlines()
        clean = lines.index("$ watch worktree 2 1")
        self.assertEqual(lines[clean + 1], "REVIEW_WATCH_WINDOW_ENDED")
        before = lines[: clean]
        self.assertNotIn("AGENT", "\n".join(before))
        writes = [i for i, line in enumerate(lines) if line.startswith("$ (sleep 2;")]
        self.assertEqual(len(writes), 1)
        command = lines[writes[0]]
        # The marker is appended in the background, after the
        # watch has started, by the same command line.
        self.assertIn("printf '%s\\n' >> worktree/app.py) &" % MARKER, command)
        self.assertTrue(command.endswith("& watch worktree 30 1"))
        self.assertEqual(lines[writes[0] + 1], "REVIEW_WATCH_MARKERS")
        self.assertEqual(lines[writes[0] + 2], "worktree/app.py:4:" + MARKER)
        self.assertEqual(lines[writes[0] + 4], "exit status: 0")
        self.assertIn("REVIEW_WATCH_MARKERS", read(PROGRAM))

    def test_transcript_was_recorded_with_ripgrep(self) -> None:
        lines = read(TRANSCRIPT).splitlines()
        version = lines[lines.index("$ rg --version | head -n 1") + 1]
        self.assertTrue(version.startswith("ripgrep "))
        record = json.loads(read(MANIFEST))
        self.assertEqual(record["invocation"]["search_tool"], version)
        readme = " ".join(read(README).replace("`", "").split())
        self.assertIn("ran with ripgrep on PATH", readme)

    def test_each_install_block_pins_the_manifest_version(self) -> None:
        version = manifest(".claude-plugin")["version"]
        blocks = install_blocks()
        self.assertEqual(len(blocks), 2)
        roots = []
        for block in blocks:
            self.assertEqual(
                re.findall(r"^release=(\S+)$", block, flags=re.M),
                ["v" + version],
            )
            self.assertIn(REPOSITORY + " \\\n", block)
            self.assertIn('--branch "$release"', block)
            target = re.findall(r'^install_target="\$HOME/(\S+)"$', block, flags=re.M)
            self.assertEqual(len(target), 1)
            roots.append(target[0])
        self.assertEqual(
            sorted(roots),
            [".agents/skills/" + NAME, ".claude/skills/" + NAME],
        )

    def test_relative_links_resolve(self) -> None:
        targets = re.findall(r"\]\(([^)#]+)\)", read(README))
        self.assertTrue(targets)
        for target in targets:
            if target.startswith("http"):
                continue
            self.assertTrue((ROOT / target).exists(), target)

    def test_readme_says_what_was_not_measured(self) -> None:
        text = " ".join(read(README).split())
        self.assertIn("No agent invoked the skill", text)
        self.assertIn("has not been measured", text)

    def test_demo_is_offered_with_a_reduced_motion_poster(self) -> None:
        text = read(README)
        picture = re.search(r"<picture>(.*?)</picture>", text, flags=re.S)
        self.assertIsNotNone(picture)
        body = picture.group(1)
        self.assertIn('media="(prefers-reduced-motion: reduce)"', body)
        self.assertIn('srcset="assets/poster.svg"', body)
        self.assertIn('src="assets/demo.svg"', body)


class ExcludeRuleTest(unittest.TestCase):
    RULE = (
        "Excluded directories, any directory named `node_modules`, "
        "`.next` or `.git`, are never searched, even when named as "
        "the watch path: `watch.sh` refuses a watch path that is one "
        "of them or is inside one, printing a message and exiting 2."
    )

    CHECK = (
        'The watch path is checked in two forms, and refused if e'
        'ither has an excluded component: as written, with `.` an'
        'd `..` components folded away, and where it physically i'
        "s, which is a directory's physical absolute path, or for"
        " anything else its parent directory's physical absolute "
        'path and its own name. So `node_modules/../src` is searc'
        'hed; `.` inside `node_modules`, a symlink into one, and '
        'a path through a symlink named `node_modules` are refuse'
        'd. A symlink that does not point to a directory is refus'
        'ed with exit 2, with or without a trailing slash, becaus'
        'e where it leads is not checked. When a symlink makes th'
        'e physical path differ from the folded one, the physical'
        ' path is searched and its matches print that path. A pat'
        'h whose parent does not exist is checked as written. The'
        ' names are compared case-sensitively; case-insensitive f'
        'ile systems were not tested.'
    )
    TIMING = (
        'A window above 0 that ends with `REVIEW_WATCH_WINDOW_END'
        'ED` lasts at least `window_seconds` and can run up to on'
        'e second longer, because the deadline is counted in whol'
        'e seconds, plus the poll interval and the scan in progre'
        'ss when the deadline passes. A marker already present en'
        'ds the watch at the first scan.'
    )

    def test_the_rule_reads_the_same_in_all_three_documents(self) -> None:
        for path in (README, ROOT / "SECURITY.md", SKILL):
            text = " ".join(read(path).split())
            self.assertIn(self.RULE, text, path.name)
            self.assertIn(self.CHECK, text, path.name)
            self.assertIn(self.TIMING, text, path.name)

    def test_the_program_names_the_same_three_directories(self) -> None:
        program = read(PROGRAM)
        for name in ("node_modules", ".next", ".git"):
            self.assertIn("--exclude-dir=%s" % name, program)
            self.assertIn("'!**/%s/**'" % name, program)
            self.assertIn("*/%s/*" % name, program)


class EvidenceTest(unittest.TestCase):
    def test_manifest_hashes_match_the_files(self) -> None:
        record = json.loads(read(MANIFEST))
        self.assertEqual(record["skill"]["sha256"], sha256(SKILL))
        programs = {item["path"]: item["sha256"] for item in record["programs"]}
        self.assertEqual(
            programs,
            {PROGRAM.relative_to(ROOT).as_posix(): sha256(PROGRAM)},
        )
        self.assertEqual(record["output"]["sha256"], sha256(TRANSCRIPT))
        self.assertIs(record["output"]["edited"], False)
        self.assertEqual(record["output"]["transforms"], [])
        self.assertIs(record["agent"]["invoked_the_skill"], False)

    def test_manifest_commands_are_the_ones_in_the_transcript(self) -> None:
        record = json.loads(read(MANIFEST))
        commands = [
            line[2:]
            for line in read(TRANSCRIPT).splitlines()
            if line.startswith("$ ") and not line.startswith("$ echo")
        ]
        self.assertEqual(record["invocation"]["commands"], commands)

    def test_transcript_carries_no_capture_path(self) -> None:
        text = read(TRANSCRIPT)
        for fragment in ("/var/folders", "/private/", "/Users/", "/home/", "/tmp/"):
            self.assertNotIn(fragment, text)

    def test_transcript_exit_statuses_match_the_readme_table(self) -> None:
        lines = read(TRANSCRIPT).splitlines()
        bad_window = lines.index("$ watch worktree 10m")
        self.assertEqual(lines[bad_window + 4], "exit status: 2")
        missing = lines.index("$ watch missing-dir 30 1")
        self.assertEqual(lines[missing + 3], "exit status: 3")
        readme = read(README)
        for status in ("| 1 ", "| 2 ", "| 3 "):
            self.assertIn(status, readme)


class DemoTest(unittest.TestCase):
    def test_images_agree_with_the_transcript(self) -> None:
        verifier = load(ROOT / "scripts" / "verify_demo.py", "verify_demo")
        generator = verifier.load_generator()
        self.assertEqual(verifier.problems_in(generator, read(TRANSCRIPT)), [])


class SocialPreviewTest(unittest.TestCase):
    def test_preview_is_the_size_github_expects(self) -> None:
        header = (ROOT / "assets" / "social-preview.png").read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", header[16:24]), (1280, 640))

    def test_stamp_binds_the_source_and_the_render(self) -> None:
        recorded = {}
        for line in read(ROOT / "assets" / "social-preview.sha256").splitlines():
            value, name = line.split()
            recorded[name] = value
        for name in ("social-preview.html", "social-preview.png"):
            self.assertEqual(recorded[name], sha256(ROOT / "assets" / name), name)

    def test_preview_source_carries_the_claim(self) -> None:
        text = " ".join(read(ROOT / "assets" / "social-preview.html").split())
        self.assertIn(CLAIM, text)


class SupportFilesTest(unittest.TestCase):
    def test_license_is_mit(self) -> None:
        self.assertTrue(read(ROOT / "LICENSE").startswith("MIT License\n"))

    def test_security_names_this_repository_for_reports(self) -> None:
        self.assertIn(
            REPOSITORY + "/security/advisories/new",
            read(ROOT / "SECURITY.md"),
        )

    def test_contributing_names_the_check_command(self) -> None:
        self.assertIn("make check", read(ROOT / "CONTRIBUTING.md"))


if __name__ == "__main__":
    unittest.main()
