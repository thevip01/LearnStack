#!/usr/bin/env python3
"""Structural checks on the repo's shell scripts, for defects that hide.

`shellcheck` is the right tool for shell and this is not a replacement for it.
It is a gate that runs with nothing installed, on a machine with no package
manager and no network, next to the other stdlib-only checkers in this directory.
Every rule below exists because the defect it describes actually shipped here and
cost real debugging time, and every one of them is invisible in review: the code
reads correctly and does something else.

The rules:

1.  A bare ``exec`` that redirects stdout or stderr to /dev/null.

    ``exec`` with no command word applies its redirections to the *current
    shell*, permanently. So a line meant to suppress noise from one cleanup step

        exec 3>&- 2>/dev/null || true

    does not suppress that step. It points the script's stderr at /dev/null for
    the rest of its life. In ``dev_local.sh`` this sat inside the port check, so
    the first busy port silenced every later error message, including the one
    explaining the busy port. What the user got was a blank line, ``stopped.``,
    and ``make: *** [dev-local] Error 1``, with the cause written to nowhere.

2.  An EXIT trap that prints without consulting ``$?``.

    A handler that cannot see the exit status prints the same thing whether the
    script succeeded or died, which turns every failure into a clean shutdown.
    Combined with ``set -e``, which exits silently by design, that is a script
    that cannot report its own failures. A non-printing handler (``rm -rf
    "$WORK"``) is fine and is not flagged: it makes no claim about what happened.

3.  ``set -u`` and ``pipefail`` missing.

    ``-e`` is deliberately not required. ``verify_loop.sh`` counts its own
    failures and exits with its own status, and forcing errexit on it would be
    wrong. Unset variables and swallowed pipeline statuses have no such defence.

4.  bash 4 syntax.

    macOS ships bash 3.2 from 2007 and will not ship a newer one, and the
    primary development machine for this project is a Mac. ``${var^^}``,
    ``mapfile``, ``declare -A`` and ``wait -n`` all parse fine on the CI Linux
    box and fail only there, which is the worst place for a defect to live.

5.  A missing or non-bash shebang on a script using bash-only syntax.

Usage:
    python3 tools/check_shell.py [path ...]

Exit code 1 if anything is flagged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".next", "websurf"}

#: One redirection: optional fd, operator, target. ``&-`` and ``&1`` are targets too.
REDIRECTION = re.compile(r"^(?P<fd>[0-9]*)(?P<op><<<|<<|>>|<>|>&|<&|&>>|&>|>|<)\s*(?P<target>[^\s;|&()]*)")

#: Constructs that need bash 4 or newer, with the version that introduced them.
BASH4 = (
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?(?:\^\^|\^|,,|,)[^}]*\}"), "${var^^} case conversion", "4.0"),
    (re.compile(r"\bmapfile\b|\breadarray\b"), "mapfile/readarray", "4.0"),
    (re.compile(r"\b(?:declare|typeset|local)\s+-[A-Za-z]*A\b"), "associative arrays (declare -A)", "4.0"),
    (re.compile(r"\bwait\s+-n\b"), "wait -n", "4.3"),
    (re.compile(r"\bcoproc\b"), "coproc", "4.0"),
    (re.compile(r"&>>"), "&>> append-both redirection", "4.0"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*@[UuLQaAKk]\}"), "${var@Q} parameter transformation", "4.4"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:[^}]*\}\s*;\s*#\s*negative"), "negative substring offsets", "4.2"),
)

#: Anything that writes to the terminal. ``:`` and ``true`` deliberately absent.
PRINTS = re.compile(r"\b(?:echo|printf|cat|tee|>&2)\b|>&2")

#: bash-only syntax, used to decide whether a `sh` shebang is a defect.
BASH_ONLY = re.compile(r"\[\[|\(\(|\blocal\b|\bdeclare\b|=\(|\bshopt\b|\bBASH_SOURCE\b|\bfunction\b")


class Line:
    """A logical line: shell source with comments removed, quotes balanced.

    Joined across physical lines when a quote or a trailing backslash is left
    open, because the handler bodies and multi-line traps this file needs to
    reason about are written that way. ``lineno`` is where it started, which is
    what a person needs in order to find it.
    """

    __slots__ = ("lineno", "text")

    def __init__(self, lineno: int, text: str) -> None:
        self.lineno = lineno
        self.text = text


def logical_lines(source: str) -> list[Line]:
    """Split a script into logical lines, dropping comments.

    Quote state is tracked across the whole file rather than per line, so a ``#``
    inside a quoted string is not mistaken for a comment and a commented-out
    example of a defect is not reported as the defect. This file's own docstring
    contains one, and so does the fix in ``dev_local.sh``.
    """
    out: list[Line] = []
    buffer: list[str] = []
    start = 1
    quote = ""  # "" or "'" or '"'
    for number, raw in enumerate(source.splitlines(), start=1):
        if not buffer:
            start = number
        index = 0
        piece: list[str] = []
        while index < len(raw):
            char = raw[index]
            if quote:
                piece.append(char)
                if char == "\\" and quote == '"' and index + 1 < len(raw):
                    piece.append(raw[index + 1])
                    index += 2
                    continue
                if char == quote:
                    quote = ""
                index += 1
                continue
            if char == "\\" and index + 1 < len(raw):
                piece.append(raw[index : index + 2])
                index += 2
                continue
            if char in "'\"":
                quote = char
                piece.append(char)
                index += 1
                continue
            if char == "#" and (index == 0 or raw[index - 1].isspace()) and not "".join(piece).strip().endswith("$"):
                break
            piece.append(char)
            index += 1
        text = "".join(piece)
        continued = text.rstrip().endswith("\\") and not text.rstrip().endswith("\\\\")
        buffer.append(text.rstrip()[:-1] if continued else text)
        if quote or continued:
            buffer.append("\n" if quote else " ")
            continue
        joined = "".join(buffer).strip()
        buffer = []
        if joined:
            out.append(Line(start, joined))
    if buffer:
        joined = "".join(buffer).strip()
        if joined:
            out.append(Line(start, joined))
    return out


def commands(text: str) -> list[str]:
    """Split a logical line into simple commands on ``;``, ``|``, ``&&``, ``||``.

    Quote-aware and paren-aware, so a separator inside a string or a subshell
    stays part of the command it belongs to. Not a shell parser: the goal is to
    find the word a command starts with, which is all any rule here needs.
    """
    out: list[str] = []
    current: list[str] = []
    quote = ""
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "'\"":
            quote = char
            current.append(char)
            index += 1
            continue
        if char in "({":
            depth += 1
        elif char in ")}":
            depth = max(0, depth - 1)
        if depth == 0:
            if text.startswith("&&", index) or text.startswith("||", index):
                out.append("".join(current))
                current = []
                index += 2
                continue
            # `&` is a separator when it backgrounds a command and part of the token
            # when it belongs to a redirection: `2>&1`, `3>&-`, `&>file`. Splitting on
            # it unconditionally cost this checker its most important finding, because
            # `exec 3>&- 2>/dev/null` became three fragments and the rule that reads a
            # command's full redirection list never saw one.
            if char == "&":
                previous = current[-1] if current else ""
                following = text[index + 1] if index + 1 < len(text) else ""
                if previous in "<>" or following == ">":
                    current.append(char)
                    index += 1
                    continue
            if char in ";|&\n":
                out.append("".join(current))
                current = []
                index += 1
                continue
        current.append(char)
        index += 1
    out.append("".join(current))
    return [command.strip() for command in out if command.strip()]


def leading_word(command: str) -> str:
    """First word of a simple command, past any keyword or assignment prefix."""
    words = command.split()
    keywords = {"then", "else", "elif", "do", "done", "fi", "!", "time", "{", "}", "(", ")"}
    for word in words:
        stripped = word.lstrip("({!")
        if not stripped or stripped in keywords:
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", stripped):
            continue
        return stripped
    return ""


def redirections(rest: str) -> list[tuple[str, str, str]] | None:
    """``(fd, op, target)`` for a command that is *only* redirections.

    ``None`` when a real word appears, which means ``exec some-command``: the
    redirections there apply to the program that replaces the shell, and are a
    different thing entirely from the bare form this file cares about.
    """
    found: list[tuple[str, str, str]] = []
    text = rest.strip()
    while text:
        match = REDIRECTION.match(text)
        if not match:
            return None
        found.append((match.group("fd"), match.group("op"), match.group("target")))
        text = text[match.end() :].strip()
    return found


def function_bodies(lines: list[Line]) -> dict[str, str]:
    """Name -> body text, for shell functions defined in this file."""
    bodies: dict[str, str] = {}
    index = 0
    while index < len(lines):
        match = re.match(r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_:.-]*)\s*\(\)\s*\{?", lines[index].text)
        if not match:
            index += 1
            continue
        name = match.group(1)
        depth = lines[index].text.count("{") - lines[index].text.count("}")
        collected = [lines[index].text]
        cursor = index + 1
        while cursor < len(lines) and depth > 0:
            collected.append(lines[cursor].text)
            depth += lines[cursor].text.count("{") - lines[cursor].text.count("}")
            cursor += 1
        bodies[name] = "\n".join(collected)
        index = cursor
    return bodies


def check_exec_silencing(path: Path, lines: list[Line]) -> list[str]:
    problems: list[str] = []
    for line in lines:
        for command in commands(line.text):
            if leading_word(command) != "exec":
                continue
            rest = command.split("exec", 1)[1]
            parsed = redirections(rest)
            if parsed is None:
                continue  # `exec a-command`, not the bare form
            for fd, op, target in parsed:
                if op in (">", ">>", ">&", "&>", "&>>") and target == "/dev/null" and fd in ("", "1", "2"):
                    stream = {"": "stdout", "1": "stdout", "2": "stderr"}[fd]
                    problems.append(
                        f"{path}:{line.lineno}: bare `exec` redirects {stream} to /dev/null, which silences "
                        f"the rest of the script, not this command. Drop the redirection, or move it onto "
                        f"the command that should be quiet."
                    )
    return problems


def check_exit_trap(path: Path, lines: list[Line]) -> list[str]:
    problems: list[str] = []
    bodies = function_bodies(lines)
    for line in lines:
        for command in commands(line.text):
            if leading_word(command) != "trap":
                continue
            arguments = command.split("trap", 1)[1].strip()
            if not arguments or arguments.startswith("-"):
                continue  # `trap - EXIT` disarms, and cannot lie about anything
            match = re.match(r"^('([^']*)'|\"([^\"]*)\"|(\S+))\s*(?P<signals>.*)$", arguments, re.S)
            if not match:
                continue
            handler = match.group(2) or match.group(3) or match.group(4) or ""
            signals = {word.upper().removeprefix("SIG") for word in match.group("signals").split()}
            if "EXIT" not in signals and "0" not in signals:
                continue
            body = bodies.get(handler.strip(), handler)
            if not PRINTS.search(body):
                continue  # a silent handler makes no claim about what happened
            if "$?" in body or "${?}" in body:
                continue
            problems.append(
                f"{path}:{line.lineno}: EXIT trap prints but never reads $?, so a failure and a clean "
                f"shutdown produce the same output. Capture `local code=$?` first and say which happened."
            )
    return problems


def check_set_options(path: Path, lines: list[Line]) -> list[str]:
    options = ""
    for line in lines:
        for command in commands(line.text):
            if leading_word(command) == "set":
                options += " " + command
    if not options:
        return [f"{path}:1: no `set` line. At minimum `set -uo pipefail`."]
    problems: list[str] = []
    if not re.search(r"-[a-z]*u", options):
        problems.append(f"{path}:1: `set -u` missing, so a typo in a variable name expands to nothing.")
    if "pipefail" not in options:
        problems.append(f"{path}:1: `set -o pipefail` missing, so a failure mid-pipeline is invisible.")
    return problems


def check_bash_version(path: Path, lines: list[Line], shebang: str) -> list[str]:
    problems: list[str] = []
    for line in lines:
        for pattern, what, version in BASH4:
            if pattern.search(line.text):
                problems.append(
                    f"{path}:{line.lineno}: {what} needs bash {version}. macOS ships bash 3.2, "
                    f"so this parses on Linux and fails on a Mac."
                )
    if not shebang:
        problems.append(f"{path}:1: no shebang.")
    elif "bash" not in shebang:
        offenders = [line.lineno for line in lines if BASH_ONLY.search(line.text)]
        if offenders:
            problems.append(
                f"{path}:1: shebang is {shebang.strip()!r} but line {offenders[0]} uses bash-only syntax."
            )
    return problems


def shell_files(roots: tuple[Path, ...]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_file():
            out.append(root)
            continue
        for path in root.rglob("*.sh"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            out.append(path)
    return sorted(set(out))


def main(argv: list[str]) -> int:
    roots = tuple(Path(argument).resolve() for argument in argv[1:]) or (REPO,)
    files = shell_files(roots)
    if not files:
        print("no shell scripts found, which is not something this repo should be able to do")
        return 1

    problems: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        shebang = source.splitlines()[0] if source.startswith("#!") else ""
        lines = logical_lines(source)
        where = path.relative_to(REPO) if path.is_relative_to(REPO) else path
        found = (
            check_exec_silencing(where, lines)
            + check_exit_trap(where, lines)
            + check_set_options(where, lines)
            + check_bash_version(where, lines, shebang)
        )
        # By line, not by rule. Four rules run per file and reporting in rule order
        # means jumping around the file, which is the wrong shape for something read
        # while a build is broken.
        problems += sorted(found, key=lambda problem: int(re.search(r":(\d+):", problem).group(1)))

    if problems:
        for problem in problems:
            print(problem)
        print(f"\n{len(problems)} problem(s) across {len(files)} script(s)")
        return 1

    total = sum(len(logical_lines(path.read_text(encoding='utf-8'))) for path in files)
    print(f"ok: {len(files)} scripts, {total} logical lines, no silenced streams or bash 4 syntax")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
