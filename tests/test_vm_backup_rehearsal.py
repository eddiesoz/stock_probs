"""Developer checks for the fixed-target Linode backup rehearsal boundary."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "linode" / "rehearse-vm-backup.sh"


def _private_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _fixtures() -> dict[str, dict[str, object]]:
    return {
        "GET https://api.linode.com/v4/linode/instances/106817202": {
            "status": 200,
            "body": {
                "id": 106817202,
                "region": "us-east",
                "type": "g6-nanode-1",
                "ipv4": ["203.0.113.50"],
            },
        },
        "GET https://api.linode.com/v4/linode/instances/106817202/backups/385239936": {
            "status": 200,
            "body": {
                "id": 385239936,
                "type": "snapshot",
                "status": "successful",
                "available": True,
                "region": "us-east",
            },
        },
        "GET https://api.linode.com/v4/networking/firewalls/177236117": {
            "status": 200,
            "body": {
                "id": 177236117,
                "status": "enabled",
                "rules": {
                    "inbound_policy": "DROP",
                    "inbound": [
                        {
                            "action": "ACCEPT",
                            "protocol": "TCP",
                            "ports": "22",
                            "addresses": {"ipv4": ["198.51.100.9/32"]},
                        }
                    ],
                },
            },
        },
        "GET https://api.linode.com/v4/linode/instances?page_size=500": {
            "status": 200,
            "body": {"page": 1, "pages": 1, "total": 0, "data": []},
        },
    }


def _fake_curl(tmp_path: Path, fixtures: dict[str, dict[str, object]]) -> tuple[Path, Path]:
    response_file = tmp_path / "curl-responses.json"
    response_file.write_text(json.dumps(fixtures), encoding="utf-8")
    log_file = tmp_path / "curl-log.jsonl"
    curl = tmp_path / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "method = args[args.index('--request') + 1]\n"
        "url = args[args.index('--url') + 1]\n"
        "output = Path(args[args.index('--output') + 1])\n"
        "body = args[args.index('--data-binary') + 1] if '--data-binary' in args else ''\n"
        "config = sys.stdin.buffer.read()\n"
        "Path(os.environ['FAKE_CURL_LOG']).open('a', encoding='utf-8').write(\n"
        "    json.dumps({'method': method, 'url': url, 'body': body,\n"
        "                'token_header_seen': b'Authorization: Bearer ' in config}) + '\\n'\n"
        ")\n"
        "fixtures = json.loads(Path(os.environ['FAKE_CURL_RESPONSES']).read_text())\n"
        "record = fixtures.get(method + ' ' + url)\n"
        "if record is None:\n"
        "    raise SystemExit('unexpected fake curl request: ' + method + ' ' + url)\n"
        "output.write_text(json.dumps(record['body']), encoding='utf-8')\n"
        "sys.stdout.write(str(record['status']))\n",
        encoding="utf-8",
    )
    curl.chmod(0o700)
    return curl, log_file


def _run(
    tmp_path: Path,
    arguments: list[str],
    *,
    fixtures: dict[str, dict[str, object]] | None = None,
    token_mode: int = 0o600,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    token = tmp_path / "linode-token"
    token.write_text("test-token-value\n", encoding="ascii")
    token.chmod(token_mode)
    _, log_file = _fake_curl(tmp_path, fixtures or _fixtures())
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["FAKE_CURL_LOG"] = str(log_file)
    environment["FAKE_CURL_RESPONSES"] = str(tmp_path / "curl-responses.json")
    result = subprocess.run(  # noqa: S603
        [
            str(SCRIPT),
            "--token-file",
            str(token),
            "--operator-ipv4-cidr",
            "198.51.100.9/32",
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if not log_file.exists():
        return result, []
    return result, [json.loads(line) for line in log_file.read_text().splitlines()]


def test_read_only_plan_checks_fixed_resources_without_mutation(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, [])

    assert result.returncode == 0, result.stderr
    assert "no Linode was created" in result.stdout
    assert {call["method"] for call in calls} == {"GET"}
    assert all(call["token_header_seen"] is True for call in calls)
    assert all("test-token-value" not in json.dumps(call) for call in calls)
    assert "test-token-value" not in result.stdout + result.stderr


def test_execute_requires_fixed_confirmation_before_api_access(tmp_path: Path) -> None:
    identity = _private_file(tmp_path / "operator-key", b"private-key")
    known_hosts = _private_file(tmp_path / "known-hosts", b"203.0.113.50 ssh-ed25519 AAAA\n")

    result, calls = _run(
        tmp_path,
        [
            "--execute",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--confirm",
            "wrong-confirmation",
        ],
    )

    assert result.returncode != 0
    assert "exact confirmation" in result.stderr
    assert calls == []


def test_resume_mode_requires_execute_and_has_no_id_argument(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, ["--resume-existing"])

    assert result.returncode != 0
    assert "requires --execute" in result.stderr
    assert calls == []

    result, calls = _run(tmp_path, ["--resume-existing", "106825234"])

    assert result.returncode != 0
    assert "unknown option" in result.stderr
    assert calls == []


def test_read_only_plan_rejects_a_public_application_firewall_rule(tmp_path: Path) -> None:
    fixtures = _fixtures()
    firewall = fixtures["GET https://api.linode.com/v4/networking/firewalls/177236117"]["body"]
    assert isinstance(firewall, dict)
    assert isinstance(firewall["rules"], dict)
    firewall["rules"]["inbound"].append(  # type: ignore[index]
        {
            "action": "ACCEPT",
            "protocol": "TCP",
            "ports": "8000",
            "addresses": {"ipv4": ["0.0.0.0/0"], "ipv6": []},
        }
    )

    result, calls = _run(tmp_path, [], fixtures=fixtures)

    assert result.returncode != 0
    assert "closed SSH-only policy" in result.stderr
    assert all(call["method"] == "GET" for call in calls)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda firewall: firewall.__setitem__("status", "disabled"), "closed SSH-only policy"),
        (
            lambda firewall: firewall["rules"]["inbound"][0]["addresses"].__setitem__(
                "ipv4", ["203.0.113.99/32"]
            ),
            "closed SSH-only policy",
        ),
        (
            lambda firewall: firewall["rules"]["inbound"][0]["addresses"].__setitem__(
                "ipv6", ["2001:db8::/64"]
            ),
            "closed SSH-only policy",
        ),
        (
            lambda firewall: firewall["rules"]["inbound"][0]["addresses"].__setitem__("ipv6", None),
            "closed SSH-only policy",
        ),
    ],
)
def test_read_only_plan_rejects_unsafe_firewall_identity(
    tmp_path: Path, mutation, message: str
) -> None:
    fixtures = _fixtures()
    firewall = fixtures["GET https://api.linode.com/v4/networking/firewalls/177236117"]["body"]
    assert isinstance(firewall, dict)
    mutation(firewall)

    result, calls = _run(tmp_path, [], fixtures=fixtures)

    assert result.returncode != 0
    assert message in result.stderr
    assert all(call["method"] == "GET" for call in calls)


def test_read_only_plan_rejects_flattened_firewall_addresses(tmp_path: Path) -> None:
    fixtures = _fixtures()
    firewall = fixtures["GET https://api.linode.com/v4/networking/firewalls/177236117"]["body"]
    assert isinstance(firewall, dict)
    rule = firewall["rules"]["inbound"][0]  # type: ignore[index]
    rule.pop("addresses")
    rule["ipv4"] = ["198.51.100.9/32"]

    result, calls = _run(tmp_path, [], fixtures=fixtures)

    assert result.returncode != 0
    assert "closed SSH-only policy" in result.stderr
    assert all(call["method"] == "GET" for call in calls)


def test_read_only_plan_accepts_explicit_empty_ipv6_addresses(tmp_path: Path) -> None:
    fixtures = _fixtures()
    firewall = fixtures["GET https://api.linode.com/v4/networking/firewalls/177236117"]["body"]
    assert isinstance(firewall, dict)
    firewall["rules"]["inbound"][0]["addresses"]["ipv6"] = []  # type: ignore[index]

    result, calls = _run(tmp_path, [], fixtures=fixtures)

    assert result.returncode == 0, result.stderr
    assert all(call["method"] == "GET" for call in calls)


def test_token_must_be_private_before_any_api_request(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, [], token_mode=0o640)

    assert result.returncode != 0
    assert "group/other-readable" in result.stderr
    assert calls == []


def test_script_pins_api_ssh_and_cleanup_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'API_ROOT="https://api.linode.com/v4"' in source
    for value in ("106817202", "385239936", "97934478", "177236117", "g6-nanode-1"):
        assert value in source
    assert "StrictHostKeyChecking=yes" in source
    assert "StrictHostKeyChecking=no" not in source
    assert "--location" not in source
    assert "ClearAllForwardings=yes" in source
    assert 'REMOTE_USER="signalops"' in source
    assert "--operator-ipv4-cidr" in source
    assert 'VOLUME = "signal-ledger_signal-ledger-data"' in source
    assert 'COMPOSE_PATH = "/opt/signal-ledger/compose.production.yaml"' in source
    assert 'APP_ENV_PATH = "/etc/signal-ledger/app.env"' in source
    assert '\\"firewall_id\\":177236117' in source
    assert 'api_request DELETE "/linode/instances/$TARGET_ID"' in source
    assert 'api_request DELETE "/linode/instances/$LEGACY_LINODE_ID"' not in source
    assert 'target["tunnel_enabled"] or target["tunnel_active"]' in source
    assert "restored_database_hash_mismatch" in source
    assert "logical_database_hash" in source
    assert "iterdump()" in source
    assert "immutable=1" not in source
    assert "restored_compose_hash_mismatch" in source
    assert "rehearsal_instance_deleted" in source
    assert 'addresses.get("ipv4")' in source
    assert "firewall_operator_cidr_mismatch" in source
    assert 'api_request POST "/linode/instances/$TARGET_ID/boot"' in source
    assert source.count('api_request POST "/linode/instances/$TARGET_ID/boot"') == 1
    assert source.index(
        'attached_response="$TMP_DIR/attached-firewalls-before-boot.json"'
    ) < source.index('api_request POST "/linode/instances/$TARGET_ID/boot"')
    assert "MAX_KEYSCAN_ATTEMPTS=12" in source
    assert "KEYSCAN_WAIT_SECONDS=5" in source
    assert "RESUME_TARGET_ID=106825234" in source
    assert "MAX_RESTORE_WAIT_ATTEMPTS=180" in source
    assert "--resume-existing" in source
    assert "assert_resume_target" in source
    for value in (
        "resume_target_identity_invalid",
        "resume_target_spec_invalid",
        "resume_target_status_invalid",
        '{"restoring", "offline", "running"}',
    ):
        assert value in source
    assert source.index('TARGET_ID="$RESUME_TARGET_ID"') < source.index(
        'api_request POST "/linode/instances/$TARGET_ID/boot"'
    )
    assert source.index('[[ -s "$source_key_material" ]]') < source.index(
        'for _attempt in $(seq 1 "$MAX_KEYSCAN_ATTEMPTS"); do'
    )
    assert 'comm -12 "$source_key_material" "$target_keyscan"' in source
    assert source.index('[[ -s "$target_known_hosts" ]] || fail') < source.index(
        'remote_verify "$TARGET_IP" "$target_known_hosts"'
    )


def test_create_payload_preserves_snapshot_host_keys_and_stays_offline() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    user_data = "I2Nsb3VkLWNvbmZpZwpzc2hfZGVsZXRla2V5czogZmFsc2UKc3NoX2dlbmtleXR5cGVzOiBbXQo="

    assert f'RESTORE_USER_DATA_B64="{user_data}"' in source
    assert base64.b64decode(user_data) == (
        b"#cloud-config\nssh_deletekeys: false\nssh_genkeytypes: []\n"
    )
    assert '\\"booted\\":false' in source
    assert '\\"metadata\\":{\\"user_data\\":\\"$RESTORE_USER_DATA_B64\\"}' in source
    assert source.index('\\"booted\\":false') < source.index(
        'api_request POST "/linode/instances/$TARGET_ID/boot"'
    )


@pytest.mark.parametrize("bad_status", ["pending", "failed"])
def test_backup_must_be_successful_and_available(tmp_path: Path, bad_status: str) -> None:
    fixtures = _fixtures()
    backup = fixtures["GET https://api.linode.com/v4/linode/instances/106817202/backups/385239936"][
        "body"
    ]
    assert isinstance(backup, dict)
    backup["status"] = bad_status

    result, calls = _run(tmp_path, [], fixtures=fixtures)

    assert result.returncode != 0
    assert "successful available backup" in result.stderr
    assert all(call["method"] == "GET" for call in calls)
