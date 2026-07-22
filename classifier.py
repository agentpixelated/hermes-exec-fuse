"""Conservative shell command classification and normalization."""

from __future__ import annotations

import re
import shlex
from enum import Enum


class CommandClass(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    UNKNOWN = "unknown"


_READ_ONLY = {
    "pwd", "ls", "find", "fd", "rg", "grep", "cat", "head", "tail",
    "wc", "sort", "uniq", "cut", "tr", "stat", "du", "df", "env",
    "printenv", "which", "whereis", "id", "whoami", "uname", "date",
    "realpath", "readlink", "file", "basename", "dirname", "echo", "printf",
    "awk",
}

_MUTATING = {
    "rm", "mv", "cp", "touch", "mkdir", "rmdir", "ln", "chmod", "chown",
    "install", "truncate", "dd", "mkfs", "mount", "umount", "kill", "pkill",
    "curl", "wget", "ssh", "scp", "rsync", "docker", "podman", "kubectl",
    "terraform", "ansible", "make", "cmake", "ninja", "bash", "sh", "zsh",
    "python", "python3", "node", "ruby", "perl", "php", "pip", "pip3",
    "npm", "pnpm", "yarn", "apt", "apt-get", "brew", "cargo", "go",
}

_GIT_READ_ONLY = {
    "status", "diff", "show", "log", "rev-parse", "ls-files", "ls-tree",
    "grep", "describe", "shortlog", "tag", "remote", "config",
}

_GIT_MUTATING = {
    "add", "commit", "checkout", "switch", "reset", "restore", "merge",
    "rebase", "cherry-pick", "revert", "stash", "apply", "am", "clean",
    "init", "clone", "fetch", "pull", "push", "worktree", "submodule",
}

_REDIRECTION = re.compile(r"(^|\s)(?:\d?>|\d?>>|&>|<>|<<)(?=\s|\S)")
_SPLIT_OPERATORS = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


def normalize_command(command: str) -> str:
    """Normalize superficial whitespace without rewriting shell semantics."""
    return re.sub(r"\s+", " ", (command or "").strip())


def _strip_prefixes(tokens: list[str]) -> list[str]:
    while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    if tokens and tokens[0] in {"command", "env"}:
        tokens.pop(0)
        while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
            tokens.pop(0)
    if tokens and tokens[0] == "sudo":
        return []
    return tokens


def _classify_git(tokens: list[str]) -> CommandClass:
    if len(tokens) < 2:
        return CommandClass.UNKNOWN
    subcommand = tokens[1]
    args = tokens[2:]
    if subcommand in _GIT_MUTATING:
        return CommandClass.MUTATING
    if subcommand == "branch":
        safe_flags = {
            "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose",
            "--list", "--show-current", "--contains", "--no-contains",
            "--merged", "--no-merged", "--sort", "--format", "--column",
            "--no-column", "--color", "--no-color", "--points-at",
        }
        for arg in args:
            if arg.startswith("-") and arg.split("=", 1)[0] not in safe_flags:
                return CommandClass.MUTATING
            if not arg.startswith("-"):
                return CommandClass.UNKNOWN
        return CommandClass.READ_ONLY
    if subcommand == "config":
        mutating_flags = {
            "--add", "--replace-all", "--unset", "--unset-all",
            "--remove-section", "--rename-section",
        }
        if any(arg in mutating_flags for arg in args):
            return CommandClass.MUTATING
        positional = [arg for arg in args if not arg.startswith("-")]
        return CommandClass.READ_ONLY if len(positional) <= 1 else CommandClass.MUTATING
    if subcommand == "remote":
        if args and args[0] not in {"-v", "--verbose", "show", "get-url"}:
            return CommandClass.MUTATING
        return CommandClass.READ_ONLY
    if subcommand == "tag":
        if any(arg in {"-d", "--delete", "-f", "--force", "-a", "-s", "-u"} for arg in args):
            return CommandClass.MUTATING
        positional = [arg for arg in args if not arg.startswith("-")]
        if positional and not any(arg in {"-l", "--list"} for arg in args):
            return CommandClass.MUTATING
        return CommandClass.READ_ONLY
    if subcommand in _GIT_READ_ONLY:
        return CommandClass.READ_ONLY
    return CommandClass.UNKNOWN


def _classify_segment(segment: str) -> CommandClass:
    try:
        tokens = _strip_prefixes(shlex.split(segment, posix=True))
    except ValueError:
        return CommandClass.UNKNOWN
    if not tokens:
        return CommandClass.UNKNOWN

    base = tokens[0]
    args = tokens[1:]
    if base == "git":
        return _classify_git(tokens)
    if base == "sed":
        mutating = any(arg == "-i" or arg.startswith("-i") for arg in args)
        return CommandClass.MUTATING if mutating else CommandClass.READ_ONLY
    if base == "ruff":
        safe = args[:1] == ["check"] and "--fix" not in args and "--fix-only" not in args
        return CommandClass.READ_ONLY if safe else CommandClass.UNKNOWN
    if base in {"eslint", "prettier"}:
        return CommandClass.READ_ONLY if "--fix" not in args and "--write" not in args else CommandClass.MUTATING
    if base in {"pytest", "py.test"}:
        return CommandClass.READ_ONLY if "--collect-only" in args else CommandClass.UNKNOWN
    if base in {"python", "python3"} and args[:2] == ["-m", "pytest"]:
        return CommandClass.READ_ONLY if "--collect-only" in args else CommandClass.UNKNOWN
    if base in {"npm", "pnpm", "yarn"}:
        safe_subcommands = {"list", "ls", "view", "info", "why", "outdated"}
        return CommandClass.READ_ONLY if args[:1] and args[0] in safe_subcommands else CommandClass.MUTATING
    if base in _READ_ONLY:
        return CommandClass.READ_ONLY
    if base in _MUTATING:
        return CommandClass.MUTATING
    return CommandClass.UNKNOWN


def classify_command(command: str) -> CommandClass:
    """Classify a command conservatively; UNKNOWN is never cached or deduplicated."""
    normalized = normalize_command(command)
    if not normalized:
        return CommandClass.UNKNOWN
    unsafe_shell_syntax = (
        _REDIRECTION.search(normalized)
        or ">" in normalized
        or "<" in normalized
        or "`" in normalized
        or "$(" in normalized
    )
    if unsafe_shell_syntax:
        return CommandClass.MUTATING

    segments = [segment for segment in _SPLIT_OPERATORS.split(normalized) if segment]
    classes = [_classify_segment(segment) for segment in segments]
    if any(item == CommandClass.MUTATING for item in classes):
        return CommandClass.MUTATING
    if classes and all(item == CommandClass.READ_ONLY for item in classes):
        return CommandClass.READ_ONLY
    return CommandClass.UNKNOWN
