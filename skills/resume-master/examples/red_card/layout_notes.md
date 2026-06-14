# Template1 Layout Notes

Template1 is decomposed from `skills/resume-master/examples/半成品.pdf`.

## Visual Structure

- Page: one A4 portrait page.
- Background: light blue-gray full-page background.
- Top bar: solid red horizontal band at the top edge.
- Header: name and contact line at upper left; optional photo area at upper right.
- Sections: red circular marker, red title, horizontal rule.
- Content: white rounded cards with a subtle border.

## Module Mapping

| Module | Source PDF role | Template fields |
| --- | --- | --- |
| `header` | Name, phone, email, city, optional photo | `name`, `phone`, `email`, `location`, `website`, `photo` |
| `education` | 教育经历 | `school`, `badges`, `time`, `major`, `degree`, `college`, `study_type`, `location`, `details` |
| `experience` | 实习/工作经历 | `organization`, `time`, `role`, `project`, `bullets[{label,text}]` |
| `projects` | 项目经历 | `name`, `role`, `time`, `bullets` |
| `awards` | 荣誉奖项/证书 | `name`, `time` |

## Renderer Contract

The renderer must consume `resume_modules.json` and produce LaTeX without calling an LLM. Agent-side intent recognition and module extraction should happen before this renderer is invoked.
