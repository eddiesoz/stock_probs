"""Synchronize native Codex and OpenCode model fields from model-routing.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import cast

JsonObject = dict[str, object]


class RoutingError(ValueError):
    """Raised when the manifest or a native configuration has an unexpected shape."""


def _object(value: object, context: str) -> JsonObject:
    """Return a JSON object after checking its key types."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RoutingError(f"{context} must be an object with string keys")
    return cast(JsonObject, value)


def _exact_keys(value: JsonObject, expected: set[str], context: str) -> None:
    """Reject missing or unexpected keys at a routing boundary."""
    if set(value) != expected:
        raise RoutingError(f"{context} keys must be {sorted(expected)}")


def _string(value: object, context: str) -> str:
    """Return a nonempty, single-line string value."""
    if not isinstance(value, str) or not value or value != value.strip() or "\n" in value:
        raise RoutingError(f"{context} must be a nonempty single-line string")
    return value


def _load_manifest(root: Path) -> tuple[dict[str, dict[str, str]], JsonObject, JsonObject]:
    """Load and validate the canonical model roles and native target mappings."""
    manifest_path = root / "model-routing.json"
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RoutingError(f"cannot read {manifest_path}: {error}") from error

    manifest = _object(raw_manifest, "manifest")
    _exact_keys(manifest, {"schema_version", "roles", "codex", "opencode"}, "manifest")
    if manifest["schema_version"] != 1:
        raise RoutingError("unsupported model-routing.json schema_version")

    raw_roles = _object(manifest["roles"], "roles")
    if not raw_roles:
        raise RoutingError("roles must define at least one routing role")
    roles: dict[str, dict[str, str]] = {}
    for role_name, raw_role in raw_roles.items():
        role = _object(raw_role, f"roles.{role_name}")
        _exact_keys(role, {"model", "reasoning_effort"}, f"roles.{role_name}")
        roles[role_name] = {
            "model": _string(role["model"], f"roles.{role_name}.model"),
            "reasoning_effort": _string(
                role["reasoning_effort"], f"roles.{role_name}.reasoning_effort"
            ),
        }

    codex = _object(manifest["codex"], "codex")
    _exact_keys(codex, {"default_role", "agents"}, "codex")
    opencode = _object(manifest["opencode"], "opencode")
    _exact_keys(opencode, {"builtin_agents", "agents"}, "opencode")
    _validate_role_map(codex["agents"], roles, "codex.agents")
    _validate_role_map(opencode["agents"], roles, "opencode.agents")
    _validate_role_map(opencode["builtin_agents"], roles, "opencode.builtin_agents")
    if codex["default_role"] not in roles:
        raise RoutingError("codex.default_role must name a declared role")
    return roles, codex, opencode


def _validate_role_map(value: object, roles: dict[str, dict[str, str]], context: str) -> None:
    """Check that a target role map references only declared roles."""
    mapping = _object(value, context)
    if not mapping:
        raise RoutingError(f"{context} must not be empty")
    for target, role_name in mapping.items():
        if not isinstance(role_name, str) or role_name not in roles:
            raise RoutingError(f"{context}.{target} must name a declared role")


def _replace_toml_values(text: str, values: dict[str, str], context: str) -> str:
    """Replace exactly one top-level TOML string value per requested key."""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RoutingError(f"{context} is invalid TOML: {error}") from error
    for key, expected in values.items():
        if not isinstance(parsed.get(key), str):
            raise RoutingError(f"{context} must have a top-level {key} string")
        pattern = re.compile(
            rf"(?m)^({re.escape(key)}[ \t]*=[ \t]*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*')"
            rf"([ \t]*(?:#.*)?)$"
        )
        text, count = pattern.subn(
            lambda match, value=expected: f"{match[1]}{json.dumps(value)}{match[2]}", text
        )
        if count != 1:
            raise RoutingError(f"{context} must contain one top-level {key} assignment")
    return text


def _matching_brace(text: str, opening: int) -> int:
    """Find the closing brace for a JSON object, ignoring braces inside strings."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
    raise RoutingError("OpenCode JSON contains an unclosed object")


def _json_object_span(text: str, name: str, start: int, end: int) -> tuple[int, int]:
    """Find one named direct object member inside a bounded JSON object span."""
    pattern = re.compile(rf'"{re.escape(name)}"[ \t]*:[ \t]*\{{')
    matches = list(pattern.finditer(text, start, end))
    if len(matches) != 1:
        raise RoutingError(f"OpenCode JSON must contain one {name} object at this level")
    opening = matches[0].end() - 1
    return opening, _matching_brace(text, opening)


def _replace_json_agent_models(
    text: str,
    mappings: JsonObject,
    roles: dict[str, dict[str, str]],
) -> str:
    """Replace only model string values within OpenCode's built-in agent objects."""
    try:
        parsed = _object(json.loads(text), "opencode.json")
        agents = _object(parsed.get("agents"), "opencode.json.agents")
    except json.JSONDecodeError as error:
        raise RoutingError(f"opencode.json is invalid JSON: {error}") from error
    if set(agents) != set(mappings):
        raise RoutingError("opencode.json agents must match opencode.builtin_agents")

    agents_start, agents_end = _json_object_span(text, "agents", 0, len(text))
    replacements: list[tuple[int, int, str]] = []
    for agent_name, role_name in mappings.items():
        agent = _object(agents[agent_name], f"opencode.json.agents.{agent_name}")
        if not isinstance(agent.get("model"), str):
            raise RoutingError(f"opencode.json.agents.{agent_name}.model must be a string")
        object_start, object_end = _json_object_span(text, agent_name, agents_start, agents_end)
        object_text = text[object_start : object_end + 1]
        model_pattern = re.compile(r'("model"[ \t]*:[ \t]*)((?:"(?:\\.|[^"\\])*")+)')
        matches = list(model_pattern.finditer(object_text))
        if len(matches) != 1:
            raise RoutingError(f"OpenCode agent {agent_name} must contain one model string")
        role = roles[cast(str, role_name)]
        replacement = json.dumps(f"openai/{role['model']}#{role['reasoning_effort']}")
        match = matches[0]
        start = object_start + match.start(2)
        end = object_start + match.end(2)
        replacements.append((start, end, replacement))

    for start, end, replacement in sorted(replacements, reverse=True):
        text = f"{text[:start]}{replacement}{text[end:]}"
    return text


def _replace_profile_model(text: str, model_spec: str, context: str) -> str:
    """Replace the single model field in a profile's YAML frontmatter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise RoutingError(f"{context} must begin with YAML frontmatter")
    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if closing is None:
        raise RoutingError(f"{context} has unclosed YAML frontmatter")
    frontmatter = "".join(lines[1:closing])
    pattern = re.compile(r"(?m)^(model:[ \t]*)(\S+)([ \t]*)(\r?)$")
    frontmatter, count = pattern.subn(
        lambda match: f"{match[1]}{model_spec}{match[3]}{match[4]}", frontmatter
    )
    if count != 1:
        raise RoutingError(f"{context} must have one simple model frontmatter field")
    return f"{lines[0]}{frontmatter}{''.join(lines[closing:])}"


def _read_text(path: Path) -> str:
    """Read UTF-8 text without normalizing existing newline sequences."""
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def projected_files(root: Path) -> dict[Path, str]:
    """Build expected model-only projections for every active native config."""
    roles, codex, opencode = _load_manifest(root)
    codex_agents = _object(codex["agents"], "codex.agents")
    opencode_agents = _object(opencode["agents"], "opencode.agents")
    builtin_agents = _object(opencode["builtin_agents"], "opencode.builtin_agents")
    if set(codex_agents) != set(opencode_agents):
        raise RoutingError("Codex and OpenCode profile maps must name the same workers")

    projections: dict[Path, str] = {}
    project_config = root / ".codex/config.toml"
    default_role = roles[cast(str, codex["default_role"])]
    projections[project_config] = _replace_toml_values(
        _read_text(project_config),
        {
            "model": default_role["model"],
            "model_reasoning_effort": default_role["reasoning_effort"],
        },
        str(project_config),
    )

    _require_profile_set(root / ".codex/agents", codex_agents, ".codex/agents")
    for profile_name, role_name in codex_agents.items():
        profile = root / ".codex/agents" / f"{profile_name}.toml"
        role = roles[cast(str, role_name)]
        projections[profile] = _replace_toml_values(
            _read_text(profile),
            {"model": role["model"], "model_reasoning_effort": role["reasoning_effort"]},
            str(profile),
        )

    _require_profile_set(root / ".opencode/agents", opencode_agents, ".opencode/agents")
    for profile_name, role_name in opencode_agents.items():
        profile = root / ".opencode/agents" / f"{profile_name}.md"
        role = roles[cast(str, role_name)]
        model_spec = f"openai/{role['model']}#{role['reasoning_effort']}"
        projections[profile] = _replace_profile_model(_read_text(profile), model_spec, str(profile))

    open_config = root / "opencode.json"
    projections[open_config] = _replace_json_agent_models(
        _read_text(open_config), builtin_agents, roles
    )
    return projections


def _require_profile_set(directory: Path, mappings: JsonObject, context: str) -> None:
    """Fail when the active profile files differ from the manifest's target set."""
    suffix = ".toml" if context == ".codex/agents" else ".md"
    actual = {path.stem for path in directory.glob(f"*{suffix}")}
    if actual != set(mappings):
        raise RoutingError(f"{context} profiles must match the manifest target names")


def sync_projection(root: Path, *, write: bool) -> list[str]:
    """Check projection drift or update only the model fields that differ."""
    projections = projected_files(root)
    changed: list[str] = []
    for path, expected in projections.items():
        current = _read_text(path)
        if current == expected:
            continue
        changed.append(path.relative_to(root).as_posix())
        if write:
            with path.open("w", encoding="utf-8", newline="") as stream:
                stream.write(expected)
    return changed


def main(argv: list[str] | None = None) -> int:
    """Run the explicit model-routing check or projection update command."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail if native model fields drift")
    mode.add_argument(
        "--write",
        action="store_true",
        help="sync native model fields from the manifest",
    )
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        changed = sync_projection(root, write=arguments.write)
    except (OSError, RoutingError, tomllib.TOMLDecodeError) as error:
        print(f"model-routing error: {error}", file=sys.stderr)
        return 2

    if arguments.check and changed:
        print(f"model-routing drift: {', '.join(changed)}", file=sys.stderr)
        return 1
    if changed:
        action = "updated" if arguments.write else "drift-free"
        print(f"model routing {action}: {', '.join(changed)}")
    else:
        print("model-routing projections already match the manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
