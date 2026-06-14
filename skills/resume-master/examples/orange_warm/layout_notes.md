# Template5 Layout Notes

## Visual Style

橙色 #D45B1A 顶部条，暖米色背景 #FFF4EE，卡片白色圆角，节标题左侧橙色竖线。

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
Jinja2 entry: `latex/main.tex.j2`. Document class: `template5.cls`.
