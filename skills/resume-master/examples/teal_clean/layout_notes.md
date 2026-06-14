# Template3 Layout Notes

## Visual Structure

- Page: one A4 portrait, near-white background (`#FAFAFA`).
- Top bar: solid dark teal (`#2A7F6F`) horizontal stripe, 3.2mm tall.
- Header: name (large, dark) + contact line left; photo placeholder right; teal underline rule.
- Section title: solid teal rectangle block on left + bold teal text + light teal rule extending right.
- Content: white rounded-corner cards with teal-tinted border.
- Accent: teal `#2A7F6F` — times, badges, bullets, section titles.

## Module Mapping

| Module | Fields |
|---|---|
| `header` | `name`, `contact_line`, `photo` |
| `education` | `school`, `badges`, `time`, `major`, `degree`, `college`, `study_type`, `location`, `details` |
| `experience` | `organization`, `time`, `role`, `project`, `bullets[{label,text}]` |
| `projects` | `name`, `role`, `time`, `bullets` |
| `awards` | `name`, `time` |

## Renderer Contract

Same `resume_modules.json` schema as template1.
Jinja2 entry: `latex/main.tex.j2`. Document class: `template3.cls`.
