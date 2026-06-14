# Template2 Layout Notes

## Visual Structure

- Layout: **two-column** — left 30% navy sidebar, right 70% white content.
- Sidebar: dark navy (`#1B2A4A`) — photo placeholder, name, contact, skills, education, awards.
- Right main: light gray background (`#F7F9FC`) — white rounded cards per section.
- Accent color: medium blue (`#3D7DBF`) for section titles, entry times, bullet markers.

## Module Placement

| Module | Column | Notes |
|---|---|---|
| `header` | Left sidebar top | Name, contact, photo |
| `skills` | Left sidebar | Skill list |
| `education` | Left sidebar | School, degree, major, time |
| `awards` | Left sidebar | Award name + time |
| `experience` | Right main | Organization, role, time, bullets |
| `projects` | Right main | Project name, role, time, bullets |

## Renderer Contract

Same `resume_modules.json` schema as template1. The sidebar modules (education, awards, skills) are rendered inline in the Jinja2 template; main content (experience, projects) follows `module_order`.
