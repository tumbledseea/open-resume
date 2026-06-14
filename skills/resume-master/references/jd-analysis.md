# JD Analysis

Use this when a target role, company, job URL, or job description is available.

Create `jd/jd_analysis.json`:

```json
{
  "company": "",
  "role": "",
  "mode": "targeted",
  "hard_requirements": [],
  "preferred_requirements": [],
  "keywords": [],
  "tools_and_technologies": [],
  "business_domain": [],
  "resume_implications": [],
  "risks_or_gaps": []
}
```

Prefer explicit JD wording over inference. If job collection only produces partial content, fill unknown fields with `XX` and continue.
