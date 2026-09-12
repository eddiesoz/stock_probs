---
title: "Documentation authoring rules"
impact: HIGH
impactDescription: "Keeps Stock Probability guides discoverable, concise, accessible, and linked without duplicating canonical prose."
tags: [markdown, taxonomy, frontmatter, links]
---

## Documentation authoring rules

### Placement

Select one existing category: `concepts`, `configure`, `develop`, `operations`, `reference`,
`security`, or `usage`. Add a category only for a demonstrated set of topics, never for empty
symmetry. A topic page covers one user intent; split unrelated procedures rather than adding a
catch-all guide.

Topic names use `^[a-z0-9]+(?:-[a-z0-9]+)*\.md$`. `index.md` is reserved for navigation.
Every page starts with exactly this minimal frontmatter shape:

```markdown
---
title: "Short human-readable title"
description: "One sentence that distinguishes the page in search and navigation."
---
```

### Content

- Start with the user's goal or the concept, not milestone history.
- Prefer commands and field tables that match the current source.
- Explain safety constraints near the operation they constrain.
- Use descriptive link labels; avoid “click here”.
- Preserve exact API field/path spelling and application terminology.
- Do not copy long root evidence records into guides or duplicate paragraphs between topics.
- Do not create empty “prerequisites”, “evidence”, or “limitations” headings when prose does not
  require them.

### Navigation

Use relative links. A category index links every direct topic exactly once, and
`docs/index.md` links every category index. Topic pages link only genuinely related material;
there is no requirement to create symmetric “next/previous” links.

When root status text must change, state only facts established in the current task: paths
created, pre-change revision observed, checks run, and independent/post-change checkpoint state.
Do not rewrite unrelated milestone evidence.
