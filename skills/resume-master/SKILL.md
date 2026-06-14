---
name: resume-master
description: >
  AI-driven LaTeX resume generation system. Converts source documents
  (PDF/DOCX/TXT/URL/image) into a targeted Markdown resume, then generates
  LaTeX source and compiles to PDF.
---

# Resume Master Skill

Resume Master keeps Markdown as the canonical editable resume and generates
LaTeX → PDF as the final output.

**Core Pipeline**: `Source Material → Project Init → Profile/JD Analysis →
Strategy + spec_lock.json → resume.md → resume.tex → PDF`

## Global Execution Rules

1. **Serial pipeline**: each step consumes the previous step's artifacts.
2. **Read sources before writing**: before writing resume content, read all Markdown files in `sources/`.
3. **Markdown stays canonical**: preserve `drafts/resume.md` as the editable text resume.
4. **Spec lock is JSON**: writer and renderer use `strategy/spec_lock.json` as the machine contract.
5. **LaTeX is auto-generated**: never edit `latex/resume.tex` directly; regenerate from `resume.md`.

## Main Scripts

| Script | Purpose |
| --- | --- |
| `${SKILL_DIR}/scripts/source2md/pdf2md.py` | PDF to Markdown |
| `${SKILL_DIR}/scripts/source2md/doc2md.py` | DOCX / Office / EPUB / HTML to Markdown |
| `${SKILL_DIR}/scripts/source2md/excel2md.py` | Excel to Markdown |
| `${SKILL_DIR}/scripts/source2md/ppt2md.py` | PowerPoint to Markdown |
| `${SKILL_DIR}/scripts/source2md/web2md.py` | Web page / URL to Markdown |
| `${SKILL_DIR}/scripts/job_manager.py` | Add or fetch JD material |
| `${SKILL_DIR}/scripts/source_to_profile/llm_normalize_profile.py` | Normalize profile markdown to `profile.json` |
| `${SKILL_DIR}/scripts/strategy/strategy_defaults.py` | Create `resume_strategy.md` and `spec_lock.json` |
| `${SKILL_DIR}/scripts/render_pdf.py` | Compile `latex/resume.tex` → `exports/resume.pdf` |

## Template Resources

| Resource | Path |
| --- | --- |
| LaTeX document class | `${SKILL_DIR}/templates/latex/resume.cls` |
| Figures store | `${SKILL_DIR}/templates/latex/figures/` |

## Knowledge Base

`${SKILL_DIR}/references/knowledge/` holds resume-writing methodology, role/scenario
guides, ATS keyword strategy, interview prep, and before/after examples. See
`references/knowledge/INDEX.md` for the catalog. Consult it during JD analysis,
strategy, drafting, and ATS optimization to inform **wording, structure, and keyword
coverage** — never as a source of candidate facts. Resume content still comes only
from `profile.json`.

## Workflow

### Step 1: Source Processing

Gate: user has provided resume source material, JD material, or both.

Convert non-Markdown sources when needed:

| User Provides | Command |
| --- | --- |
| PDF | `python ${SKILL_DIR}/scripts/source2md/pdf2md.py <file> -o <file>.md` |
| DOCX / Office / HTML | `python ${SKILL_DIR}/scripts/source2md/doc2md.py <file> -o <file>.md` |
| Excel | `python ${SKILL_DIR}/scripts/source2md/excel2md.py <file> -o <file>.md` |
| PPTX | `python ${SKILL_DIR}/scripts/source2md/ppt2md.py <file> -o <file>.md` |
| URL | `python ${SKILL_DIR}/scripts/source2md/web2md.py <URL> -o <name>.md` |
| Markdown / pasted text | Read directly |

### Step 2: Project Initialization

```bash
python ${SKILL_DIR}/scripts/project_manager.py init <project_name>
python ${SKILL_DIR}/scripts/project_manager.py import-sources <project_path> <source_files...> --copy
```

Project structure:

```text
<project_path>/
  sources/
  profile/
  jd/
  strategy/
  drafts/
  checks/
  figures/
  latex/
  exports/
```

### Step 3: Content Analysis

Read all files in `sources/` and write:

- `profile/profile.md`
- `profile/profile.json` when structured facts are available
- `jd/jd_raw.md` if a JD exists
- `jd/jd_analysis.md` if a JD exists

Helper commands:

```bash
python ${SKILL_DIR}/scripts/source_to_profile/llm_normalize_profile.py --profile-md <project_path>/profile/profile.md
python ${SKILL_DIR}/scripts/job_manager.py add-text --project <project_path> --company "<company>" --role "<role>" --text "<jd text>"
python ${SKILL_DIR}/scripts/jd_tools/jd_defaults.py --project <project_path>
```

### Step 4: Strategy And Spec Lock

Create the strategy and machine lock:

```bash
python ${SKILL_DIR}/scripts/strategy/strategy_defaults.py --project <project_path>
```

Required outputs:

- `strategy/resume_strategy.md`
- `strategy/spec_lock.json`

`spec_lock.json` must include at least:

- `target_role`
- `section_order`

### Step 5: Resume Content

Write or build the text resume:

```bash
python ${SKILL_DIR}/scripts/generation/resume_builder.py --project <project_path>
```

Outputs:

- `drafts/resume.md`
- `drafts/resume_semantic.md`
- `exports/resume.md`

Rules:

- Only use facts present in source material.
- Keep bullets concise and role-relevant.
- Preserve `resume.md` as the editable artifact.
- Do not make layout decisions in this stage.

### Step 6: LaTeX Generation

Convert the Markdown resume to LaTeX:

```bash
# Basic usage:
python ${SKILL_DIR}/scripts/resume2latex.py --project <project_path>

# With a person photo:
python ${SKILL_DIR}/scripts/resume2latex.py --project <project_path> --photo person/photo.jpg
```

The script:

1. Parses `drafts/resume.md` into a structured data model
2. Copies the provided photo to `figures/photo.*`
3. Generates `latex/resume.tex` using the resume document class
4. Copies `resume.cls` to the `latex/` directory for self-contained compilation

Outputs:

- `latex/resume.tex`
- `figures/photo.*` (if photo provided)
- `latex/resume.cls`

### Step 7: PDF Export

Compile the LaTeX source to PDF:

```bash
python ${SKILL_DIR}/scripts/render_pdf.py --project <project_path>
```

PDF backend:

1. **xelatex** (primary) — requires TeX Live or MiKTeX installed on the system. Supports Chinese via the `ctex` package. The script runs xelatex twice for cross-reference resolution.
2. **tex-only** (fallback) — if no LaTeX engine is found, the .tex file is copied to `exports/` with instructions for manual compilation.

Outputs:

- `exports/resume.pdf` (if compilation succeeds)
- `exports/resume.tex` (fallback for manual compilation)
- `checks/export_quality.json`

## End-To-End Demo

```bash
python ${SKILL_DIR}/scripts/pipeline.py \
  --person-dir person \
  --projects-dir projects \
  --company "<company>" \
  --role "<role>" \
  --jd-text "<jd text>"
```

The demo prints the project path and all generated artifacts.

## Notes

- Install TeX Live (https://tug.org/texlive/) for LaTeX → PDF compilation on Windows.
- The resume.cls uses the `ctex` package for Chinese typesetting. Ensure your TeX distribution includes it (TeX Live does by default).
- Multi-JD mode remains content-first: create per-job folders, write per-job `jd_analysis.md`, `resume_strategy.md`, `spec_lock.json`, then run the same generation commands inside each job folder.
