# Contributing

This repository is one skill, one shell program with its
tests, and the scripts that build and check the demo images.

## Run the checks first

```sh
make check
```

That runs `tests/test_watch.py` and
`tests/test_integrations.py`. They need `make`, Python 3.9
or later, `bash`, `git`, `grep`, `date`, `sleep` and ripgrep
(`rg`); no Python package is installed. The ripgrep tests
fail, not skip, when `rg` is missing. The grep tests prefer
`/usr/bin/grep`. Four tests, two per backend, remove a
fixture's permissions and skip when run as root. The
packaging contract needs a git clone, because it reads `git
log`; its release-tag test skips when `HEAD` carries no tag.

**The packaging contract asserts on the README.** These will
fail on an innocent-looking prose edit:

- the claim line at the top of the README must appear
  verbatim, and the transcript must show it;
- each install block must carry its own `release=` pin at
  the version both plugin manifests ship;
- `SKILL.md` must stay under 500 lines;
- the excluded-directory rule, the paragraph on how the
  watch path is checked, and the timing sentence must read
  the same, word for word, in the README, `SECURITY.md` and
  `SKILL.md`;
- `evidence/demo-manifest.json` records the SHA-256 of
  `SKILL.md`, of `watch.sh` and of the transcript, so any
  edit to one of those three files, prose included, fails
  until the manifest is refreshed as described next.

If you change one of those, change the thing it describes
too.

## Changing the program or the transcript

After any edit to `SKILL.md` or to `watch.sh`, run:

```sh
make record
make demo
```

`make record` runs `scripts/record_session.py`. It replays
the commands listed in the manifest in a throwaway directory
with ripgrep on `PATH`, writes the transcript, and rewrites
the manifest's hashes, date, ripgrep version and bash
version. It needs `bash`, `git`, `rg` and `python3`.
`make demo` rebuilds the two images from the transcript.
`make assets` rebuilds the social preview and needs Chrome or
Chromium; `make asset-check` does not.

## What is most useful

Open an issue for any of these. The labels
`good first issue` and `help wanted` mark the ones that are
ready to pick up.

- **A marker the watcher missed, or a line it reported that
  was not a marker.** Attach the line, the file type, and
  which backend ran (`rg` or `grep`, with its version).
- **A difference between the two backends** that the README
  does not list.
- **A run where an agent edited without address-comments**,
  or did not stop when it was missing. Say which host ran it.

## Pull requests

Prose changes to `SKILL.md` are welcome. Say what an agent
did before the change and what it does after, on the same
worktree.

A change to the marker grammar in `watch.sh` changes both
patterns, the ripgrep one and the POSIX ERE one, and adds a
case to `tests/test_watch.py` that runs on both backends.

Keep `SKILL.md` under 500 lines; the suite enforces it.
Frontmatter carries `name` and `description` and nothing
else.

The top-level `skill` is a symlink to `skills/review-watch/`.
Do not reverse that orientation.

Commit with your own identity and no `Co-authored-by`
trailer of any kind. The suite fails on one anywhere in
history, so do not apply review suggestions through the
GitHub UI.
