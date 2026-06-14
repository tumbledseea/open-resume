# Template8 Layout Notes

## Visual Style

深紫 #4A2580 顶部条，浅紫背景 #F8F5FF，白色卡片，节标题紫色竖线 #7B42CC。

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
Jinja2 entry: `latex/main.tex.j2`. Document class: `template8.cls`.
