# getProjectDetail Pattern

## Purpose
Provide a single endpoint that returns all project-related data for a dashboard view.

## Endpoint
- `GET /api/projects/:id/detail`

## Response Structure
```json
{
  "metadata": { ... },
  "skills": [...],
  "observations": [...],
  "pipeline_events": [...],
  "synthesis_status": "..."
}
```

## Benefits
- Reduces number of API calls from 5+ to 1
- Simplifies frontend state management
- Consistent data snapshot for the view