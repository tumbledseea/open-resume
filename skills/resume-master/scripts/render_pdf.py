#!/usr/bin/env python
"""Compile LaTeX resume to PDF.

Usage:
    python scripts/render_pdf.py --project <project_path>

Looks for latex/resume.tex in the project directory, then runs xelatex to
produce exports/resume.pdf.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = SCRIPT_DIR.parent / "examples"
LEGACY_CLS = SCRIPT_DIR.parent / "templates" / "latex" / "resume.cls"


def parse_documentclass(tex_path: Path) -> str:
    """Read the document class name from ``\\documentclass{<name>}``.

    Returns the class name (e.g. ``red_card``) or ``"resume"`` as a fallback.
    The class name determines which ``.cls`` file must sit next to resume.tex.
    """
    try:
        text = tex_path.read_text(encoding="utf-8-sig")
    except OSError:
        return "resume"
    match = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", text)
    if match:
        return match.group(1).strip()
    return "resume"


def locate_cls_source(class_name: str) -> Path | None:
    """Find the source ``<class_name>.cls`` for a template.

    Search order:
    1. examples/<class_name>/latex/<class_name>.cls  (current multi-template layout)
    2. any examples/*/latex/<class_name>.cls          (class name differs from dir)
    3. legacy templates/latex/resume.cls              (only for the old 'resume' class)
    """
    primary = EXAMPLES_DIR / class_name / "latex" / f"{class_name}.cls"
    if primary.is_file():
        return primary
    if EXAMPLES_DIR.is_dir():
        for found in EXAMPLES_DIR.glob(f"*/latex/{class_name}.cls"):
            if found.is_file():
                return found
    if class_name == "resume" and LEGACY_CLS.is_file():
        return LEGACY_CLS
    return None


def ensure_cls(latex_dir: Path, class_name: str) -> None:
    """Ensure ``<class_name>.cls`` exists in the compile directory.

    xelatex resolves ``\\documentclass{<class_name>}`` relative to its working
    directory (``latex_dir``), so the matching ``.cls`` must live there. If it is
    missing we copy it from the template source.
    """
    cls_local = latex_dir / f"{class_name}.cls"
    if cls_local.is_file():
        return
    cls_source = locate_cls_source(class_name)
    if cls_source is not None:
        latex_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cls_source, cls_local)



LATEX_ENGINES = [
    ("xelatex", "xelatex -interaction=nonstopmode -halt-on-error"),
]


def find_latex_engine() -> str | None:
    """Check which LaTeX engines are available on PATH."""
    for name, _ in LATEX_ENGINES:
        if shutil.which(name):
            return name
    return None


def run_xelatex(tex_dir: Path, tex_name: str, output_dir: Path) -> bool:
    """Run xelatex twice (for cross-references) in the given directory."""
    engine = find_latex_engine()
    if not engine:
        return False

    # Build the command
    cmd = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={output_dir}",
        tex_name,
    ]

    for pass_num in (1, 2):
        result = subprocess.run(
            cmd,
            cwd=tex_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            # Print last 30 lines of log for debugging
            log_path = output_dir / f"{Path(tex_name).stem}.log"
            if log_path.is_file():
                log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                critical = [l for l in log_lines if "!" in l and not l.startswith("(")]
                print("LaTeX errors:", file=sys.stderr)
                for l in critical[-15:]:
                    print(f"  {l}", file=sys.stderr)
            return False

    return True


def count_pdf_pages(pdf_path: Path) -> int:
    """Count PDF pages by reading the root Pages object."""
    try:
        import subprocess
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":")[1].strip())
    except Exception:
        pass
    # Fallback: count /Type /Page in raw PDF
    try:
        raw = pdf_path.read_bytes()
        return raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    except Exception:
        return 0


def write_export_report(project_dir: Path, pdf_path: Path, success: bool) -> None:
    """Write check report to checks/export_quality.json."""
    page_count = count_pdf_pages(pdf_path) if success and pdf_path.is_file() else 0
    gates_status = "pass" if success else "fail"
    if success and page_count > 1:
        gates_status = "warn"
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gates": {
            "export": {
                "status": gates_status,
                "pdf": str(pdf_path) if success else "",
                "backend": "xelatex" if success else "none",
                "page_count": page_count,
                "one_page": page_count <= 1,
            }
        },
    }
    if page_count > 1:
        report["gates"]["export"]["note"] = (
            f"Resume is {page_count} pages — target is 1 page. "
            "Consider shortening content or tightening spacing."
        )
    if not success:
        report["gates"]["export"]["note"] = (
            "LaTeX compilation failed. Install TeX Live (recommended) or MiKTeX, "
            "then run xelatex on the .tex file manually."
        )
    report_path = project_dir / "checks" / "export_quality.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_project(project_dir: Path) -> tuple[Path, str]:
    """Compile LaTeX to PDF. Returns (pdf_path, status)."""
    project_dir = project_dir.resolve()
    latex_dir = project_dir / "latex"
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = project_dir / "figures"

    # Ensure resume.tex exists
    tex_path = latex_dir / "resume.tex"
    if not tex_path.is_file():
        # Lazy import: only needed for this fallback path
        sys.path.insert(0, str(SCRIPT_DIR))
        from resume2latex import generate_project  # type: ignore  # noqa: F811
        print("resume.tex not found — generating from resume.md...")
        generate_project(project_dir)
        if not tex_path.is_file():
            raise FileNotFoundError(f"Failed to generate {tex_path}")

    # Ensure the document class file (<class>.cls) sits next to resume.tex.
    # xelatex runs with cwd=latex_dir, so \documentclass{<class>} is resolved
    # there. Multi-template projects use a per-template class name (e.g.
    # red_card.cls), so we parse the actual class from the tex and copy its .cls.
    class_name = parse_documentclass(tex_path)
    ensure_cls(latex_dir, class_name)

    # Compile
    print(f"Compiling LaTeX to PDF (documentclass: {class_name})...")
    success = run_xelatex(latex_dir, "resume.tex", exports_dir)

    pdf_path = exports_dir / "resume.pdf"
    if success and pdf_path.is_file():
        # Check page count
        page_count = count_pdf_pages(pdf_path)
        if page_count > 1:
            print(f"⚠  Resume is {page_count} pages — target is 1 page.  Shorten content or tighten spacing.", file=sys.stderr)
        elif page_count == 0:
            print("⚠  Could not determine PDF page count.", file=sys.stderr)
        else:
            print(f"[OK] Resume fits on {page_count} page.")
        # Clean up auxiliary files
        for ext in (".aux", ".log", ".out", ".fls", ".synctex.gz", ".fdb_latexmk"):
            aux = exports_dir / f"resume{ext}"
            aux.unlink(missing_ok=True)
        write_export_report(project_dir, pdf_path, True)
        return pdf_path, "xelatex"
    else:
        # Copy the .tex file to exports as fallback
        export_tex = exports_dir / "resume.tex"
        shutil.copy2(tex_path, export_tex)
        write_export_report(project_dir, pdf_path, False)
        print(
            "⚠ LaTeX compilation requires TeX Live (install from https://tug.org/texlive/).\n"
            "  The .tex file is available at: " + str(export_tex),
            file=sys.stderr,
        )
        return export_tex, "tex-only"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile LaTeX resume to PDF")
    parser.add_argument("--project", required=True, help="Resume project directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        pdf_path, backend = render_project(Path(args.project).resolve())
        print(f"pdf={pdf_path.resolve()}")
        print(f"pdf_backend={backend}")
        return 0 if backend != "tex-only" else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
