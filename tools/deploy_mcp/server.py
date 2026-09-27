"""Run Signal Ledger's private stdio deployment MCP server."""

from __future__ import annotations

from typing import Any

from controller import DeployConfig, DeployController, DeployError
from mcp.server import MCPServer

server = MCPServer("signal-ledger-deploy")


def _call(operation: str, **arguments: str) -> dict[str, Any]:
    """Turn operational failures into bounded, credential-free tool responses."""

    try:
        controller = DeployController(DeployConfig.from_env())
        method = getattr(controller, operation)
        return method(**arguments)
    except DeployError as exc:
        return {"status": "error", "code": exc.code}


@server.tool()
def inspect() -> dict[str, Any]:
    """Inspect the configured Signal Ledger production target without changing it."""

    return _call("inspect")


@server.tool()
def plan_deploy(revision: str, expected_image_digest: str) -> dict[str, Any]:
    """Pull and stage a published digest for an exact main revision."""

    return _call(
        "plan_deploy",
        revision=revision,
        expected_image_digest=expected_image_digest,
    )


@server.tool()
def deploy(plan_id: str, revision: str, image_digest: str) -> dict[str, Any]:
    """Promote one prepared release after backup and readiness checks."""

    return _call("deploy", plan_id=plan_id, revision=revision, image_digest=image_digest)


@server.tool()
def status() -> dict[str, Any]:
    """Return the active release and last deployment result."""

    return _call("status")


@server.tool()
def rollback(revision: str) -> dict[str, Any]:
    """Roll back to a recorded release only when the database schema is compatible."""

    return _call("rollback", revision=revision)


if __name__ == "__main__":
    server.run(transport="stdio")
