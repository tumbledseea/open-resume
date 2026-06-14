# Resume Strategist

The Strategist decides what the resume should emphasize before any resume draft or layout fill is produced.

## Inputs

- `profile/profile.md`
- `profile/profile.json` when available
- `jd/jd_analysis.md` when available
- selected layout under `templates/layouts/`
- selected layout `design_spec.md`

## Outputs

- `strategy/resume_strategy.md`
- `strategy/spec_lock.json`

## Strategy Requirements

`resume_strategy.md` must include:

1. Candidate positioning
2. Resume mode: `general` or `targeted`
3. Target language
4. Selected layout
5. Section order
6. Strength priorities
7. Content to include
8. Content to omit or downplay
9. Claims requiring user confirmation
10. Quality gates before export

`spec_lock.json` is the machine-readable contract. It must be specific enough that the writer and renderer can operate without changing strategy mid-flow.

Required `spec_lock.json` fields:

```json
{
  "language": "zh-CN",
  "mode": "targeted",
  "resume_type": "visual_svg",
  "layout": "橙色背景简历",
  "template_svg": "templates/layouts/橙色背景简历/template.svg",
  "design_spec": "templates/layouts/橙色背景简历/design_spec.md",
  "page_limit": 1,
  "canvas": {},
  "safe_area": {},
  "font_roles": {},
  "section_order": [],
  "max_lines_per_section": {},
  "placeholder_policy": {},
  "overflow_policy": {},
  "quality_gates": []
}
```
