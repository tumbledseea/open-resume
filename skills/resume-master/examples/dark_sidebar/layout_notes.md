# Template6 Layout Notes

## Visual Style

深灰 #2C2C2C 左边栏（30%宽）+ 金色 #E8B84B 点缀，右侧浅色内容区，双栏布局。

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
Jinja2 entry: `latex/main.tex.j2`. Document class: `template6.cls`.
