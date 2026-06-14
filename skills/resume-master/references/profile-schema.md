# Profile Schema

Create `profile/profile.json` with this top-level shape:

```json
{
  "basic_info": {
    "name": "",
    "email": "",
    "phone": "",
    "location": "",
    "target_direction": "",
    "links": []
  },
  "education": [],
  "skills": [],
  "projects": [],
  "internships": [],
  "awards": [],
  "certifications": [],
  "publications": [],
  "other_experiences": [],
  "needs_user_confirmation": []
}
```

## Rules

- Preserve source facts when available.
- Fill missing or blank fields with `XX`; do not stop the workflow because the user provided partial information.
- Keep dates as user-provided strings.
- Project and internship items should include `name`, `role`, `time`, `description`, `technologies`, `actions`, and `results` when available.
- Skills may be strings or grouped objects; keep the source wording if uncertain.
