# MCP Tool Parity

Every REST API resource should have a corresponding MCP tool, and vice versa.

## Mapping

| REST Endpoint | MCP Tool | Status |
|--------------|----------|--------|
| GET/POST /skills | skill_list / skill_create | ✅ |
| GET/PUT/DELETE /skills/:name | skill_load / skill_update / skill_delete | ✅ |
| POST /skills/:name/sync | skill_sync | ✅ |
| PATCH /skills/:name/enable\|disable | skill_enable / skill_disable | ✅ |
| GET/POST /observations | observation_list / observation_store | ✅ |
| PATCH /observations/:id | (via observation_list + observe) | 🟡 |
| GET /observations/search | observation_search | ✅ |

## Rule

When adding a new API route, always add a corresponding MCP tool in `ingenium-server/lib/tools/`.
When adding a new MCP tool, ensure the API route exists for it to call.
