"""Run one real OpenCode V2 Exa search with a synthetic local model and public query.

This opt-in probe never reads ambient credentials, creates accounts, or invokes TinyFish. The
native model transport is a deterministic loopback fixture; only OpenCode's configured Exa
websearch implementation makes its own public search request after the exact permission bridge
approves the synthetic query.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
from native_assistant_probe import (
    _binary,
    _mcp_handler,
    _ProviderHandler,
    _run_native_search_probe,
)

from stock_probs.container_supervisor import _fixed_location_config


def _search_probe_passes(search: Mapping[str, object]) -> bool:
    """Require terminal native search, nonempty result bytes, and safe unverified links."""

    if search.get("status") != "native_search_completed":
        return False
    if search.get("terminal_outcome") != "succeeded":
        return False
    evidence = search.get("search_result")
    if not isinstance(evidence, Mapping):
        return False
    links = evidence.get("unverified_links")
    model_calls = search.get("synthetic_model_calls")
    return (
        evidence.get("native_provider") == "exa"
        and evidence.get("record_boundary") == "unstructured_text"
        and search.get("synthetic_continuation_observed") is True
        and search.get("synthetic_model_answer_nonempty") is True
        and type(search.get("synthetic_model_answer_bytes")) is int
        and search.get("synthetic_model_answer_bytes", 0) > 0
        and isinstance(model_calls, list)
        and len(model_calls) >= 2
        and all(
            isinstance(call, Mapping)
            and call.get("model") == "assistant-selected"
            and call.get("store") is False
            and call.get("stream") is True
            for call in model_calls
        )
        and evidence.get("tool_status") in {"completed", "success"}
        and type(evidence.get("result_bytes")) is int
        and evidence.get("result_bytes", 0) > 0
        and evidence.get("nonempty_result") is True
        and type(evidence.get("unverified_link_count")) is int
        and evidence.get("unverified_link_count", 0) > 0
        and isinstance(links, list | tuple)
        and all(
            isinstance(link, Mapping)
            and link.get("source_type") == "native_search_text_unverified"
            and str(link.get("title", "")).startswith(
                "Unverified link from native Exa search text at "
            )
            for link in links
        )
    )


def main() -> int:
    """Run the bounded probe and emit only sanitized search protocol metadata."""

    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    process: subprocess.Popen[bytes] | None = None
    servers: list[ThreadingHTTPServer] = []
    threads: list[threading.Thread] = []
    try:
        with tempfile.TemporaryDirectory(prefix="r120-native-exa-") as temporary:
            root = Path(temporary)
            home, location = root / "home", root / "location"
            for path in (home / "config", home / "data", home / "cache", home / "tmp", location):
                path.mkdir(parents=True, mode=0o700)
            mcp = ThreadingHTTPServer(("127.0.0.1", 0), _mcp_handler("synthetic-exa-mcp"))
            provider = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
            servers = [mcp, provider]
            for server in servers:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                threads.append(thread)
            config = _fixed_location_config(
                proxy_base_url=f"http://127.0.0.1:{provider.server_port}/v1",
                proxy_capability="synthetic-provider-capability",
                mcp_url=f"http://127.0.0.1:{mcp.server_port}/mcp",
                mcp_capability="synthetic-mcp-capability",
            )
            (location / "opencode.json").write_text(
                json.dumps(config, separators=(",", ":")), encoding="utf-8"
            )
            password = secrets.token_urlsafe(36)
            environment = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "XDG_CACHE_HOME": str(home / "cache"),
                "TMPDIR": str(home / "tmp"),
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": password,
                "SYNTHETIC_PROVIDER_KEY": "synthetic-no-account",
            }
            environment.pop("OPENCODE_DISABLE_PROJECT_CONFIG", None)
            binary = _binary()
            with socket.socket() as listener_check:
                listener_check.bind(("127.0.0.1", 4097))
            process = subprocess.Popen(  # noqa: S603 - fixed local binary from source.
                [str(binary), "serve", "--hostname", "127.0.0.1", "--port", "4097"],
                cwd=location,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            with httpx.Client(
                base_url="http://127.0.0.1:4097",
                auth=("opencode", password),
                timeout=httpx.Timeout(3.0, connect=1.0),
                trust_env=False,
            ) as client:
                readiness_deadline = time.monotonic() + 15.0
                while time.monotonic() < readiness_deadline:
                    if process.poll() is not None:
                        raise RuntimeError("native worker exited")
                    try:
                        if client.get("/api/info").status_code == 200:
                            break
                    except httpx.HTTPError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("native worker readiness timed out")
                params = {"location[directory]": str(location)}
                model_deadline = time.monotonic() + 8.0
                while time.monotonic() < model_deadline:
                    response = client.get("/api/model", params=params)
                    payload = response.json() if response.status_code == 200 else {}
                    if any(
                        isinstance(row, dict)
                        and row.get("id") == "assistant-selected"
                        and row.get("providerID") == "assistant-proxy"
                        for row in payload.get("data", [])
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError("native selected model unavailable")
                search = _run_native_search_probe(
                    client,
                    {"providerID": "assistant-proxy", "id": "assistant-selected"},
                    location,
                )
                result = {
                    "command": "./.dev-venv/bin/python tests/native_assistant_search_probe.py",
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "binary_version": subprocess.run(  # noqa: S603 - _binary is a fixed local executable.
                        [str(binary), "--version"],
                        check=True,
                        capture_output=True,
                        text=True,
                        env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                        timeout=5,
                    ).stdout.strip(),
                    "synthetic_only_model": True,
                    "synthetic_public_query_only": True,
                    "config_websearch_provider": config.get("websearch", {}).get("provider"),
                    "tinyfish_configured": False,
                    "search": search,
                    "acceptance_criteria": {
                        "native_completed": search.get("status") == "native_search_completed",
                        "successful_terminal": search.get("terminal_outcome") == "succeeded",
                        "synthetic_model_continued_after_tool": (
                            search.get("synthetic_continuation_observed") is True
                            and search.get("synthetic_model_answer_nonempty") is True
                        ),
                        "nonempty_result": bool(
                            isinstance(search.get("search_result"), dict)
                            and search["search_result"].get("nonempty_result") is True
                        ),
                        "unverified_public_links": bool(
                            isinstance(search.get("search_result"), dict)
                            and search["search_result"].get("unverified_link_count", 0) > 0
                        ),
                    },
                }
                print(json.dumps(result, sort_keys=True, separators=(",", ":")))
                return 0 if _search_probe_passes(search) else 1
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())
