# Security

## Reporting a vulnerability

Report privately through GitHub:
<https://github.com/trycopilotai/review-watch/security/advisories/new>

That opens a private security advisory visible only to the
maintainers. Do not put the details of a vulnerability in a
public issue.

If that link shows "Not Found", private reporting is not
turned on for this repository. Open a public issue titled
"Security report waiting" that says only that you have a
report, with no details, and a maintainer will arrange a
private channel.

## What is in scope

- **Prompt content that redirects an agent.** `SKILL.md` is
  an instruction set an agent follows while a person reviews
  a worktree. Text in it that makes an agent commit or push
  from the watch loop without a wrapper's authorization,
  edit files other than through address-comments, or keep
  editing when address-comments is missing is a valid
  report.
- **`watch.sh`.** It reads `REVIEW_WATCH_LABELS` and its
  three arguments, runs `rg` or `grep` over the watch path,
  and runs `date` and `sleep`. It writes only to standard
  output and standard error. A tree, argument or label value
  that makes it write a file, delete one, or run another
  command is a valid report.
- **The install blocks.** The two README blocks run `mkdir
  -p`, `mktemp -d`, `git clone`, `cp`, `mv` and `rm -rf`,
  all inside one skills directory under `$HOME`. A
  repository state that makes either block write or delete
  outside its install target is in scope.
- **The build scripts.** `assets/build.py` finds a Chrome or
  Chromium binary from a fixed candidate list, runs it
  headless with a temporary profile directory, and writes
  the preview PNG and its stamp. `scripts/generate_demo.py`
  writes two SVG files; `scripts/verify_demo.py` only reads.
  `scripts/record_session.py` copies `skills/` into a
  temporary directory, creates a git repository with one
  commit there, runs the manifest's commands through `bash`,
  and rewrites the transcript and the manifest.
  `tests/test_watch.py` writes fixture trees in temporary
  directories and runs `watch.sh` on them; one test runs
  `git init` in one of them, and four (two per backend)
  remove and then restore the permissions of a fixture file
  or directory. `tests/test_integrations.py` runs `git`
  against the repository root.

## Markers are instructions

This is how the skill works, and a known limit, not a
finding: anyone who can write to the watched path can write a
marker, and the skill hands the markers a scan finds to
address-comments as work for the agent. That includes files a reviewer did not
write, such as a dependency's sources or a generated file,
when they are under the watch path and not excluded. Watch
only a tree whose writers you would let direct the agent.

## Known limits of `watch.sh`

These are known limits, not findings:

- `poll_seconds` is not checked. It is passed to `sleep` as
  given. A value `sleep` rejects makes every poll print
  `sleep`'s error and rescan at once, until the window ends;
  `0` rescans without a pause. A value `sleep` accepts, such
  as `0.5` or, with some `sleep` programs, `1m`, is used.
- A window above 0 that ends with
  `REVIEW_WATCH_WINDOW_ENDED` lasts at least
  `window_seconds` and can run up to one second longer,
  because the deadline is counted in whole seconds, plus the
  poll interval and the scan in progress when the deadline
  passes. A marker already present ends the watch at the
  first scan.
- `REVIEW_WATCH_LABELS` is inserted into the pattern as it
  is, without escaping. A value that is not a valid pattern
  makes the search fail, and `watch.sh` exits 3. A value
  such as `.*` makes every comment leader a match.
- The marker grammar is matched without regard to case, and
  a label such as `agent:` after a comment leader matches in
  any comment, so ordinary comments can be reported.
- ripgrep runs with `--no-config`, so a ripgrep
  configuration file, which could otherwise add options such
  as `--pre`, is not read. Other environment variables and
  the `rg`, `grep`, `date` and `sleep` found on `PATH` are
  trusted as they are.
- Excluded directories, any directory named `node_modules`,
  `.next` or `.git`, are never searched, even when named as
  the watch path: `watch.sh` refuses a watch path that is
  one of them or is inside one, printing a message and
  exiting 2. The watch path is checked in two forms, and
  refused if either has an excluded component: as written,
  with `.` and `..` components folded away, and where it
  physically is, which is a directory's physical absolute
  path, or for anything else its parent directory's physical
  absolute path and its own name. So `node_modules/../src`
  is searched; `.` inside `node_modules`, a symlink into
  one, and a path through a symlink named `node_modules` are
  refused. A symlink that does not point to a directory is
  refused with exit 2, with or without a trailing slash,
  because where it leads is not checked. When a symlink
  makes the physical path differ from the folded one, the
  physical path is searched and its matches print that path.
  A path whose parent does not exist is checked as written.
  The names are compared case-sensitively; case-insensitive
  file systems were not tested. The three names are fixed in
  the script.
- ripgrep's hidden-file and ignore rules do not apply to the
  watch path itself, only to what is found below it. The
  README's "Search backends" section lists which files each
  backend skips.
- Inside the watch path, neither backend followed a
  symlinked directory in the checks run for this release
  (ripgrep and the BSD grep that ships with macOS). A watch
  path that is itself a symlink to a directory is searched
  by both, through its physical path.
- A scan that hits an error exits 3 and drops any markers
  the same scan found.
- Each poll rescans the watch path; the script keeps no
  state between scans.

## What is out of scope

`SKILL.md` tells the agent to make its changes through
address-comments. That skill's behaviour, ripgrep's, grep's, and that of Claude Code, Codex,
or any other host, are out of scope here. Report those to
their own maintainers.
