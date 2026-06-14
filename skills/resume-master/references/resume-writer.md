# Resume Writer

Write the semantic resume from `profile/profile.json`, source Markdown, JD analysis, and `strategy/spec_lock.json`.

## Inputs

- `profile/profile.md`
- `profile/profile.json` when available
- `jd/jd_analysis.md` when available
- `strategy/resume_strategy.md`
- `strategy/spec_lock.json`

## Outputs

- `drafts/resume.md`
- `drafts/resume_semantic.md`
- `exports/resume.md`

## Rules

- Keep `resume.md` as the canonical editable artifact.
- Use the selected template as layout structure only; do not put filler text into the resume.
- Keep bullets concise and specific.
- Prefer action + method/tool + result.
- Prioritize JD keywords when a JD exists.
- Omit low-value empty sections instead of writing placeholder-heavy content.
- Do not invent metrics, awards, technologies, company names, or scope.
- If a claim requires confirmation, list it in `strategy/resume_strategy.md` and keep the resume conservative.

## Stage Boundary

The writer only produces Markdown. It must not decide SVG coordinates, font sizes, PDF export details, or visual overflow behavior. Those belong to:

```bash
python scripts/resume2svg.py --project <project_path>
python scripts/finalize_resume.py --project <project_path>
python scripts/render_pdf.py --project <project_path> --keep-html
```

## Bullet Example

Supported:

```text
使用 Python 解析 Markdown 简历内容，并填充 SVG 模板占位符，生成可导出的视觉简历。
```

Risky unless source evidence exists:

```text
主导企业级 AI 招聘平台建设，将招聘效率提升 80%。
```
