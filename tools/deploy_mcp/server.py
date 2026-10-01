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
def plan_deploy(revision: str, archive_sha256: str, image_id: str) -> dict[str, Any]:
    """Stage a locally published GitHub Release archive for an exact main revision."""

    return _call(
        "plan_deploy",
        revision=revision,
        expected_archive_sha256=archive_sha256,
        expected_image_id=image_id,
    )


@server.tool()
def deploy(plan_id: str, revision: str, archive_sha256: str, image_id: str) -> dict[str, Any]:
    """Promote one prepared release after backup and readiness checks."""

    return _call(
        "deploy",
        plan_id=plan_id,
        revision=revision,
        archive_sha256=archive_sha256,
        image_id=image_id,
    )


@server.tool()
def status() -> dict[str, Any]:
    """Return the active release and last deployment result."""

    return _call("status")


@server.tool()
def rollback(revision: str, image_id: str) -> dict[str, Any]:
    """Roll back to a recorded release bound to its full image ID and compatible schema."""

    return _call("rollback", revision=revision, image_id=image_id)


@server.tool()
def refresh_operator_access(operator_ipv4_cidr: str) -> dict[str, Any]:
    """Refresh only the fixed Signal Ledger operator SSH `/32` through Terraform."""

    return _call("refresh_operator_access", operator_ipv4_cidr=operator_ipv4_cidr)


if __name__ == "__main__":
    server.run(transport="stdio")
