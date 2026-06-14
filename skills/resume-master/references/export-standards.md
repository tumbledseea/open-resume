# Export Standards

Resume Master is Markdown-first and layout-capable.

## Required Outputs

- `exports/resume.md`
- `svg_output/resume.svg`
- `svg_final/resume.svg`
- `exports/resume.html`
- `exports/resume.pdf`
- `checks/layout_quality.json`
- `checks/export_quality.json`

## Markdown Rules

- Use standard headings.
- Use `- ` bullets.
- Avoid tables for ATS compatibility.
- Keep source Markdown as the canonical editable artifact.

## SVG Rules

- Fill `template.svg` from `drafts/resume_semantic.md`.
- Do not leave `{PLACEHOLDER}` or `{{PLACEHOLDER}}` tokens in final SVG.
- Keep external resources local or embedded.
- Avoid `rgba()` in final SVG; use hex colors and opacity fields.

## HTML/PDF Rules

- `exports/resume.html` should contain inline SVG so it can be opened locally.
- `exports/resume.pdf` must be a valid PDF file.
- If a direct SVG-to-PDF backend is unavailable, the exporter may write a minimal valid PDF and keep the complete visual export in HTML.
