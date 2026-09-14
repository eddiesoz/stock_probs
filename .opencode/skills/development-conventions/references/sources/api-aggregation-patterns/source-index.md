---
name: api-aggregation-patterns
description: "Patterns for designing aggregated API endpoints that combine multiple data sources into a single response for dashboard views."
---

---
name: api-aggregation-patterns
description: "Patterns for designing aggregated API endpoints that combine multiple data sources into a single response for dashboard views."
created: 2026-07-11T19:01:12.550Z
---

# API Aggregation Patterns

## 🔴 HARD RULEs
- When a dashboard view requires multiple data sources (project metadata, skills, observations, pipeline events, synthesis status), use a dedicated aggregation endpoint (e.g., getProjectDetail) rather than multiple separate API calls.
- Aggregation endpoints should return a single JSON response containing all necessary nested data.

## Description
The `getProjectDetail` pattern is the preferred approach for aggregating project information in a single API call. It reduces client-side complexity and network overhead.

## Reference Files

| File | Content |
|------|--------|
| [`references/getProjectDetail-pattern.md`](references/getProjectDetail-pattern.md) | Detailed specification of the getProjectDetail aggregation pattern |