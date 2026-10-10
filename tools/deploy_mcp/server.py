"""Run Signal Ledger's private stdio deployment MCP server."""

from __future__ import annotations

from typing import Any, Literal

from controller import DeployConfig, DeployController, DeployError
from mcp.server import MCPServer
from pr_rehearsal import RehearsalError
from pr_rehearsal import rehearse_pr_pair as run_pr_pair_rehearsal

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
def plan_deploy(
    revision: str,
    archive_sha256: str,
    image_id: str,
    pair_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Stage a release; schema-13 deployments also require the verified recovery-pair hash."""

    arguments = {
        "revision": revision,
        "expected_archive_sha256": archive_sha256,
        "expected_image_id": image_id,
    }
    if pair_manifest_sha256 is not None:
        arguments["expected_pair_manifest_sha256"] = pair_manifest_sha256
    return _call("plan_deploy", **arguments)


@server.tool()
def deploy(
    plan_id: str,
    revision: str,
    archive_sha256: str,
    image_id: str,
    pair_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Promote one prepared image bound to its exact recovery-pair manifest, when required."""

    arguments = {
        "plan_id": plan_id,
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
    }
    if pair_manifest_sha256 is not None:
        arguments["pair_manifest_sha256"] = pair_manifest_sha256
    return _call("deploy", **arguments)


@server.tool()
def status() -> dict[str, Any]:
    """Return the active release and last deployment result."""

    return _call("status")


@server.tool()
def rollback(revision: str, image_id: str) -> dict[str, Any]:
    """Roll back to a recorded release bound to its full image ID and compatible schema."""

    return _call("rollback", revision=revision, image_id=image_id)


@server.tool()
def set_assistant_rollout(
    mode: Literal["disabled", "owner_canary", "invited"],
) -> dict[str, Any]:
    """Enable the current reviewed assistant release for owner canary or invited users."""

    return _call("set_assistant_rollout", mode=mode)


@server.tool()
def refresh_operator_access(operator_ipv4_cidr: str) -> dict[str, Any]:
    """Refresh only the fixed Signal Ledger operator SSH `/32` through Terraform."""

    return _call("refresh_operator_access", operator_ipv4_cidr=operator_ipv4_cidr)


@server.tool()
def rehearse_pr_pair(
    reviewed_head_sha: str,
    candidate_image_id: str,
    candidate_source_context_sha256: str,
    recovery_image_id: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
    pair_manifest_sha256: str,
) -> dict[str, Any]:
    """Run the fixed PR #2 candidate and recovery pair in the isolated host rehearsal slot."""

    try:
        return run_pr_pair_rehearsal(
            reviewed_head_sha=reviewed_head_sha,
            candidate_image_id=candidate_image_id,
            candidate_source_context_sha256=candidate_source_context_sha256,
            recovery_image_id=recovery_image_id,
            recovery_source_context_sha256=recovery_source_context_sha256,
            recovery_overlay_sha256=recovery_overlay_sha256,
            pair_manifest_sha256=pair_manifest_sha256,
        )
    except RehearsalError as exc:
        response: dict[str, Any] = {"status": "error", "code": exc.code}
        if exc.details:
            response.update(exc.details)
        return response


if __name__ == "__main__":
    server.run(transport="stdio")
