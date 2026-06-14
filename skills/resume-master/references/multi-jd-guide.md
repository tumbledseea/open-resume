# Multi-JD Guide

Use this when the raw JD content contains multiple job postings that need individually targeted resumes.

## Workflow Summary

1. Read `<project>/jd/jd_raw.md`.
2. Use LLM understanding to identify each distinct job posting.
3. Create a per-job subdirectory under `<project>/jobs/`.
4. Write per-job JD analysis, strategy, `spec_lock.json`, and resume.
5. Run the same Markdown -> SVG -> finalize -> HTML/PDF pipeline for each job.

## Per-Job Analysis JSON Schema

For each job posting, write `jobs/<job_dir>/jd/jd_analysis.md` with a fenced JSON block:

```json
{
  "company": "",
  "role": "",
  "mode": "targeted",
  "hard_requirements": [],
  "preferred_requirements": [],
  "keywords": [],
  "tools_and_technologies": [],
  "business_domain": [],
  "resume_implications": [],
  "risks_or_gaps": []
}
```

## Per-Job Directory Structure

Create each job directory:

```bash
python ${SKILL_DIR}/scripts/project_manager.py init-job <project_path> \
  --company "<Company>" --role "<Role>"
```

This creates:

```text
jobs/job_001_Company_Role/
  jd/
  strategy/
  drafts/
  exports/
```

## Per-Job Strategy

For each job, write:

- `jd/jd_raw.md`
- `jd/jd_analysis.md`
- `strategy/resume_strategy.md`
- `strategy/spec_lock.json`

`strategy/spec_lock.json` should select the layout, section order, page limit, placeholder policy, overflow policy, and quality gates for this job.

## Per-Job Resume And Export

Inside each job directory:

```bash
python ${SKILL_DIR}/scripts/generation/resume_builder.py --project <job_dir>
python ${SKILL_DIR}/scripts/resume2svg.py --project <job_dir>
python ${SKILL_DIR}/scripts/finalize_resume.py --project <job_dir>
python ${SKILL_DIR}/scripts/render_pdf.py --project <job_dir> --keep-html
```

## Quality Checks

- Each resume targets its specific job.
- No two resumes are identical unless the jobs have identical requirements.
- Keywords from each JD analysis appear in the corresponding resume.
- Truthfulness rules are followed per [truthfulness-rules.md](truthfulness-rules.md).
- Layout gates pass per `checks/layout_quality.json`.
