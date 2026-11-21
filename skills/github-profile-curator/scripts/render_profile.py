#!/usr/bin/env python3
"""Render a GitHub profile section to stdout; never edit inputs or use the network."""

import argparse
import json
import os
from pathlib import Path
import re
import string
import sys
import unicodedata

START = b"<!-- github-profile-curator:start -->"
END = b"<!-- github-profile-curator:end -->"
PREFIX = b"<!-- github-profile-curator"
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")


def plain_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty plain text")
    if any(unicodedata.category(c).startswith("C") or c in "\u2028\u2029" for c in value):
        raise ValueError(f"{field} must be one line without control characters")
    return value


def literal(value):
    """Keep user text literal in Markdown labels, prose and HTML contexts."""
    entities = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
    return "".join(entities.get(c, "\\" + c if c in string.punctuation else c) for c in value)


def section(spec, newline):
    if not isinstance(spec, dict) or set(spec) != {"owner", "heading", "projects"}:
        raise ValueError("projects JSON needs exactly owner, heading and projects")
    owner = spec["owner"]
    if not isinstance(owner, str) or not OWNER.fullmatch(owner) or "--" in owner:
        raise ValueError("owner must be a GitHub-style account name")
    heading = plain_text(spec["heading"], "heading")
    if not isinstance(spec["projects"], list):
        raise ValueError("projects must be an array")
    lines = [START.decode(), "## " + literal(heading), ""]
    seen = set()
    for project in spec["projects"]:
        if not isinstance(project, dict) or set(project) != {"repo", "title", "description"}:
            raise ValueError("each project needs exactly repo, title and description")
        repo = project["repo"]
        if not isinstance(repo, str) or not REPO.fullmatch(repo) or repo in {".", ".."}:
            raise ValueError("repo must be a single safe repository name")
        if repo.casefold() in seen:
            raise ValueError("duplicate repository name")
        seen.add(repo.casefold())
        title = literal(plain_text(project["title"], "title"))
        description = literal(plain_text(project["description"], "description"))
        lines.append(f"- [{title}](https://github.com/{owner}/{repo}) — {description}")
    lines.append(END.decode())
    return newline.join(line.encode("utf-8") for line in lines)


def separator(prefix, newline):
    if not prefix or prefix.endswith(newline + newline):
        return b""
    return newline if prefix.endswith(newline) else newline + newline


def render_profile(readme, spec, before=None):
    """Return UTF-8 bytes, preserving every byte outside the generated section."""
    readme.decode("utf-8")
    match = re.search(rb"\r\n|\n|\r", readme)
    newline = match.group() if match else b"\n"
    block = section(spec, newline)
    if before is not None:
        plain_text(before, "before")
        if not re.fullmatch(r"#{1,6} [^\r\n]+", before):
            raise ValueError("before must be an exact Markdown heading")
    starts, ends = readme.count(START), readme.count(END)
    if readme.count(PREFIX) != starts + ends or (starts, ends) not in {(0, 0), (1, 1)}:
        raise ValueError("partial or duplicate curator markers")
    if starts:
        start, end = readme.index(START), readme.index(END)
        if start >= end:
            raise ValueError("reversed curator markers")
        for pos, marker in ((start, START), (end, END)):
            tail = pos + len(marker)
            if (pos and readme[pos - 1:pos] not in (b"\n", b"\r")) or (
                tail < len(readme) and readme[tail:tail + 1] not in (b"\n", b"\r")
            ):
                raise ValueError("curator markers must occupy their own lines")
        return readme[:start] + block + readme[end + len(END):]
    if before is not None:
        positions, offset = [], 0
        for line in readme.splitlines(keepends=True):
            if line.rstrip(b"\r\n") == before.encode("utf-8"):
                positions.append(offset)
            offset += len(line)
        if len(positions) != 1:
            raise ValueError("before heading must occur exactly once")
        pos = positions[0]
        return readme[:pos] + separator(readme[:pos], newline) + block + newline * 2 + readme[pos:]
    ending = newline if not readme or readme.endswith((b"\r", b"\n")) else b""
    return readme + separator(readme, newline) + block + ending


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--projects", type=Path, required=True)
    parser.add_argument("--before")
    args = parser.parse_args(argv)
    try:
        # Shell redirection can truncate a file before Python starts: use a DIFFERENT output path.
        out = os.fstat(sys.stdout.fileno())
        for path in (args.readme, args.projects):
            source = path.stat()
            if (out.st_dev, out.st_ino) == (source.st_dev, source.st_ino):
                raise ValueError("stdout must use a different path from both input files")
        spec = json.loads(args.projects.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        output = render_profile(args.readme.read_bytes(), spec, args.before)
        sys.stdout.buffer.write(output)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
