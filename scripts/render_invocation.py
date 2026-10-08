#!/usr/bin/env python3
"""Render an agent client's raw JSON-lines output as a readable transcript.

Standard library only. The output holds the prompt, every tool call
(name and arguments, each argument string cut at LIMIT characters
the same way), each call's exit status where the raw output gives
one, and the final message, copied except for the declared
replacements. Tool output is not rendered.

    python3 scripts/render_invocation.py claude-code RAW PROMPT \
        [--isolation-root DIR] --plugin-root DIR --capture-root DIR \
        [--scratch-root DIR] --home DIR --hostname NAME > transcript.txt
    python3 scripts/render_invocation.py codex RAW PROMPT \
        --last-message FILE --plugin-root DIR --capture-root DIR ...

The only edits are the declared path transforms. A root matches
only when the character after it is `/`, whitespace, a quote, a
backslash, `)` or end of text, and the character before it is
whitespace, a quote, `=`, `(` or start of text. They apply in
this order: replace-isolation-root (to /iso),
replace-plugin-root (to /plugin),
replace-scratch-root (to /scratch), replace-capture-root (to
/work), replace-home (to ~) and replace-hostname (to host).
"""

from __future__ import annotations

import argparse
import json
import re
import sys

LIMIT = 300


def cut(text: str) -> str:
    if len(text) <= LIMIT:
        return text
    return text[:LIMIT] + " ...[%d more characters]" % (len(text) - LIMIT)


# A root matches only when the character after it is `/`,
# whitespace, a quote, a backslash, `)` or end of text, and the
# character before it is whitespace, a quote, `=`, `(` or start
# of text.
AFTER = r"(?=[/\s\"'\\)]|\Z)"
BEFORE = r"(?:(?<=[\s\"'=(])|\A)"

# A character that can sit inside a host name.
NAME = r"[\w.~+-]"


def prefix(path: str, replacement: str):
    """Replace `path` where it is a root: only when the character
    after it is `/`, whitespace, a quote, a backslash, `)` or end of
    text, and the character before it is whitespace, a quote, `=`,
    `(` or start of text."""
    pattern = re.compile(BEFORE + re.escape(path.rstrip("/")) + AFTER)
    return lambda text: pattern.sub(replacement, text)


def whole_name(name: str, replacement: str):
    """Replace a host name only where it is not part of a longer name."""
    pattern = re.compile(r"(?<!" + NAME + r")" + re.escape(name) + r"(?![\w-]|\.\w)")
    return lambda text: pattern.sub(replacement, text)


def transforms(args):
    steps = []
    if args.isolation_root:
        steps.append(prefix(args.isolation_root, "/iso"))
    for root in args.plugin_root:
        steps.append(prefix(root, "/plugin"))
    for root in args.scratch_root:
        steps.append(prefix(root, "/scratch"))
    if args.capture_root:
        steps.append(prefix(args.capture_root, "/work"))
    if args.home:
        steps.append(prefix(args.home, "~"))
    if args.hostname:
        steps.append(whole_name(args.hostname, "host"))

    def apply(text: str) -> str:
        for step in steps:
            text = step(text)
        return text

    return apply


APPLY = [lambda text: text]


def argument_lines(arguments: dict) -> list:
    """Transforms run on the whole value before it is cut, so a cut
    never leaves part of a path the transforms would replace."""
    lines = []
    for key in arguments:
        value = arguments[key]
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        value = APPLY[0](value)
        lines.append("    %s: %s" % (key, cut(value).replace("\n", "\\n")))
    return lines


def claude_code(raw: str):
    calls, status, final, header = [], {}, "", []
    for line in raw.splitlines():
        event = json.loads(line)
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            header.append("client: Claude Code %s" % event.get("claude_code_version", "?"))
            header.append("model: %s" % event.get("model"))
        if kind == "result":
            final = event.get("result", "")
            header.append(
                "result: %s, %s turns, %s ms"
                % (event.get("subtype"), event.get("num_turns"), event.get("duration_ms"))
            )
        message = event.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if block.get("type") == "tool_use":
                calls.append((block["id"], block["name"], block.get("input", {}),
                              event.get("parent_tool_use_id")))
            elif block.get("type") == "tool_result":
                error = block.get("is_error")
                status[block["tool_use_id"]] = (
                    "error" if error else "ok" if error is False else "not reported"
                )
    lines = []
    for number, (ident, name, arguments, parent) in enumerate(calls, 1):
        where = " (sub-agent)" if parent else ""
        lines.append("[%d] %s%s" % (number, name, where))
        lines.extend(argument_lines(arguments))
        lines.append("    status: %s" % status.get(ident, "no result"))
    return header, lines, final


def codex(raw: str, last_message: str):
    lines, header, number = [], [], 0
    for line in raw.splitlines():
        event = json.loads(line)
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
            header.append("result: turn completed, %s output tokens" % usage.get("output_tokens"))
        if event.get("type") != "item.completed":
            continue
        item = event["item"]
        if item.get("type") in ("agent_message", "reasoning"):
            continue
        number += 1
        if item.get("type") == "command_execution":
            lines.append("[%d] command_execution" % number)
            lines.extend(argument_lines({"command": item.get("command", "")}))
            code = item.get("exit_code")
            lines.append("    status: %s" % ("exit %s" % code if code is not None else "not reported"))
        else:
            arguments = {k: v for k, v in item.items() if k not in ("id", "type", "status")}
            lines.append("[%d] %s" % (number, item.get("type")))
            lines.extend(argument_lines(arguments))
            lines.append("    status: %s" % item.get("status", "not reported"))
    return header, lines, last_message


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client", choices=("claude-code", "codex"))
    parser.add_argument("raw")
    parser.add_argument("prompt")
    parser.add_argument("--last-message")
    parser.add_argument("--isolation-root")
    parser.add_argument("--plugin-root", action="append", default=[])
    parser.add_argument("--scratch-root", action="append", default=[])
    parser.add_argument("--capture-root")
    parser.add_argument("--home")
    parser.add_argument("--hostname")
    args = parser.parse_args(argv)
    APPLY[0] = transforms(args)
    with open(args.raw, encoding="utf-8") as handle:
        raw = handle.read()
    with open(args.prompt, encoding="utf-8") as handle:
        prompt = handle.read().rstrip("\n")
    if args.client == "claude-code":
        header, calls, final = claude_code(raw)
    else:
        if not args.last_message:
            parser.error("codex needs --last-message")
        with open(args.last_message, encoding="utf-8") as handle:
            header, calls, final = codex(raw, handle.read())
    out = ["# %s invocation transcript" % args.client, ""]
    out += header + ["", "## Prompt", "", prompt, "", "## Tool calls", ""]
    out += calls + ["", "## Final message", "", final.rstrip("\n"), ""]
    sys.stdout.write(APPLY[0]("\n".join(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
