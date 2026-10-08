#!/usr/bin/env bash
#
# review-watch reference poller.
#
# Scan a path for agent-directed review markers using the
# address-comments marker grammar, once per poll interval, and
# exit at the first scan that finds one (printing the matches)
# or when the window elapses. Drive the address-comments workflow on each reported
# match; this script only detects, it does not edit.
#
# Usage: watch.sh <watch_path> [window_seconds] [poll_seconds]
#
# Host wrappers may extend the operator-label alternation via
# the REVIEW_WATCH_LABELS environment variable, for example:
#   REVIEW_WATCH_LABELS='reviewer[[:space:]]+says:'
# The value is passed to whichever search tool runs, so write
# it in syntax that both ripgrep and POSIX ERE accept.
#
# Uses ripgrep (rg) when it is on PATH. Otherwise it falls back
# to grep -rEn with the same marker grammar written as POSIX
# ERE; the README lists where the two differ. If neither tool
# is on PATH, date or sleep is missing, or the search exits
# with an error status, it prints a message to stderr and
# exits 3. Argument and watch-path errors exit 1 or 2; the
# README's exit-status table lists them.

set -u

USAGE="usage: watch.sh <watch_path> [window_seconds] [poll_seconds]"

if [ "$#" -lt 1 ] || [ -z "$1" ]; then
  echo "watch.sh: a watch_path is required" >&2
  echo "$USAGE" >&2
  exit 1
fi
WATCH_PATH="$1"
# Only an omitted argument takes the default; an empty one is
# checked like any other value.
WINDOW="${2-600}"
POLL="${3-12}"

# A non-negative decimal integer without leading zeros (bash
# arithmetic would read 08 as a bad octal number) and of at
# most nine digits (so the deadline cannot overflow).
case "$WINDOW" in
  '' | *[!0-9]* | 0?* | ??????????*)
    echo "watch.sh: window_seconds must be a whole number of seconds from 0 to 999999999, got '$WINDOW'" >&2
    echo "$USAGE" >&2
    exit 2
    ;;
esac

# A path that starts with "-" is searched as ./<path>, so that
# neither tool reads it as an option or, for "-", as standard
# input.
SEARCH_PATH="$WATCH_PATH"
case "$SEARCH_PATH" in
  -*)
    SEARCH_PATH="./$SEARCH_PATH"
    ;;
esac

# Excluded directories (node_modules, .next, .git) are never
# searched, however the watch path is written. Two forms of
# the path are checked, and the path is refused if either
# has an excluded component:
# - as written, with "." and ".." components folded away
#   (so node_modules/../src is not refused), and
# - where it physically is: a directory by its physical
#   absolute path, anything else by its parent directory's
#   physical absolute path and its own name (so "." inside
#   node_modules, or a symlink into one, is refused).
# A symlink that does not point to a directory is refused,
# because where it leads is not checked. A path whose parent
# does not exist is checked as written. Names are compared
# with case.
is_excluded() {
  case "/$1/" in
    */node_modules/* | */.next/* | */.git/*)
      return 0
      ;;
  esac
  return 1
}

# Print a path with empty, "." and ".." components folded
# away lexically, without touching the file system.
fold_path() {
  local input="$1"
  local prefix=""
  local part
  local count
  local kept=()
  local saved_ifs="$IFS"
  case "$input" in
    /*)
      prefix=/
      ;;
  esac
  IFS=/
  set -f
  for part in $input; do
    count=${#kept[@]}
    case "$part" in
      '' | .)
        ;;
      ..)
        if [ "$count" -gt 0 ] && [ "${kept[$((count - 1))]}" != ".." ]; then
          unset "kept[$((count - 1))]"
        elif [ -z "$prefix" ]; then
          kept[$count]=".."
        fi
        ;;
      *)
        kept[$count]="$part"
        ;;
    esac
  done
  set +f
  local joined=""
  if [ "${#kept[@]}" -gt 0 ]; then
    joined="${kept[*]}"
  fi
  IFS="$saved_ifs"
  if [ -n "$prefix" ]; then
    echo "/$joined"
    return
  fi
  if [ -z "$joined" ]; then
    echo "."
    return
  fi
  echo "$joined"
}

# A trailing slash would hide a symlink from -L.
BARE_PATH="$SEARCH_PATH"
while [ "${#BARE_PATH}" -gt 1 ]; do
  case "$BARE_PATH" in
    */)
      BARE_PATH="${BARE_PATH%/}"
      ;;
    *)
      break
      ;;
  esac
done
if [ -L "$BARE_PATH" ] && [ ! -d "$BARE_PATH" ]; then
  echo "watch.sh: $WATCH_PATH is a symlink that does not point to a directory; give the file's own path" >&2
  exit 2
fi
# A directory that cannot be entered cannot be resolved, so
# it is refused rather than guessed at.
refuse_unresolved() {
  echo "watch.sh: cannot enter $1 to check where $WATCH_PATH is; check its permissions" >&2
  exit 2
}
if [ -d "$SEARCH_PATH" ]; then
  RESOLVED="$(CDPATH='' cd -- "$SEARCH_PATH" 2>/dev/null && pwd -P)" || refuse_unresolved "$SEARCH_PATH"
else
  case "$BARE_PATH" in
    */*)
      PARENT="${BARE_PATH%/*}"
      NAME="${BARE_PATH##*/}"
      ;;
    *)
      PARENT=.
      NAME="$BARE_PATH"
      ;;
  esac
  if [ -z "$PARENT" ]; then
    PARENT=/
  fi
  RESOLVED=""
  if [ -d "$PARENT" ]; then
    RESOLVED_PARENT="$(CDPATH='' cd -- "$PARENT" 2>/dev/null && pwd -P)" || refuse_unresolved "$PARENT"
    RESOLVED="$RESOLVED_PARENT/$NAME"
  fi
fi
FOLDED="$(fold_path "$SEARCH_PATH")"
if is_excluded "$FOLDED" || is_excluded "$RESOLVED"; then
  echo "watch.sh: $WATCH_PATH is, or is inside, an excluded directory (node_modules, .next or .git); excluded directories are never searched" >&2
  exit 2
fi

# Search the folded path when it leads where it reads, and
# the physical path when a symlink makes the two differ. The
# exclude patterns match the path as the tool sees it, so
# neither then drops the watch path itself.
case "$FOLDED" in
  /*)
    LOGICAL="$FOLDED"
    ;;
  *)
    LOGICAL="$(fold_path "$(pwd -P)/$FOLDED")"
    ;;
esac
if [ -n "$RESOLVED" ] && [ "$RESOLVED" != "$LOGICAL" ]; then
  SEARCH_PATH="$RESOLVED"
else
  SEARCH_PATH="$FOLDED"
  case "$SEARCH_PATH" in
    -*)
      SEARCH_PATH="./$SEARCH_PATH"
      ;;
  esac
fi

for REQUIRED in date sleep; do
  if ! command -v "$REQUIRED" >/dev/null 2>&1; then
    echo "watch.sh: $REQUIRED is not on PATH; cannot time the watch" >&2
    exit 3
  fi
done

if command -v rg >/dev/null 2>&1; then
  BACKEND=rg
elif command -v grep >/dev/null 2>&1; then
  BACKEND=grep
else
  echo "watch.sh: neither rg nor grep is on PATH; cannot scan $WATCH_PATH" >&2
  exit 3
fi

EXTRA_LABELS="${REVIEW_WATCH_LABELS:-}"
LABEL_ALT='agents?:|to[[:space:]]+agents?\b'
# POSIX ERE has no \b; a following non-word character or the
# end of the line stands in for it.
GREP_LABEL_ALT='agents?:|to[[:space:]]+agents?([^[:alnum:]_]|$)'
if [ -n "$EXTRA_LABELS" ]; then
  LABEL_ALT="$LABEL_ALT|$EXTRA_LABELS"
  GREP_LABEL_ALT="$GREP_LABEL_ALT|$EXTRA_LABELS"
fi

# address-comments marker grammar: agent/operator labels in a
# comment leader, TODO(agent)/TODO(agents), and
# TODO(code-review:<id>).
RE="((^|[[:space:]])(//|#|--|/\\*|\\*|<!--)\\s*($LABEL_ALT)|TODO\\s*\\(\\s*agents?\\s*\\)|TODO\\(code-review:[^)]+\\))"
# The same grammar in POSIX ERE, for the grep fallback.
GREP_RE="((^|[[:space:]])(//|#|--|/\\*|\\*|<!--)[[:space:]]*($GREP_LABEL_ALT)|TODO[[:space:]]*\\([[:space:]]*agents?[[:space:]]*\\)|TODO\\(code-review:[^)]+\\))"

scan() {
  if [ "$BACKEND" = rg ]; then
    rg --no-config -n -i \
      --glob '!**/node_modules/**' \
      --glob '!**/.next/**' \
      --glob '!**/.git/**' \
      -e "$RE" -- "$SEARCH_PATH" 2>/dev/null
    return
  fi
  grep -rEn -i -I \
    --exclude-dir=node_modules \
    --exclude-dir=.next \
    --exclude-dir=.git \
    -e "$GREP_RE" -- "$SEARCH_PATH" 2>/dev/null
}

# date +%s counts whole seconds, so one is added to any window
# above 0: a watch that reaches the deadline then lasts at
# least the window, and up to one second longer before the
# last poll interval and scan. A window of 0 scans nothing.
DEADLINE=$(date +%s)
if [ "$WINDOW" -gt 0 ]; then
  DEADLINE=$((DEADLINE + WINDOW + 1))
fi
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  HITS="$(scan)"
  SCAN_STATUS=$?
  if [ "$SCAN_STATUS" -ge 2 ]; then
    echo "watch.sh: $BACKEND exited with status $SCAN_STATUS while scanning $WATCH_PATH; run it by hand to see the error" >&2
    exit 3
  fi
  if [ -n "$HITS" ]; then
    echo "REVIEW_WATCH_MARKERS"
    echo "$HITS"
    exit 0
  fi
  sleep "$POLL"
done

echo "REVIEW_WATCH_WINDOW_ENDED"
exit 0
