---
name: review-watch
description: >-
  Watch a worktree or path for agent-directed review markers
  (AGENT:, TODO(agent) / TODO(agents),
  TODO(code-review:<id>), and host-registered operator
  labels) as a reviewer writes them, and run the
  address-comments skill on the markers each scan finds, for
  a bounded window or until the reviewer stops. Use it while a person reviews a worktree in an
  editor and wants each marker handled as it is written.
---

# Review Watch

Use this skill to watch a path - typically a worktree a
human is actively reviewing in an editor - and address
agent-directed review markers at the first scan after they
are written, without a separate manual invocation for each
one.

`review-watch` is the watch loop around `address-comments`.
It detects the markers present at each scan and delegates
every fix to `address-comments`. It does not re-implement marker
handling: `address-comments` owns the marker grammar, the
change, the comment removal, and the review-log entry.

## When to use

- A reviewer has opened a worktree and will leave
  `TODO(agent)` / `AGENT:` directives or
  `TODO(code-review:<id>)` markers as they read.
- An orchestrator - for example a swe-day run
  (`trycopilotai/swe-day`, step 12) - has just
  turned a worktree over to a human for code review and
  wants markers addressed live during that review rather
  than in one later batch.

Stop watching at a bound: a fixed time window, an explicit
stop signal, or when the reviewing step completes.

## Inputs

- `watch_path` - the worktree or directory to watch
  (required).
- `address_comments` - the address-comments skill or wrapper
  to delegate to (required; a wrapper can name it, else use
  the skill named `address-comments`). It is a
  separate skill, published as `trycopilotai/address-comments`,
  and is not bundled here. If it is not installed, do not
  address markers yourself: report the markers the scan found,
  say that address-comments is missing, and stop without
  editing.
- `window` - how long to watch, for example `10m`, or
  `until-stopped`. Default: the wrapper's value, else
  `watch.sh`'s 600 seconds. `watch.sh` has no
  `until-stopped` mode; to watch until stopped, call it again
  each time its window ends.
- `poll_interval` - how often to rescan. Default: the
  wrapper's value, else `watch.sh`'s 12 seconds.
- `excludes` - generated, vendored, and transcript globs to
  skip, inherited from the address-comments wrapper.

## Workflow

1. Baseline. Run the address-comments marker scan over
   `watch_path`. Address any markers already present at the
   start of the watch - a reviewer often writes the first
   one before the watch begins - then record a clean
   baseline.
2. Poll. On each interval, rescan `watch_path` for supported
   markers. Because addressed markers are removed from
   source, any marker found is new work. A marker that stays
   in the tree, because it was deferred or was not meant for
   an agent, is found again on every scan, and `watch.sh`
   exits at once on it; do not restart `watch.sh` in a loop
   while such a marker remains. Report it and stop instead.
3. On detection, run the `address-comments` workflow on the
   matched files: classify, make or plan the change, produce
   post-lint artifacts, remove the addressed marker, and
   append the review-log entry. Follow the
   address-comments spec exactly; do not shortcut it.
4. Continue until the bound is reached: the `window`
   elapses, a stop signal arrives, or the reviewing step
   completes.
5. Summarize. Report how many markers were addressed, the
   files touched, the validation run, and anything left
   unresolved or deferred for the reviewer.

A marker classified by `address-comments` as a question to
answer in chat is still a hit: answer it, remove the marker,
and log it, the same as any other addressed marker.

## Detection

Use the address-comments marker grammar as the detector;
never invent a separate one. The default scan is the
address-comments base scan extended with any host-registered
operator labels and the host's exclude globs. `watch.sh`
takes extra labels through `REVIEW_WATCH_LABELS`, but its
excludes are fixed; drop matches under any other excluded
path yourself. Excluded directories, any directory named
`node_modules`, `.next` or `.git`, are never searched, even
when named as the watch path: `watch.sh` refuses a watch
path that is one of them or is inside one, printing a
message and exiting 2. The watch path is checked in two
forms, and refused if either has an excluded component: as
written, with `.` and `..` components folded away, and where
it physically is, which is a directory's physical absolute
path, or for anything else its parent directory's physical
absolute path and its own name. So `node_modules/../src` is
searched; `.` inside `node_modules`, a symlink into one, and
a path through a symlink named `node_modules` are refused. A
symlink that does not point to a directory is refused with
exit 2, with or without a trailing slash, because where it
leads is not checked. When a symlink makes the physical path
differ from the folded one, the physical path is searched
and its matches print that path. A path whose parent does
not exist is checked as written. The names are compared
case-sensitively; case-insensitive file systems were not
tested. [`scripts/watch.sh`](scripts/watch.sh) is a
reference poller that scans and exits on the first match; it
is a convenience for driving the loop, not a replacement for
the address-comments workflow on each hit. It uses ripgrep
when `rg` is on `PATH` and falls back to `grep -rEn -i -I`
otherwise. It exits 0 after printing `REVIEW_WATCH_MARKERS`
and the matches, or `REVIEW_WATCH_WINDOW_ENDED`; it exits 1
without a path, 2 on a bad window argument, an excluded
watch path, a symlink that does not point to a directory, or
a path or parent directory it cannot enter, and 3 when no search tool, `date` or `sleep` is available or
the search fails. Treat a non-zero exit as a failed scan,
not as a clean one. Call it as `watch.sh <watch_path>
[window_seconds] [poll_seconds]`. It accepts the window only
as whole seconds from 0 to 999999999, so convert a window
such as `10m` to `600`. A window above 0 that ends with
`REVIEW_WATCH_WINDOW_ENDED` lasts at least `window_seconds`
and can run up to one second longer, because the deadline is
counted in whole seconds, plus the poll interval and the
scan in progress when the deadline passes. A marker already
present ends the watch at the first scan. It passes the poll
interval to `sleep` unchecked, so give it whole seconds too.

## Concurrency and safety

- Re-read before edit. The reviewer is editing the same
  files concurrently; always re-read a matched file's
  current content before changing it.
- One writer at a time. If the host repo serializes tracked
  mutations with a lock, the address-comments edits and
  review-log append must respect that lock.
- Never commit or push from the watch loop unless the host
  wrapper explicitly authorizes it. Addressing markers in a
  shared-repo worktree is a local edit; landing is a
  separate human-gated step.

## Installing

Install the whole skill directory, `SKILL.md` with
`agents/` and `scripts/`, where your coding agent loads
skills; the repository README's install blocks do that.
Install address-comments beside it. A per-repo wrapper is
optional: it can bind the `address-comments` skill to
delegate to, the watched path, the marker excludes, and the
window defaults, and delegate here. Without one, take the
watched path from the request, use the skill named
`address-comments`, and use `watch.sh`'s defaults.
