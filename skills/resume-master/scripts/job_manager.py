#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path


def write_jd(project: Path, company: str, role: str, text: str) -> Path:
    jd_dir = project / "jd"
    jd_dir.mkdir(parents=True, exist_ok=True)
    output = jd_dir / "jd_raw.md"
    output.write_text(
        "# Job Description\n\n"
        f"- Company: {company or 'XX'}\n"
        f"- Role: {role or 'XX'}\n\n"
        "## Raw Text\n\n"
        f"{text.strip()}\n",
        encoding="utf-8",
    )
    return output


def fetch_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - user-provided CLI URL
        data = response.read()
    return data.decode("utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage job descriptions for Resume Master")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_text = subparsers.add_parser("add-text")
    add_text.add_argument("--project", required=True)
    add_text.add_argument("--company", default="XX")
    add_text.add_argument("--role", default="XX")
    add_text.add_argument("--text", required=True)

    fetch = subparsers.add_parser("fetch-url")
    fetch.add_argument("--project", required=True)
    fetch.add_argument("--url", required=True)
    fetch.add_argument("--company", default="XX")
    fetch.add_argument("--role", default="XX")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "add-text":
            output = write_jd(Path(args.project).resolve(), args.company, args.role, args.text)
        else:
            output = write_jd(Path(args.project).resolve(), args.company, args.role, fetch_url(args.url))
        print(output.resolve())
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
