# Template7 Layout Notes

## Visual Style

蓝灰 #3A5075 顶部条，浅蓝灰背景 #F4F7FB，白色卡片，节标题蓝色竖线。

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
Jinja2 entry: `latex/main.tex.j2`. Document class: `template7.cls`.
