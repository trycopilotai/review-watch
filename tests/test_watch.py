#!/usr/bin/env python3
"""Tests for skills/review-watch/scripts/watch.sh.

Each test runs the script with bash against a fixture tree in a
temporary directory. PATH is replaced by a directory of
symlinks, so the test decides which search tool the script can
find:

- the rg backend sees rg, date and sleep;
- the grep backend sees grep, date and sleep, and no rg;
- the no-tool case sees date and sleep only, and the
  missing-clock cases see grep and one of date or sleep.

The rg tests need ripgrep installed; they fail, not skip, when
it is missing. Standard library only:

    python3 tests/test_watch.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "skills" / "review-watch" / "scripts" / "watch.sh"
BASH = shutil.which("bash") or "/bin/bash"

# Lines the marker grammar matches, in every comment leader and
# TODO form the script lists, in mixed case.
MARKERS = (
    "// AGENT: slash leader",
    "# agent: hash leader",
    "-- agents: double dash leader",
    "/* to agent please */",
    " * TODO(agent) star leader",
    "<!-- Agent: html leader -->",
    "x = 1  # agent: trailing comment",
    "#agent: no space after the leader",
    "TODO(agents) bare",
    "TODO( agent ) inner spaces",
    "TODO(code-review:abc12) code review id",
    "# Agents: an ordinary comment that also matches",
    "* Agent: a Markdown bullet also matches through the * leader",
)
# Lines it does not match.
NON_MARKERS = (
    "TODO(alice) someone else",
    "user_agent: a yaml key",
    "# reagent: not the word agent",
    "see http://agent: no leader",
    "- agent: a single dash is not a leader",
    "agent: no comment leader",
    "/// agent: triple slash",
    "//! agent: doc comment",
    "/** agent: javadoc",
    "## agent: double hash",
    "; agent: semicolon",
)


def tool(name: str) -> str:
    """The absolute path of a tool, preferring the system grep."""
    if name == "grep":
        for candidate in ("/usr/bin/grep", "/bin/grep"):
            if os.path.exists(candidate):
                return candidate
    found = shutil.which(name)
    if found is None:
        raise AssertionError(
            "%s is not on PATH; make check needs it (see CONTRIBUTING.md)" % name
        )
    return found


def bin_dir(parent: Path, names: tuple) -> Path:
    directory = parent / ("bin-" + "-".join(names))
    directory.mkdir()
    for name in names:
        (directory / name).symlink_to(tool(name))
    return directory


def matched_lines(stdout: str) -> list:
    """The text of each reported match, without path and line number."""
    lines = stdout.splitlines()
    texts = []
    for line in lines[1:]:
        match = re.match(r"^(?:[^:]*:)?\d+:(.*)$", line)
        if match is None:
            raise AssertionError("not a match line: %r" % line)
        texts.append(match.group(1))
    return texts


def snapshot(tree: Path) -> dict:
    return {
        str(path.relative_to(tree)): path.read_bytes()
        for path in sorted(tree.rglob("*"))
        if path.is_file()
    }


class Backend:
    """Tests that hold for both backends. Subclasses set TOOLS."""

    TOOLS: tuple = ()

    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        base = Path(self.scratch.name).resolve()
        self.path = str(bin_dir(base, self.TOOLS + ("date", "sleep")))
        self.tree = base / "tree"
        self.tree.mkdir()

    def tearDown(self) -> None:
        self.scratch.cleanup()

    def run_watch(self, *arguments: str, labels: str = "", cwd=None):
        environment = {"PATH": self.path}
        if labels:
            environment["REVIEW_WATCH_LABELS"] = labels
        return subprocess.run(
            [BASH, str(WATCH), *arguments],
            cwd=str(cwd or self.tree),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def write(self, relative: str, text: str) -> Path:
        path = self.tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_reports_every_marker_form_and_no_other_line(self) -> None:
        self.write("cases.txt", "\n".join(MARKERS + NON_MARKERS) + "\n")
        result = self.run_watch(".", "5", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], "REVIEW_WATCH_MARKERS")
        self.assertEqual(sorted(matched_lines(result.stdout)), sorted(MARKERS))

    def test_window_ends_when_no_marker_appears(self) -> None:
        self.write("clean.py", "# an ordinary comment\nprint('hi')\n")
        result = self.run_watch(".", "1", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")
        self.assertEqual(result.stderr, "")

    def test_detects_a_marker_written_after_the_watch_starts(self) -> None:
        self.write("app.js", "const a = 1;\n")
        started = time.monotonic()
        process = subprocess.Popen(
            [BASH, str(WATCH), ".", "30", "1"],
            cwd=str(self.tree),
            env={"PATH": self.path},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1.5)
        self.write("app.js", "const a = 1;\n// AGENT: rename a\n")
        stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(stdout.splitlines()[0], "REVIEW_WATCH_MARKERS")
        self.assertEqual(matched_lines(stdout), ["// AGENT: rename a"])

    def test_labels_variable_extends_the_grammar(self) -> None:
        self.write("notes.py", "# reviewer says: split this\n")
        without = self.run_watch(".", "1", "1")
        self.assertEqual(without.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")
        with_label = self.run_watch(
            ".", "5", "1", labels="reviewer[[:space:]]+says:"
        )
        self.assertEqual(
            matched_lines(with_label.stdout), ["# reviewer says: split this"]
        )

    def test_top_level_excluded_directories_are_skipped(self) -> None:
        for directory in ("node_modules", ".next", ".git"):
            self.write(directory + "/x.js", "// AGENT: excluded\n")
        result = self.run_watch(".", "1", "1")
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_excluded_directories_are_skipped_at_any_depth(self) -> None:
        self.write("ok.js", "// AGENT: kept\n")
        for directory in ("node_modules", "pkg/node_modules", "a/.next", "b/.git"):
            self.write(directory + "/x.js", "// AGENT: excluded\n")
        result = self.run_watch(".", "5", "1")
        self.assertEqual(matched_lines(result.stdout), ["// AGENT: kept"])

    def test_an_absolute_path_from_another_directory_keeps_the_excludes(
        self,
    ) -> None:
        self.write("ok.js", "// AGENT: kept\n")
        self.write("node_modules/x.js", "// AGENT: excluded\n")
        self.write(".next/x.js", "// AGENT: excluded\n")
        elsewhere = self.tree.parent / "elsewhere"
        elsewhere.mkdir()
        for path in (str(self.tree), "../tree"):
            result = self.run_watch(path, "5", "1", cwd=elsewhere)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(matched_lines(result.stdout), ["// AGENT: kept"], path)

    def test_an_excluded_watch_path_is_refused(self) -> None:
        self.write(".git/hooks/pre-commit", "# AGENT: in a hook\n")
        self.write(".git/HEAD", "ref: refs/heads/main\n")
        self.write("node_modules/pkg/x.js", "// AGENT: in a dependency\n")
        self.write(".next/x.js", "// AGENT: generated\n")
        before = snapshot(self.tree)
        for path in (
            ".git",
            ".git/hooks",
            ".git/hooks/pre-commit",
            "node_modules",
            "node_modules/pkg/x.js",
            "./node_modules/",
            ".next",
            str(self.tree / "node_modules"),
            "node_modules/does-not-exist",
        ):
            result = self.run_watch(path, "5", "1")
            self.assertEqual(result.returncode, 2, path)
            self.assertEqual(result.stdout, "", path)
            self.assertIn("excluded directories are never searched", result.stderr)
        inside = self.run_watch(".", "5", "1", cwd=self.tree / "node_modules" / "pkg")
        self.assertEqual(inside.returncode, 2)
        self.assertIn("excluded directories are never searched", inside.stderr)
        self.assertEqual(snapshot(self.tree), before)

    def test_a_symlink_into_an_excluded_directory_is_refused(self) -> None:
        self.write("node_modules/pkg/x.js", "// AGENT: in a dependency\n")
        (self.tree / "link").symlink_to(self.tree / "node_modules" / "pkg")
        result = self.run_watch("link", "5", "1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("excluded directories are never searched", result.stderr)

    def test_a_symlink_that_is_not_to_a_directory_is_refused(self) -> None:
        self.write("node_modules/pkg/x.js", "// AGENT: in a dependency\n")
        self.write("src/y.js", "// AGENT: ordinary\n")
        (self.tree / "into").symlink_to(self.tree / "node_modules" / "pkg" / "x.js")
        (self.tree / "plain").symlink_to(self.tree / "src" / "y.js")
        (self.tree / "dangling").symlink_to(self.tree / "nowhere")
        for path in ("into", "plain", "dangling", "plain/", "into//"):
            result = self.run_watch(path, "5", "1")
            self.assertEqual(result.returncode, 2, path)
            self.assertEqual(result.stdout, "", path)
            self.assertIn("is a symlink that does not point to a directory", result.stderr)

    def test_a_symlinked_node_modules_cannot_be_used_to_reach_its_target(
        self,
    ) -> None:
        self.write("vendor/x/a.js", "// AGENT: vendored\n")
        (self.tree / "node_modules").symlink_to(self.tree / "vendor")
        for path in ("node_modules", "node_modules/x", "node_modules/x/a.js"):
            result = self.run_watch(path, "5", "1")
            self.assertEqual(result.returncode, 2, path)
            self.assertEqual(result.stdout, "", path)
            self.assertIn("excluded directories are never searched", result.stderr)
        # Through its real name the directory is an ordinary one.
        direct = self.run_watch("vendor", "5", "1")
        self.assertEqual(matched_lines(direct.stdout), ["// AGENT: vendored"])

    def test_a_path_through_a_symlink_into_node_modules_is_refused(self) -> None:
        self.write("node_modules/pkg/sub/x.js", "// AGENT: in a dependency\n")
        (self.tree / "deps").symlink_to(self.tree / "node_modules")
        for path in ("deps", "deps/pkg", "deps/pkg/sub", "deps/pkg/sub/x.js"):
            result = self.run_watch(path, "5", "1")
            self.assertEqual(result.returncode, 2, path)
            self.assertEqual(result.stdout, "", path)

    def test_a_symlink_to_an_ordinary_directory_is_searched(self) -> None:
        self.write("src/y.js", "// AGENT: ordinary\n")
        (self.tree / "alias").symlink_to(self.tree / "src")
        result = self.run_watch("alias", "5", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(matched_lines(result.stdout), ["// AGENT: ordinary"])
        # The physical path is searched, so the match names it.
        self.assertIn(str(self.tree / "src" / "y.js"), result.stdout)

    def test_an_unreadable_file_fails_the_scan_and_drops_its_markers(
        self,
    ) -> None:
        if os.geteuid() == 0:
            self.skipTest("root can read any file")
        self.write("a.py", "# AGENT: readable\n")
        secret = self.write("b.py", "# AGENT: unreadable\n")
        secret.chmod(0)
        try:
            result = self.run_watch(".", "5", "1")
        finally:
            secret.chmod(0o644)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        self.assertIn("exited with status 2", result.stderr)

    def test_a_present_marker_ends_the_watch_at_the_first_scan(self) -> None:
        self.write("a.py", "# AGENT: already here\n")
        started = time.monotonic()
        result = self.run_watch(".", "30", "10")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(matched_lines(result.stdout), ["# AGENT: already here"])

    def test_a_directory_that_cannot_be_entered_is_refused(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("root can enter any directory")
        self.write("locked/f.js", "// AGENT: behind a lock\n")
        locked = self.tree / "locked"
        locked.chmod(0)
        try:
            for path in ("locked", "locked/f.js"):
                result = self.run_watch(path, "5", "1")
                self.assertEqual(result.returncode, 2, path)
                self.assertEqual(result.stdout, "", path)
                self.assertIn("cannot enter locked", result.stderr)
        finally:
            locked.chmod(0o755)

    def test_the_window_lasts_at_least_its_length(self) -> None:
        self.write("clean.py", "# an ordinary comment\n")
        for _ in range(3):
            started = time.monotonic()
            result = self.run_watch(".", "2", "1")
            elapsed = time.monotonic() - started
            self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")
            self.assertGreaterEqual(elapsed, 2.0)
            self.assertLess(elapsed, 6.0)

    def test_a_path_through_an_excluded_name_that_leaves_it_is_searched(
        self,
    ) -> None:
        self.write("src/y.js", "// AGENT: ordinary\n")
        for directory in ("node_modules", ".git", ".next"):
            (self.tree / directory).mkdir(exist_ok=True)
        for path in ("node_modules/../src", ".git/../src", ".next/../src/y.js"):
            result = self.run_watch(path, "5", "1")
            self.assertEqual(result.returncode, 0, (path, result.stderr))
            self.assertEqual(matched_lines(result.stdout), ["// AGENT: ordinary"], path)

    def test_a_name_that_only_contains_an_excluded_name_is_searched(self) -> None:
        self.write("node_modules.bak/x.js", "// AGENT: kept\n")
        result = self.run_watch("node_modules.bak", "5", "1")
        self.assertEqual(matched_lines(result.stdout), ["// AGENT: kept"])

    def test_window_zero_ends_without_scanning(self) -> None:
        self.write("a.py", "# AGENT: present\n")
        result = self.run_watch(".", "0", "1")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_a_failing_search_is_loud(self) -> None:
        result = self.run_watch("does-not-exist", "5", "1")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        self.assertIn("exited with status 2", result.stderr)
        self.assertIn(self.TOOLS[0], result.stderr)

    def test_an_option_like_path_is_a_path(self) -> None:
        self.write("a.py", "# AGENT: present\n")
        before = snapshot(self.tree)
        for path in ("--version", "--pre=touch", "-x", "-"):
            result = subprocess.run(
                [BASH, str(WATCH), path, "5", "1"],
                cwd=str(self.tree),
                env={"PATH": self.path},
                input="// AGENT: from standard input\n",
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 3, path)
            self.assertEqual(result.stdout, "", path)
            self.assertIn("exited with status 2", result.stderr)
        self.assertEqual(snapshot(self.tree), before)

    def test_the_watch_does_not_change_the_tree(self) -> None:
        self.write("a.py", "# AGENT: present\n")
        self.write("b/c.md", "<!-- TODO(agent) -->\n")
        before = snapshot(self.tree)
        self.run_watch(".", "5", "1")
        self.assertEqual(snapshot(self.tree), before)


class RipgrepBackendTest(Backend, unittest.TestCase):
    TOOLS = ("rg",)

    def test_hidden_files_are_skipped(self) -> None:
        self.write(".env.sh", "# AGENT: hidden\n")
        result = self.run_watch(".", "1", "1")
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_a_review_log_in_a_hidden_directory_is_skipped(self) -> None:
        # README Known limits: the published runs' clean windows
        # rest on this.
        self.write(".address-comments/review-log.md", "- Marker: `TODO(agent)` add apply_discount\n")
        result = self.run_watch(".", "1", "1")
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_gitignored_files_are_skipped_inside_a_git_repository(self) -> None:
        subprocess.run(
            ["git", "init", "-q", str(self.tree)],
            check=True,
            env={"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": os.devnull, "HOME": str(self.tree)},
        )
        self.write(".gitignore", "build/\n")
        self.write("build/out.js", "// AGENT: generated\n")
        result = self.run_watch(".", "1", "1")
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_a_ripgrep_config_file_is_not_read(self) -> None:
        config = self.tree.parent / "rgconfig"
        config.write_text("--hidden\n", encoding="utf-8")
        self.write(".env.sh", "# AGENT: hidden\n")
        result = subprocess.run(
            [BASH, str(WATCH), ".", "1", "1"],
            cwd=str(self.tree),
            env={"PATH": self.path, "RIPGREP_CONFIG_PATH": str(config)},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_an_explicit_hidden_watch_path_is_searched(self) -> None:
        # Known limit: the hidden and ignore rules apply to what
        # ripgrep finds while descending, not to the path given.
        self.write(".github/x.yml", "# AGENT: explicit\n")
        result = self.run_watch(".github", "5", "1")
        self.assertEqual(matched_lines(result.stdout), ["# AGENT: explicit"])

    def test_a_single_binary_file_is_reported_as_a_hit(self) -> None:
        # Known limit: given one binary file as the watch path,
        # ripgrep prints a notice instead of a line, and watch.sh
        # reports it as a marker.
        self.write("b.dat", "abc\0def\n// AGENT: in binary\n")
        result = self.run_watch("b.dat", "5", "1")
        self.assertEqual(result.stdout.splitlines()[0], "REVIEW_WATCH_MARKERS")
        self.assertTrue(result.stdout.splitlines()[1].startswith("binary file matches"))

    def test_binary_files_inside_a_directory_are_skipped(self) -> None:
        self.write("b.dat", "abc\0def\n// AGENT: in binary\n")
        self.write("c.dat", "// AGENT: before the nul\nabc\0def\n")
        result = self.run_watch(".", "1", "1")
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")

    def test_a_symlinked_watch_root_is_followed(self) -> None:
        real = self.tree.parent / "real"
        real.mkdir()
        (real / "f.js").write_text("// AGENT: behind a link\n", encoding="utf-8")
        (self.tree / "root").symlink_to(real)
        result = self.run_watch("root", "5", "1")
        self.assertEqual(matched_lines(result.stdout), ["// AGENT: behind a link"])


class GrepBackendTest(Backend, unittest.TestCase):
    TOOLS = ("grep",)

    def test_hidden_files_are_searched(self) -> None:
        self.write(".env.sh", "# AGENT: hidden\n")
        result = self.run_watch(".", "5", "1")
        self.assertEqual(matched_lines(result.stdout), ["# AGENT: hidden"])

    def test_a_review_log_in_a_hidden_directory_is_reported(self) -> None:
        # README Known limits: with grep, the log repeats the
        # marker at every scan.
        self.write(".address-comments/review-log.md", "- Marker: `TODO(agent)` add apply_discount\n")
        result = self.run_watch(".", "5", "1")
        self.assertEqual(
            matched_lines(result.stdout), ["- Marker: `TODO(agent)` add apply_discount"]
        )

    def test_gitignore_is_not_read(self) -> None:
        self.write(".gitignore", "build/\n")
        self.write("build/out.js", "// AGENT: generated\n")
        result = self.run_watch(".", "5", "1")
        self.assertEqual(matched_lines(result.stdout), ["// AGENT: generated"])

    def test_binary_files_are_skipped(self) -> None:
        self.write("b.dat", "abc\0def\n// AGENT: in binary\n")
        for path in (".", "b.dat"):
            result = self.run_watch(path, "1", "1")
            self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n", path)

class ArgumentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.base = Path(self.scratch.name).resolve()

    def tearDown(self) -> None:
        self.scratch.cleanup()

    def run_watch(self, path: str, *arguments: str):
        return subprocess.run(
            [BASH, str(WATCH), *arguments],
            cwd=str(self.base),
            env={"PATH": path},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_missing_path_argument_is_a_usage_error(self) -> None:
        path = str(bin_dir(self.base, ("grep", "date", "sleep")))
        result = self.run_watch(path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage: watch.sh <watch_path>", result.stderr)
        self.assertIn("a watch_path is required", result.stderr)
        empty = self.run_watch(path, "")
        self.assertEqual(empty.returncode, 1)
        self.assertEqual(empty.stdout, "")

    def test_window_must_be_whole_seconds_up_to_nine_digits(self) -> None:
        path = str(bin_dir(self.base, ("grep", "date", "sleep")))
        for window in ("abc", "-1", "1.5", "08", "10m", "1000000000", ""):
            result = self.run_watch(path, ".", window, "1")
            self.assertEqual(result.returncode, 2, window)
            self.assertEqual(result.stdout, "", window)
            self.assertIn(
                "window_seconds must be a whole number of seconds from 0 to 999999999",
                result.stderr,
            )
            self.assertIn("usage: watch.sh", result.stderr)

    def test_largest_window_is_accepted(self) -> None:
        path = str(bin_dir(self.base, ("grep", "date", "sleep")))
        (self.base / "a.py").write_text("# AGENT: present\n", encoding="utf-8")
        result = self.run_watch(path, "a.py", "999999999", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], "REVIEW_WATCH_MARKERS")

    def test_no_search_tool_is_loud(self) -> None:
        path = str(bin_dir(self.base, ("date", "sleep")))
        result = self.run_watch(path, ".", "5", "1")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        self.assertIn("neither rg nor grep is on PATH", result.stderr)

    def test_a_missing_clock_or_sleep_is_loud(self) -> None:
        (self.base / "a.py").write_text("# AGENT: present\n", encoding="utf-8")
        for tools, missing in ((("grep", "sleep"), "date"), (("grep", "date"), "sleep")):
            path = str(bin_dir(self.base, tools))
            result = self.run_watch(path, ".", "5", "1")
            self.assertEqual(result.returncode, 3, missing)
            self.assertEqual(result.stdout, "", missing)
            self.assertIn("%s is not on PATH" % missing, result.stderr)

    def test_rg_is_preferred_when_both_are_on_path(self) -> None:
        path = str(bin_dir(self.base, ("rg", "grep", "date", "sleep")))
        (self.base / ".hidden.py").write_text("# AGENT: hidden\n", encoding="utf-8")
        result = self.run_watch(path, ".", "1", "1")
        # grep would report the hidden file; rg skips it.
        self.assertEqual(result.stdout, "REVIEW_WATCH_WINDOW_ENDED\n")


if __name__ == "__main__":
    unittest.main()
