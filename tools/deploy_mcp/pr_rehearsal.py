"""Stage and run the fixed schema-13 rehearsal pair through the operator boundary."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIRECTORY = REPOSITORY_ROOT / "test-results" / "assistant-r120-pr-pair"
HOST = "45.79.180.32"
USER = "signalops"
REPOSITORY = "eddiesoz/stock_probs"
PULL_NUMBER = 2
HELPER_SOURCE_PR_NUMBER = 11
HOTFIX_PR_NUMBER = 9
HOTFIX_CONTRACT = "schema13_same_schema_hotfix_v1"
HOTFIX_CANDIDATE_REVISION = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
HOTFIX_V3_CONTRACT = "schema13_same_schema_hotfix_v3"
HOTFIX_V3_IMAGE_SOURCE_REVISION = "e40dbc3b721080057a2ab2b9b23565ebf4d85982"
HOTFIX_V3_REVIEWED_PR_HEAD_SHA = "8622e303d63a6d2bc419ef6a97a2fb9601a63f7e"
HOTFIX_V3_REVIEWED_PR9_COMMITS = (
    "a8eee53c21cca79a2d6ddc7b2451f89f5e60be7c",
    "7f66bc6cddb1f389b052714b4872828a3447b127",
    "9e0680b343cbc1097bc29fdc709a24a7537290a1",
    "1e134da0ad68ad4fe960714e2ea8911e3ee8d8aa",
    "8622e303d63a6d2bc419ef6a97a2fb9601a63f7e",
)
HOTFIX_V3_REVIEWED_PR9_FILE_DELTA = (
    (
        "MVP-PLAN.md",
        "d8c3646dcefd04ff2c8c9f3b8e38475500185405",
        "1d05707f2c7edbc82cec60a6e1e319ab4e3822fd",
        398,
        0,
    ),
    (
        "docs/develop/testing.md",
        "4fdb2800bf272d42e67519745bcb2daa063c70a6",
        "0386703d80211eda58b6740b7bac7904663ff3bf",
        59,
        0,
    ),
    (
        "tests/test_assistant_api.py",
        "888a32b17a2671aea3c2c87126c7e1f8f19e07e5",
        "3fdbecf1554916eb82c8c9cec49f02bd39487110",
        7,
        3,
    ),
    (
        "tests/test_assistant_final_boundary_coverage.py",
        "652d04666bb17f9b1cd9f93f66a6abeb58b8ffa6",
        "a9ea3c43c160123e812e03d82ced3cb9cab3eac7",
        4,
        2,
    ),
    (
        "tests/test_assistant_provider_admin_api_flows.py",
        "29959b587e3a53ce7b3b8f787000130a5771004e",
        "a31ef10d9d2fa226ffb613208e9ce8e5773fa85f",
        4,
        6,
    ),
    (
        "tests/test_assistant_runtime_event_http_flows.py",
        "d076fb753fcf7899082eada854b59e5fc564f6a4",
        "1bb3e947e051a3839494f82df1f75daea944d479",
        17,
        3,
    ),
    (
        "tests/test_backup_automation.py",
        "95d8b5f7305b2ce6e3b8f0db55fa9b19c03deed3",
        "2570d14bf93fac0f6a794fe5aa19bb2fc2ef3f92",
        22,
        2,
    ),
    (
        "tests/test_browser_assistant_fixture.py",
        "0000000000000000000000000000000000000000",
        "1ede43e34010ed48d5282c79c5ea3e1f5424876f",
        85,
        0,
    ),
    (
        "tests/test_history_repository.py",
        "81aae5be41362912d1697b132cc8aa24032fea57",
        "7676736e90ef20b0e80f89bd33e6e1aa18f92bb3",
        11,
        8,
    ),
    (
        "tools/browser/assistant_qa_server.py",
        "ba6bbdd01d5a9e62f5e99d82b99152151f394bf2",
        "2e6e4ecd861a5453b1498b184f57169fbfd68e9d",
        84,
        60,
    ),
    (
        "tools/browser/tests/assistant.spec.js",
        "3734a80eae843a382ac9b49bc2ec51d77b046903",
        "5d4be699bceba523aef8fdb1f25943e01c62ae6f",
        13,
        1,
    ),
    (
        "tools/browser/tests/fixtures.js",
        "89468fe1a51ab1a7fa46b9fc1f169bf3a1028230",
        "c517ba1ff6c8606042cbff041572cc5f628f2b79",
        10,
        1,
    ),
)
HOTFIX_V3_REVIEWED_TEST_PATCH = (
    '-        assert context["authorization_check"]() is True',
    '+        authorization_check = context["authorization_check"]',
    "+        assert callable(authorization_check)",
    "+        assert asyncio.run(authorization_check()) is True",
    '-        assert context["authorization_check"]() is False',
    "+        assert asyncio.run(authorization_check()) is False",
)
HOTFIX_V3_IMAGE_ID = "sha256:76aecf5483a38a0328f8560e1ae6a09d90f248e712d1dc719f765a224c7ccd2a"
HOTFIX_V3_IMAGE_CONTEXT_SHA256 = "16dba274c8485b69d3c798ea5f9a587c980eb37dbf6c0e64db2bcbc49ab8bf6c"
HOTFIX_V3_BUILD_RECEIPT_SHA256 = "b7810ed4ff96e96207a88886c8d9d1ec81625dc6d73ee1cd0d45121f25fd9ced"
HOTFIX_CANDIDATE_IMAGE_ID = (
    "sha256:52154c40d23c785f1d5522977c3add663ba6d3bffcc6c669cc2732c52cfdd196"
)
HOTFIX_CANDIDATE_CONTEXT_SHA256 = "a332dca5d27f4bb6fda4673e826096158c038e218f6291f01069951378c4fbae"
HOTFIX_BUILD_RECEIPT_SHA256 = "d3529f24499ea2f3b7921055a4308be019798b7be083fc6e75f1ad94b205b0b5"
HOTFIX_RECOVERY_ARCHIVE_SHA256 = "99b198f169958e63a4b1ee2380fa805c82a3bc75352d17f8feae2e4ad41185e5"
HOTFIX_RECOVERY_ARCHIVE_SIZE = 202_156_038
HOTFIX_RECOVERY_CONTEXT_SHA256 = "9f2abef917d4832783d32cfbf31290cc50df76c942b4238aa7f1330d4bc4f7bb"
HOTFIX_PRIOR_PAIR_MANIFEST_SHA256 = (
    "e9b7462aa6d5bf04201717a28644df085c58b5634125a2f9bb1aa096a7253ed3"
)
HOTFIX_EMPTY_OVERLAY_SHA256 = hashlib.sha256(b"[]").hexdigest()
HOTFIX_RECOVERY_KIND = "previous_production_candidate"
HELPER_PATH = "/usr/local/libexec/signal-ledger-pr-rehearsal/host_helper.py"
STATE_ROOT = "/var/lib/signal-ledger-pr-rehearsal"
INCOMING_DIRECTORY = "/var/lib/signal-ledger-pr-rehearsal/incoming"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 65_536
MAX_REVIEW_METADATA_BYTES = 4_096
REVIEW_METADATA_DIRECTORY = "signal-ledger"
REVIEW_METADATA_FILENAME = "rehearsal-review.json"
REVIEW_METADATA_VERSION = 1
REVIEW_METADATA_KEYS = {
    "format_version",
    "reviewed_pr_head_sha",
    "reviewed_pair_manifest_sha256",
}
REVIEW_HEAD_ENV = "SIGNAL_LEDGER_REHEARSAL_REVIEWED_PR_HEAD_SHA"
REVIEW_PAIR_ENV = "SIGNAL_LEDGER_REHEARSAL_REVIEWED_PAIR_MANIFEST_SHA256"
REVISION = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")
MODEL_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,95}$")
OOM_EVENT_COUNTERS = ("oom", "oom_kill", "oom_group_kill")
CPU_STAT_COUNTERS = ("usage_usec", "nr_periods", "nr_throttled", "throttled_usec")
MAX_RESOURCE_COUNTER = (1 << 64) - 1
EXPECTED_CANDIDATE_MEMORY_LIMIT = 768 * 1024 * 1024
EXPECTED_RECOVERY_MEMORY_LIMIT = 384 * 1024 * 1024
START_RESERVE_KIB = 512 * 1024
RUN_RESERVE_KIB = 128 * 1024
DEPLOYED_BASELINE = {
    "revision": "da2764e8477698fa7d686be93a4711e35478e802",
    "image_id": "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1",
    "archive_sha256": "669f840a3141b0fb95ae248b5ea0799733b9e5b5b81e224d4637571c24d8f640",
}


class ProductionBaseline(TypedDict):
    revision: str
    image_id: str
    schema_version: int


class RecoveryProductionBaselineFields(TypedDict):
    role: str
    revision: str
    image_id: str
    archive_sha256: str
    pair_manifest_sha256: str
    recovery_overlay_sha256: str
    migration_sha256: str
    compose_digest: str
    schema_version: int
    assistant_rollout_mode: str
    assistant_enabled: bool
    assistant_status: str
    loopback_only: bool


class RecoveryProductionBaseline(RecoveryProductionBaselineFields):
    container_id: str
    container_revision: str


class TemporaryRecoveryProductionBaselineFields(TypedDict):
    operation_kind: str
    operation_id: str
    phase: str
    start_admission_allowed: bool
    startup_floor_kib: int
    revision: str
    image_id: str
    image_ref: str
    build_tag: str
    archive_sha256: str
    archive_size: int
    manifest_sha256: str
    source_manifest_sha256: str
    source_context_sha256: str
    base_revision: str
    base_source_archive_sha256: str
    base_source_context_sha256: str
    migration_sha256: str
    overlay_sha256: str
    compose_digest: str
    schema_version: int
    platform: str
    assistant_rollout_mode: str
    assistant_enabled: bool
    assistant_status: str
    loopback_only: bool
    original_revision: str
    original_image_id: str
    original_compose_digest: str
    original_assistant_rollout_mode: str
    protected_recovery_revision: str
    protected_recovery_image_id: str
    protected_recovery_image_ref: str
    protected_recovery_archive_sha256: str
    protected_recovery_pair_manifest_sha256: str
    protected_recovery_overlay_sha256: str


class TemporaryRecoveryProductionBaseline(TemporaryRecoveryProductionBaselineFields):
    container_id: str
    container_revision: str


PRODUCTION_BASELINE: ProductionBaseline = {
    "revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
    "image_id": "sha256:78746f600815cac1941a9060f91bba41aca08f363714db466200c2d77e8ad7b1",
    "schema_version": 13,
}
RECOVERY_PRODUCTION_BASELINE: RecoveryProductionBaselineFields = {
    "role": "recovery",
    "revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
    "image_id": "sha256:a9b5147cff0016e443589e8c7b72e83764ca4bac45866ef3ad9bbcd3b308c13f",
    "archive_sha256": "082d04e065acfc1eb7db86358e40e20f937111f7d26901bd98b589521f8628c3",
    "pair_manifest_sha256": "e9b7462aa6d5bf04201717a28644df085c58b5634125a2f9bb1aa096a7253ed3",
    "recovery_overlay_sha256": "d1df9215ecb99dc8dc45b06c5b4c0aede364be6e80c7701a6814225397dfecad",
    "migration_sha256": "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b",
    "compose_digest": "01028e5b02cc0eded5f7b5207950a54b5a111b169f2a60a4ae8abdc6dfdb92b0",
    "schema_version": 13,
    "assistant_rollout_mode": "disabled",
    "assistant_enabled": False,
    "assistant_status": "disabled",
    "loopback_only": True,
}
MIGRATION_SHA256 = "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b"
TEMPORARY_RECOVERY_SOURCE_REVISION = "63597953c9d1ab387563dadfe705b78a2861a426"
TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256 = (
    "9443700f5248606c1f50a6e4e1bb2a20782a44aaa06fe62ffc3de2d17c4c2994"
)
TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256 = (
    "a197b69829076e75bdc1c51830761d1bb4d4c0fda9074372abb45b6d972d59d7"
)
TEMPORARY_RECOVERY_BASE_CONTEXT_SHA256 = (
    "38a2098f81fde0d3b73e7e3b3d31f84b5731492ff04b9ace2bfe5fd83c53c97b"
)
TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256 = (
    "964d7ca16ac1733c031780fc5dd3c271461489cc58cb9a653371cb060b26baa9"
)
TEMPORARY_RECOVERY_OVERLAY_SHA256 = (
    "272949c0fcaafcc0b217265619ba3eb76d9e9e92d69c18a2492100f5e14a0a6f"
)
TEMPORARY_RECOVERY_IMAGE_BUILD_TAG = "signal-ledger:temporary-recovery-build-63597953c9d1"
TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS: dict[str, object] = {
    "operation_kind": "temporary_recovery",
    "phase": "startup_floor_passed",
    "start_admission_allowed": True,
    "revision": TEMPORARY_RECOVERY_SOURCE_REVISION,
    "build_tag": TEMPORARY_RECOVERY_IMAGE_BUILD_TAG,
    "source_manifest_sha256": TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
    "source_context_sha256": TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
    "base_revision": DEPLOYED_BASELINE["revision"],
    "base_source_archive_sha256": TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256,
    "base_source_context_sha256": TEMPORARY_RECOVERY_BASE_CONTEXT_SHA256,
    "migration_sha256": MIGRATION_SHA256,
    "overlay_sha256": TEMPORARY_RECOVERY_OVERLAY_SHA256,
    "compose_digest": RECOVERY_PRODUCTION_BASELINE["compose_digest"],
    "schema_version": 13,
    "platform": "linux/amd64",
    "assistant_rollout_mode": "disabled",
    "assistant_enabled": False,
    "assistant_status": "disabled",
    "loopback_only": True,
    "original_revision": PRODUCTION_BASELINE["revision"],
    "original_image_id": PRODUCTION_BASELINE["image_id"],
    "original_compose_digest": RECOVERY_PRODUCTION_BASELINE["compose_digest"],
    "protected_recovery_revision": RECOVERY_PRODUCTION_BASELINE["revision"],
    "protected_recovery_image_id": RECOVERY_PRODUCTION_BASELINE["image_id"],
    "protected_recovery_image_ref": (
        f"signal-ledger:recovery-sha-{RECOVERY_PRODUCTION_BASELINE['revision']}"
    ),
    "protected_recovery_archive_sha256": RECOVERY_PRODUCTION_BASELINE["archive_sha256"],
    "protected_recovery_pair_manifest_sha256": RECOVERY_PRODUCTION_BASELINE["pair_manifest_sha256"],
    "protected_recovery_overlay_sha256": RECOVERY_PRODUCTION_BASELINE["recovery_overlay_sha256"],
}
SOURCE_ASSETS = {
    "bootstrap": ("scripts/pr_rehearsal_bootstrap.py", "bootstrap.py", 256 * 1024),
    "host_helper": ("scripts/pr_rehearsal_host_helper.py", "host_helper.py", 256 * 1024),
    "seed": ("scripts/pr_rehearsal_seed.py", "seed.py", 64 * 1024),
    "driver": ("tests/native_assistant_probe.py", "native_driver.py", 2 * 1024 * 1024),
    "production_helper": (
        "scripts/production-deploy-helper.py",
        "production-deploy-helper.py",
        512 * 1024,
    ),
}


class RehearsalError(Exception):
    """A safe rehearsal failure category for the local MCP boundary."""

    def __init__(self, code: str, *, details: dict[str, object] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class RehearsalConfig:
    """Hold operator SSH metadata and exact reviewed source/artifact pins."""

    identity_file: Path
    known_hosts_file: Path
    reviewed_head_sha: str
    reviewed_pair_manifest_sha256: str

    @classmethod
    def from_env(cls) -> RehearsalConfig:
        """Load fixed-target operator metadata without reading either private file."""

        home = Path.home()
        config_home = _review_config_home()
        identity = Path(
            os.environ.get(
                "SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE",
                str(home / ".ssh" / "signal-ledger-operator-2026"),
            )
        ).expanduser()
        known_hosts = Path(
            os.environ.get(
                "SIGNAL_LEDGER_KNOWN_HOSTS_FILE",
                str(config_home / "signal-ledger" / "credentials" / "linode-known-hosts"),
            )
        ).expanduser()
        environment_pins = _environment_review_pins()
        metadata_pins = _read_review_metadata()
        if (
            environment_pins is not None
            and metadata_pins is not None
            and environment_pins != metadata_pins
        ):
            raise RehearsalError("review_pins_disagree")
        pins = environment_pins or metadata_pins
        if pins is None:
            raise RehearsalError("review_pins_unconfigured")
        reviewed_head, reviewed_manifest = pins
        _private_file_metadata(identity, "operator_identity")
        _private_file_metadata(known_hosts, "known_hosts")
        return cls(
            identity.absolute(),
            known_hosts.absolute(),
            reviewed_head,
            reviewed_manifest,
        )


def _review_config_home() -> Path:
    """Return the fixed XDG config home without accepting relative or parent paths."""

    configured = os.environ.get("XDG_CONFIG_HOME")
    path = Path(configured) if configured is not None else Path.home() / ".config"
    if not path.is_absolute() or path == Path("/") or ".." in path.parts:
        raise RehearsalError("review_metadata_directory_unsafe")
    return path


def _environment_review_pins() -> tuple[str, str] | None:
    """Read only the paired public review pins and reject partial configuration."""

    head_present = REVIEW_HEAD_ENV in os.environ
    pair_present = REVIEW_PAIR_ENV in os.environ
    if head_present != pair_present:
        raise RehearsalError("review_pins_partial_environment")
    if not head_present:
        return None
    head = os.environ[REVIEW_HEAD_ENV]
    pair = os.environ[REVIEW_PAIR_ENV]
    if REVISION.fullmatch(head) is None or DIGEST.fullmatch(pair) is None:
        raise RehearsalError("review_pins_invalid")
    return head, pair


def _open_directory_chain(path: Path) -> int:
    """Open an absolute directory path component by component without following links."""

    if not path.is_absolute() or ".." in path.parts:
        raise RehearsalError("review_metadata_directory_unsafe")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open("/", directory_flags)
    except OSError as exc:
        raise RehearsalError("review_metadata_directory_unavailable") from exc
    try:
        for component in path.parts[1:]:
            try:
                next_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            except FileNotFoundError as exc:
                raise RehearsalError("review_metadata_directory_missing") from exc
            except OSError as exc:
                raise RehearsalError("review_metadata_directory_unavailable") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise RehearsalError("review_metadata_directory_unsafe")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_review_directory(*, create: bool) -> int | None:
    """Open the fixed private review directory, optionally creating it mode 0700."""

    config_home = _review_config_home()
    try:
        config_descriptor = _open_directory_chain(config_home)
    except RehearsalError as exc:
        if not create and exc.code == "review_metadata_directory_missing":
            return None
        raise
    try:
        created_directory = False
        if create:
            try:
                os.mkdir(REVIEW_METADATA_DIRECTORY, mode=0o700, dir_fd=config_descriptor)
                created_directory = True
            except FileExistsError:
                pass
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            descriptor = os.open(
                REVIEW_METADATA_DIRECTORY,
                directory_flags,
                dir_fd=config_descriptor,
            )
        except FileNotFoundError as exc:
            if not create:
                return None
            raise RehearsalError("review_metadata_directory_unavailable") from exc
        except OSError as exc:
            raise RehearsalError("review_metadata_directory_unsafe") from exc
        metadata = os.fstat(descriptor)
        try:
            if created_directory:
                os.fchmod(descriptor, 0o700)
                metadata = os.fstat(descriptor)
            _validate_review_directory_metadata(metadata)
        except RehearsalError:
            os.close(descriptor)
            raise
        return descriptor
    finally:
        os.close(config_descriptor)


def _file_signature(metadata: os.stat_result) -> tuple[int, ...]:
    """Return identity and metadata fields that must remain stable during access."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_uid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _validate_review_directory_metadata(metadata: os.stat_result) -> None:
    """Require the review directory to be private and owned by this operator."""

    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise RehearsalError("review_metadata_directory_unsafe")


def _validate_review_file_metadata(metadata: os.stat_result) -> None:
    """Require a single-link, private regular file within the fixed size bound."""

    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= MAX_REVIEW_METADATA_BYTES
    ):
        raise RehearsalError("review_metadata_permissions")


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys so JSON pins have one unambiguous interpretation."""

    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _validate_review_pins(value: object) -> tuple[str, str]:
    """Validate the exact three-field nonsensitive review metadata schema."""

    if (
        not isinstance(value, dict)
        or set(value) != REVIEW_METADATA_KEYS
        or type(value.get("format_version")) is not int
        or value.get("format_version") != REVIEW_METADATA_VERSION
    ):
        raise RehearsalError("review_metadata_invalid")
    head = value.get("reviewed_pr_head_sha")
    pair = value.get("reviewed_pair_manifest_sha256")
    if (
        not isinstance(head, str)
        or REVISION.fullmatch(head) is None
        or not isinstance(pair, str)
        or DIGEST.fullmatch(pair) is None
    ):
        raise RehearsalError("review_metadata_invalid")
    return head, pair


def _read_review_metadata() -> tuple[str, str] | None:
    """Read the fixed review file with private ownership and no-follow checks."""

    directory_descriptor = _open_review_directory(create=False)
    if directory_descriptor is None:
        return None
    try:
        directory_before = os.fstat(directory_descriptor)
        _validate_review_directory_metadata(directory_before)
        try:
            before = os.stat(
                REVIEW_METADATA_FILENAME,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RehearsalError("review_metadata_unavailable") from exc
        _validate_review_file_metadata(before)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        try:
            file_descriptor = os.open(
                REVIEW_METADATA_FILENAME,
                flags,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            raise RehearsalError("review_metadata_unavailable") from exc
        try:
            opened = os.fstat(file_descriptor)
            _validate_review_file_metadata(opened)
            if _file_signature(opened) != _file_signature(before):
                raise RehearsalError("review_metadata_changed")
            contents = bytearray()
            try:
                while len(contents) <= MAX_REVIEW_METADATA_BYTES:
                    chunk = os.read(
                        file_descriptor,
                        min(1024, MAX_REVIEW_METADATA_BYTES + 1 - len(contents)),
                    )
                    if not chunk:
                        break
                    contents.extend(chunk)
            except OSError as exc:
                raise RehearsalError("review_metadata_unavailable") from exc
            after = os.fstat(file_descriptor)
            _validate_review_file_metadata(after)
            try:
                current = os.stat(
                    REVIEW_METADATA_FILENAME,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                directory_after = os.fstat(directory_descriptor)
            except OSError as exc:
                raise RehearsalError("review_metadata_changed") from exc
            if (
                _file_signature(opened) != _file_signature(after)
                or _file_signature(opened) != _file_signature(current)
                or _file_signature(directory_before) != _file_signature(directory_after)
                or len(contents) != opened.st_size
                or len(contents) > MAX_REVIEW_METADATA_BYTES
            ):
                raise RehearsalError("review_metadata_changed")
        finally:
            os.close(file_descriptor)
    finally:
        os.close(directory_descriptor)
    try:
        value: object = json.loads(bytes(contents), object_pairs_hook=_strict_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RehearsalError("review_metadata_invalid") from exc
    return _validate_review_pins(value)


def _write_review_metadata(reviewed_head_sha: str, pair_manifest_sha256: str) -> None:
    """Atomically store only verified public pins in the fixed private config directory."""

    pins = _validate_review_pins(
        {
            "format_version": REVIEW_METADATA_VERSION,
            "reviewed_pr_head_sha": reviewed_head_sha,
            "reviewed_pair_manifest_sha256": pair_manifest_sha256,
        }
    )
    environment_pins = _environment_review_pins()
    if environment_pins is not None and environment_pins != pins:
        raise RehearsalError("review_pins_disagree")
    existing_pins = _read_review_metadata()
    if (
        environment_pins is not None
        and existing_pins is not None
        and environment_pins != existing_pins
    ):
        raise RehearsalError("review_pins_disagree")
    directory_descriptor = _open_review_directory(create=True)
    if directory_descriptor is None:
        raise RehearsalError("review_metadata_directory_unavailable")
    temporary_name = f".{REVIEW_METADATA_FILENAME}.{secrets.token_hex(8)}.tmp"
    encoded = (
        json.dumps(
            {
                "format_version": REVIEW_METADATA_VERSION,
                "reviewed_pr_head_sha": reviewed_head_sha,
                "reviewed_pair_manifest_sha256": pair_manifest_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        + b"\n"
    )
    file_descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        flags |= os.O_CLOEXEC | os.O_NONBLOCK
        try:
            file_descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            raise RehearsalError("review_metadata_write_failed") from exc
        os.fchmod(file_descriptor, 0o600)
        offset = 0
        while offset < len(encoded):
            written = os.write(file_descriptor, encoded[offset:])
            if written <= 0:
                raise RehearsalError("review_metadata_write_failed")
            offset += written
        os.fsync(file_descriptor)
        temporary_metadata = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(temporary_metadata.st_mode)
            or temporary_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(temporary_metadata.st_mode) != 0o600
            or temporary_metadata.st_nlink != 1
            or temporary_metadata.st_size != len(encoded)
        ):
            raise RehearsalError("review_metadata_write_failed")
        os.close(file_descriptor)
        file_descriptor = None
        try:
            existing = os.stat(
                REVIEW_METADATA_FILENAME,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.geteuid()
            or stat.S_IMODE(existing.st_mode) != 0o600
            or existing.st_nlink != 1
        ):
            raise RehearsalError("review_metadata_permissions")
        os.replace(
            temporary_name,
            REVIEW_METADATA_FILENAME,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    except OSError as exc:
        raise RehearsalError("review_metadata_write_failed") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        os.close(directory_descriptor)
    if _read_review_metadata() != pins:
        raise RehearsalError("review_metadata_write_failed")


def _private_file_metadata(path: Path, label: str) -> None:
    """Check SSH file metadata without opening or printing its contents."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RehearsalError(f"{label}_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise RehearsalError(f"{label}_permissions")


def _fixed_environment() -> dict[str, str]:
    """Drop inherited Git, SSH, proxy, and credential environment from child tools."""

    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "LANG": "C",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run_fixed(command: list[str], *, timeout: float, input_bytes: bytes | None = None) -> bytes:
    """Run one fixed executable with bounded captured output and no diagnostic forwarding."""

    try:
        result = subprocess.run(  # noqa: S603 - every command is fixed or digest-validated.
            command,
            cwd=REPOSITORY_ROOT,
            env=_fixed_environment(),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalError("fixed_operation_unavailable") from exc
    if result.returncode != 0:
        raise RehearsalError("fixed_operation_failed")
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise RehearsalError("fixed_operation_response_too_large")
    return result.stdout


def _validated_production_baseline(value: object) -> dict[str, object]:
    if isinstance(value, dict) and value == PRODUCTION_BASELINE:
        if type(value.get("schema_version")) is int:
            return dict(value)
        raise RehearsalError("host_response_invalid")
    temporary_dynamic_keys = {
        "operation_id",
        "startup_floor_kib",
        "image_id",
        "image_ref",
        "archive_sha256",
        "archive_size",
        "manifest_sha256",
        "original_assistant_rollout_mode",
        "container_id",
        "container_revision",
    }
    temporary_keys = set(TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS) | temporary_dynamic_keys
    if isinstance(value, dict) and set(value) == temporary_keys:
        operation_id = value.get("operation_id")
        image_id = value.get("image_id")
        container_id = value.get("container_id")
        archive_size = value.get("archive_size")
        startup_floor_kib = value.get("startup_floor_kib")
        if (
            any(
                value.get(key) != expected
                for key, expected in TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS.items()
            )
            or type(value.get("start_admission_allowed")) is not bool
            or type(value.get("assistant_enabled")) is not bool
            or type(value.get("loopback_only")) is not bool
            or type(value.get("schema_version")) is not int
            or not isinstance(operation_id, str)
            or OPERATION_ID.fullmatch(operation_id) is None
            or not isinstance(image_id, str)
            or IMAGE_ID.fullmatch(image_id) is None
            or image_id
            in {
                PRODUCTION_BASELINE["image_id"],
                RECOVERY_PRODUCTION_BASELINE["image_id"],
                DEPLOYED_BASELINE["image_id"],
            }
            or value.get("image_ref") != f"signal-ledger:temporary-recovery-{operation_id}"
            or not isinstance(value.get("archive_sha256"), str)
            or DIGEST.fullmatch(value["archive_sha256"]) is None
            or type(archive_size) is not int
            or not 1 <= archive_size <= MAX_ARCHIVE_BYTES
            or not isinstance(value.get("manifest_sha256"), str)
            or DIGEST.fullmatch(value["manifest_sha256"]) is None
            or type(startup_floor_kib) is not int
            or not START_RESERVE_KIB <= startup_floor_kib <= MAX_RESOURCE_COUNTER
            or not isinstance(container_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", container_id) is None
            or value.get("container_revision") != TEMPORARY_RECOVERY_SOURCE_REVISION
            or value.get("original_assistant_rollout_mode") != "invited"
        ):
            raise RehearsalError("host_response_invalid")
        return dict(value)
    recovery_keys = {*RECOVERY_PRODUCTION_BASELINE, "container_id", "container_revision"}
    if (
        not isinstance(value, dict)
        or set(value) != recovery_keys
        or any(value.get(key) != expected for key, expected in RECOVERY_PRODUCTION_BASELINE.items())
        or type(value.get("schema_version")) is not int
        or type(value.get("assistant_enabled")) is not bool
        or value.get("assistant_enabled") is not False
        or type(value.get("loopback_only")) is not bool
        or value.get("loopback_only") is not True
        or not isinstance(value.get("container_id"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["container_id"]) is None
        or value.get("container_revision") != RECOVERY_PRODUCTION_BASELINE["revision"]
    ):
        raise RehearsalError("host_response_invalid")
    return dict(value)


def _validated_v2_production_baseline(value: object) -> dict[str, object]:
    """Accept only the pinned release or a fully validated temporary baseline for V2."""
    baseline = _validated_production_baseline(value)
    if baseline != PRODUCTION_BASELINE and baseline.get("operation_kind") != "temporary_recovery":
        raise RehearsalError("host_response_invalid")
    return baseline


def _validated_native_evidence(response: dict[str, object]) -> dict[str, object]:
    """Require actual enabled-candidate and two-owner native evidence."""

    model_id = response.get("native_model_id")
    model_parts = model_id.split("/") if isinstance(model_id, str) else []
    summary_calls = response.get("mcp_workspace_summary_calls")
    search_sources = response.get("native_search_source_count")
    if (
        response.get("candidate_disabled_seed_verified") is not True
        or response.get("candidate_enabled_readiness_verified") is not True
        or response.get("native_workload_verified") is not True
        or not 2 <= len(model_parts) <= 4
        or any(MODEL_SEGMENT.fullmatch(part) is None for part in model_parts)
        or type(summary_calls) is not int
        or summary_calls != 2
        or type(search_sources) is not int
        or not 1 <= search_sources <= 10_000
        or response.get("simultaneous_two_owner_turns") is not True
        or response.get("ownership_isolation_verified") is not True
    ):
        raise RehearsalError("host_response_invalid")
    return {
        "candidate_disabled_seed_verified": True,
        "candidate_enabled_readiness_verified": True,
        "native_workload_verified": True,
        "native_model_id": model_id,
        "mcp_workspace_summary_calls": summary_calls,
        "native_search_source_count": search_sources,
        "simultaneous_two_owner_turns": True,
        "ownership_isolation_verified": True,
    }


def _validated_resource_evidence(response: dict[str, object]) -> dict[str, object]:
    """Project only complete, bounded host and cgroup resource observations."""

    capacity = response.get("host_memory_capacity_evidence")
    if (
        not isinstance(capacity, dict)
        or set(capacity) != {"complete", "unit", "memtotal_before", "memtotal_after", "stable"}
        or capacity.get("complete") is not True
        or capacity.get("unit") != "kib"
        or type(capacity.get("memtotal_before")) is not int
        or type(capacity.get("memtotal_after")) is not int
        or capacity.get("memtotal_before", 0) <= 0
        or capacity.get("memtotal_after", 0) <= 0
        or capacity.get("memtotal_before", MAX_RESOURCE_COUNTER + 1) > MAX_RESOURCE_COUNTER
        or capacity.get("memtotal_after", MAX_RESOURCE_COUNTER + 1) > MAX_RESOURCE_COUNTER
        or capacity.get("memtotal_before") != capacity.get("memtotal_after")
        or capacity.get("stable") is not True
    ):
        raise RehearsalError("host_response_invalid")

    available_before = response.get("host_memavailable_before_kib")
    available_after = response.get("host_memavailable_after_kib")
    if (
        type(available_before) is not int
        or type(available_after) is not int
        or not 0 <= available_before <= capacity["memtotal_before"]
        or not 0 <= available_after <= capacity["memtotal_after"]
        or available_before > MAX_RESOURCE_COUNTER
        or available_after > MAX_RESOURCE_COUNTER
        or available_before < START_RESERVE_KIB
        or available_after < RUN_RESERVE_KIB
    ):
        raise RehearsalError("host_response_invalid")

    candidate_peak = response.get("candidate_memory_peak_bytes")
    candidate_limit = response.get("candidate_memory_limit_bytes")
    recovery_peak = response.get("recovery_memory_peak_bytes")
    recovery_limit = response.get("recovery_memory_limit_bytes")
    if (
        type(candidate_peak) is not int
        or type(candidate_limit) is not int
        or type(recovery_peak) is not int
        or type(recovery_limit) is not int
        or candidate_limit != EXPECTED_CANDIDATE_MEMORY_LIMIT
        or recovery_limit != EXPECTED_RECOVERY_MEMORY_LIMIT
        or not 0 <= candidate_peak <= candidate_limit
        or not 0 <= recovery_peak <= recovery_limit
    ):
        raise RehearsalError("host_response_invalid")

    def validate_oom_evidence(value: object) -> dict[str, object]:
        if (
            not isinstance(value, dict)
            or set(value) != {"complete", "baseline", "final", "delta", "zero_oom_events"}
            or value.get("complete") is not True
            or value.get("zero_oom_events") is not True
        ):
            raise RehearsalError("host_response_invalid")
        observed: dict[str, dict[str, int]] = {}
        for field in ("baseline", "final", "delta"):
            counters = value.get(field)
            if not isinstance(counters, dict) or set(counters) != set(OOM_EVENT_COUNTERS):
                raise RehearsalError("host_response_invalid")
            if any(
                type(counters[counter]) is not int
                or not 0 <= counters[counter] <= MAX_RESOURCE_COUNTER
                for counter in OOM_EVENT_COUNTERS
            ):
                raise RehearsalError("host_response_invalid")
            observed[field] = {counter: counters[counter] for counter in OOM_EVENT_COUNTERS}
        for counter in OOM_EVENT_COUNTERS:
            baseline = observed["baseline"][counter]
            final = observed["final"][counter]
            delta = observed["delta"][counter]
            if baseline != 0 or final != 0 or delta != final - baseline:
                raise RehearsalError("host_response_invalid")
        return {
            "complete": True,
            "baseline": observed["baseline"],
            "final": observed["final"],
            "delta": observed["delta"],
            "zero_oom_events": True,
        }

    candidate_oom = validate_oom_evidence(response.get("candidate_oom_event_evidence"))
    recovery_oom = validate_oom_evidence(response.get("recovery_oom_event_evidence"))

    def validate_cpu_evidence(value: object, expected_role: str) -> dict[str, object]:
        if (
            not isinstance(value, dict)
            or set(value) != {"complete", "resource_role", "baseline", "final", "delta"}
            or value.get("complete") is not True
            or value.get("resource_role") != expected_role
        ):
            raise RehearsalError("host_response_invalid")
        observed: dict[str, dict[str, int]] = {}
        for field in ("baseline", "final", "delta"):
            counters = value.get(field)
            if not isinstance(counters, dict) or set(counters) != set(CPU_STAT_COUNTERS):
                raise RehearsalError("host_response_invalid")
            if any(
                type(counters[counter]) is not int
                or not 0 <= counters[counter] <= MAX_RESOURCE_COUNTER
                for counter in CPU_STAT_COUNTERS
            ):
                raise RehearsalError("host_response_invalid")
            observed[field] = {counter: counters[counter] for counter in CPU_STAT_COUNTERS}
        for counter in CPU_STAT_COUNTERS:
            baseline = observed["baseline"][counter]
            final = observed["final"][counter]
            delta = observed["delta"][counter]
            if final < baseline or delta != final - baseline:
                raise RehearsalError("host_response_invalid")
        return {
            "complete": True,
            "resource_role": expected_role,
            "baseline": observed["baseline"],
            "final": observed["final"],
            "delta": observed["delta"],
        }

    candidate_cpu = validate_cpu_evidence(response.get("candidate_cpu_stat_evidence"), "candidate")
    recovery_cpu = validate_cpu_evidence(response.get("recovery_cpu_stat_evidence"), "recovery")
    if (
        response.get("oom_event_evidence_complete") is not True
        or response.get("zero_oom_events_verified") is not True
    ):
        raise RehearsalError("host_response_invalid")

    return {
        "host_memavailable_before_kib": available_before,
        "host_memavailable_after_kib": available_after,
        "host_memory_capacity_evidence": {
            "complete": True,
            "unit": "kib",
            "memtotal_before": capacity["memtotal_before"],
            "memtotal_after": capacity["memtotal_after"],
            "stable": True,
        },
        "candidate_memory_peak_bytes": candidate_peak,
        "candidate_memory_limit_bytes": candidate_limit,
        "candidate_oom_event_evidence": candidate_oom,
        "candidate_cpu_stat_evidence": candidate_cpu,
        "recovery_memory_peak_bytes": recovery_peak,
        "recovery_memory_limit_bytes": recovery_limit,
        "recovery_oom_event_evidence": recovery_oom,
        "recovery_cpu_stat_evidence": recovery_cpu,
        "oom_event_evidence_complete": True,
        "zero_oom_events_verified": True,
    }


def verify_pull_request(reviewed_head_sha: str) -> dict[str, object]:
    """Require public PR #2 to remain open, based on main, at the reviewed SHA."""

    if REVISION.fullmatch(reviewed_head_sha) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{PULL_NUMBER}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "signal-ledger-r120-pr-rehearsal",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RehearsalError("reviewed_pr_unavailable")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RehearsalError("reviewed_pr_unavailable") from exc
    finally:
        connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RehearsalError("reviewed_pr_response_too_large")
    try:
        payload: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("reviewed_pr_response_invalid") from exc
    if not isinstance(payload, dict):
        raise RehearsalError("reviewed_pr_response_invalid")
    base = payload.get("base")
    head = payload.get("head")
    repository = payload.get("head")
    source_repository = repository.get("repo") if isinstance(repository, dict) else None
    if (
        payload.get("state") != "open"
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
        or head.get("sha") != reviewed_head_sha
        or not isinstance(source_repository, dict)
        or source_repository.get("full_name") != REPOSITORY
    ):
        raise RehearsalError("reviewed_pr_mismatch")
    return {
        "repository": REPOSITORY,
        "pull_number": PULL_NUMBER,
        "state": "open",
        "base": "main",
        "head_sha": reviewed_head_sha,
        "draft": payload.get("draft") is True,
    }


def verify_helper_source_pull_request(reviewed_head_sha: str) -> dict[str, object]:
    """Require PR #11 to remain open, based on main, at the reviewed helper SHA."""

    if REVISION.fullmatch(reviewed_head_sha) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{HELPER_SOURCE_PR_NUMBER}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "signal-ledger-r120-pr-rehearsal",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RehearsalError("helper_source_pr_unavailable")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RehearsalError("helper_source_pr_unavailable") from exc
    finally:
        connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RehearsalError("helper_source_pr_response_too_large")
    try:
        payload: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("helper_source_pr_response_invalid") from exc
    if not isinstance(payload, dict):
        raise RehearsalError("helper_source_pr_response_invalid")
    base = payload.get("base")
    head = payload.get("head")
    source_repository = head.get("repo") if isinstance(head, dict) else None
    if (
        payload.get("state") != "open"
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
        or head.get("sha") != reviewed_head_sha
        or not isinstance(source_repository, dict)
        or source_repository.get("full_name") != REPOSITORY
    ):
        raise RehearsalError("helper_source_pr_mismatch")
    return {
        "repository": REPOSITORY,
        "pull_number": HELPER_SOURCE_PR_NUMBER,
        "state": "open",
        "base": "main",
        "head_sha": reviewed_head_sha,
        "draft": payload.get("draft") is True,
    }


def verify_hotfix_pull_request(reviewed_pr_head_sha: str | None = None) -> dict[str, object]:
    """Require PR #9 to remain open at its explicitly bound reviewed test head."""

    expected_head_sha = (
        HOTFIX_CANDIDATE_REVISION if reviewed_pr_head_sha is None else reviewed_pr_head_sha
    )
    if REVISION.fullmatch(expected_head_sha) is None:
        raise RehearsalError("hotfix_pr_head_invalid")
    if reviewed_pr_head_sha is not None and expected_head_sha != HOTFIX_V3_REVIEWED_PR_HEAD_SHA:
        raise RehearsalError("hotfix_pr_head_unreviewed")

    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{HOTFIX_PR_NUMBER}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "signal-ledger-r120-pr-rehearsal",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RehearsalError("hotfix_pr_unavailable")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RehearsalError("hotfix_pr_unavailable") from exc
    finally:
        connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RehearsalError("hotfix_pr_response_too_large")
    try:
        payload: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("hotfix_pr_response_invalid") from exc
    if not isinstance(payload, dict):
        raise RehearsalError("hotfix_pr_response_invalid")
    base = payload.get("base")
    head = payload.get("head")
    source_repository = head.get("repo") if isinstance(head, dict) else None
    if (
        payload.get("state") != "open"
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
        or head.get("sha") != expected_head_sha
        or not isinstance(source_repository, dict)
        or source_repository.get("full_name") != REPOSITORY
    ):
        raise RehearsalError("hotfix_pr_mismatch")
    return {
        "repository": REPOSITORY,
        "pull_number": HOTFIX_PR_NUMBER,
        "state": "open",
        "base": "main",
        "head_sha": expected_head_sha,
        "draft": payload.get("draft") is True,
    }


def _read_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    """Read one fixed artifact only after rejecting links, special files, and size drift."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RehearsalError(f"{label}_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= maximum:
        raise RehearsalError(f"{label}_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(maximum + 1)
    except OSError as exc:
        raise RehearsalError(f"{label}_unavailable") from exc
    if len(data) != metadata.st_size or len(data) > maximum:
        raise RehearsalError(f"{label}_changed")
    return data


def _hotfix_pair_asset_names(reviewed_head_sha: str, *, format_version: int = 2) -> dict[str, str]:
    """Return fixed archive names while keeping helper and image revisions distinct."""

    if format_version not in {2, 3}:
        raise RehearsalError("pair_manifest_version_unsupported")
    candidate_revision = (
        HOTFIX_V3_IMAGE_SOURCE_REVISION if format_version == 3 else HOTFIX_CANDIDATE_REVISION
    )
    return {
        "candidate": f"signal-ledger-image-{candidate_revision}.tar.gz",
        "recovery": f"signal-ledger-image-{PRODUCTION_BASELINE['revision']}.tar.gz",
        "manifest": f"signal-ledger-pair-{reviewed_head_sha}.json",
    }


def _artifact_pair_hotfix(
    reviewed_head_sha: str,
    *,
    manifest: object,
    manifest_bytes: bytes,
    candidate_image_id: str,
    candidate_source_context_sha256: str,
    recovery_image_id: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Validate the additive same-schema contract against fixed candidate and recovery pins."""

    if not isinstance(manifest, dict):
        raise RehearsalError("pair_manifest_invalid")
    format_version = manifest.get("format_version")
    if type(format_version) is not int or format_version not in {2, 3}:
        raise RehearsalError("pair_manifest_version_unsupported")
    v3 = format_version == 3
    image_revision = HOTFIX_V3_IMAGE_SOURCE_REVISION if v3 else HOTFIX_CANDIDATE_REVISION
    image_id = HOTFIX_V3_IMAGE_ID if v3 else HOTFIX_CANDIDATE_IMAGE_ID
    image_context = HOTFIX_V3_IMAGE_CONTEXT_SHA256 if v3 else HOTFIX_CANDIDATE_CONTEXT_SHA256
    build_receipt = HOTFIX_V3_BUILD_RECEIPT_SHA256 if v3 else HOTFIX_BUILD_RECEIPT_SHA256
    names = _hotfix_pair_asset_names(reviewed_head_sha, format_version=format_version)
    try:
        candidate_archive = _read_regular_file(
            ARTIFACT_DIRECTORY / names["candidate"],
            maximum=MAX_ARCHIVE_BYTES,
            label="candidate_asset",
        )
        recovery_archive = _read_regular_file(
            ARTIFACT_DIRECTORY / names["recovery"],
            maximum=MAX_ARCHIVE_BYTES,
            label="recovery_asset",
        )
    except RehearsalError:
        raise

    candidate = manifest.get("candidate")
    recovery = manifest.get("recovery")
    helper_source = manifest.get("helper_source")
    transition = manifest.get("transition")
    overlay = manifest.get("recovery_overlay")
    expected_root_keys = {
        "format_version",
        "contract",
        "repository",
        "revision",
        "helper_source",
        "candidate",
        "recovery",
        "transition",
        "recovery_overlay",
    }
    if v3:
        expected_root_keys.update({"reviewed_pr_head_sha", "image_source_revision"})
    expected = (
        set(manifest) == expected_root_keys
        and manifest.get("contract") == (HOTFIX_V3_CONTRACT if v3 else HOTFIX_CONTRACT)
        and manifest.get("repository") == REPOSITORY
        and manifest.get("revision") == reviewed_head_sha
        and (
            not v3
            or (
                isinstance(manifest.get("reviewed_pr_head_sha"), str)
                and manifest["reviewed_pr_head_sha"] == HOTFIX_V3_REVIEWED_PR_HEAD_SHA
                and manifest.get("image_source_revision") == image_revision
            )
        )
        and isinstance(helper_source, dict)
        and set(helper_source) == {"pull_number", "revision"}
        and type(helper_source.get("pull_number")) is int
        and helper_source.get("pull_number") == HELPER_SOURCE_PR_NUMBER
        and helper_source.get("revision") == reviewed_head_sha
        and isinstance(candidate, dict)
        and set(candidate)
        == {
            "asset",
            "archive_sha256",
            "archive_size",
            "image_id",
            "platform",
            "pull_number",
            "revision",
            "schema_version",
            "source_context_sha256",
            "build_receipt_sha256",
        }
        and candidate.get("asset") == names["candidate"]
        and candidate.get("archive_sha256") == hashlib.sha256(candidate_archive).hexdigest()
        and type(candidate.get("archive_size")) is int
        and candidate.get("archive_size") == len(candidate_archive)
        and candidate.get("image_id") == image_id == candidate_image_id
        and candidate.get("platform") == "linux/amd64"
        and type(candidate.get("pull_number")) is int
        and candidate.get("pull_number") == HOTFIX_PR_NUMBER
        and candidate.get("revision") == image_revision
        and type(candidate.get("schema_version")) is int
        and candidate.get("schema_version") == 13
        and candidate.get("source_context_sha256")
        == image_context
        == candidate_source_context_sha256
        and candidate.get("build_receipt_sha256") == build_receipt
        and isinstance(recovery, dict)
        and set(recovery)
        == {
            "asset",
            "archive_sha256",
            "archive_size",
            "image_id",
            "platform",
            "revision",
            "schema_version",
            "source_context_sha256",
            "kind",
            "prior_pair_manifest_sha256",
            "assistant_rollout_mode",
        }
        and recovery.get("asset") == names["recovery"]
        and recovery.get("archive_sha256") == HOTFIX_RECOVERY_ARCHIVE_SHA256
        and hashlib.sha256(recovery_archive).hexdigest() == HOTFIX_RECOVERY_ARCHIVE_SHA256
        and type(recovery.get("archive_size")) is int
        and recovery.get("archive_size") == HOTFIX_RECOVERY_ARCHIVE_SIZE == len(recovery_archive)
        and recovery.get("image_id") == PRODUCTION_BASELINE["image_id"] == recovery_image_id
        and recovery.get("platform") == "linux/amd64"
        and recovery.get("revision") == PRODUCTION_BASELINE["revision"]
        and type(recovery.get("schema_version")) is int
        and recovery.get("schema_version") == PRODUCTION_BASELINE["schema_version"] == 13
        and recovery.get("source_context_sha256")
        == HOTFIX_RECOVERY_CONTEXT_SHA256
        == recovery_source_context_sha256
        and recovery.get("kind") == HOTFIX_RECOVERY_KIND
        and recovery.get("prior_pair_manifest_sha256") == HOTFIX_PRIOR_PAIR_MANIFEST_SHA256
        and recovery.get("assistant_rollout_mode") == "invited"
        and isinstance(transition, dict)
        and transition
        == {
            "from_schema": 13,
            "to_schema": 13,
            "migrations": [],
            "restore": False,
        }
        and isinstance(overlay, dict)
        and overlay == {"kind": "none", "sha256": HOTFIX_EMPTY_OVERLAY_SHA256}
        and recovery_overlay_sha256 == HOTFIX_EMPTY_OVERLAY_SHA256
    )
    if not expected:
        raise RehearsalError("pair_manifest_identity_mismatch")
    return manifest, {
        "manifest": manifest_bytes,
        "candidate": candidate_archive,
        "recovery": recovery_archive,
    }


def _artifact_pair(
    reviewed_head_sha: str,
    *,
    candidate_image_id: str,
    candidate_source_context_sha256: str,
    recovery_image_id: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
    pair_manifest_sha256: str,
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Bind the fixed local release assets to every typed identity supplied by the caller."""

    if REVISION.fullmatch(reviewed_head_sha) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    if not IMAGE_ID.fullmatch(candidate_image_id) or not IMAGE_ID.fullmatch(recovery_image_id):
        raise RehearsalError("image_identity_invalid")
    for value in (
        candidate_source_context_sha256,
        recovery_source_context_sha256,
        recovery_overlay_sha256,
        pair_manifest_sha256,
    ):
        if DIGEST.fullmatch(value) is None:
            raise RehearsalError("pair_digest_invalid")
    try:
        directory_info = ARTIFACT_DIRECTORY.lstat()
    except OSError as exc:
        raise RehearsalError("pair_assets_unavailable") from exc
    if not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode):
        raise RehearsalError("pair_assets_unsafe")
    manifest_name = f"signal-ledger-pair-{reviewed_head_sha}.json"
    manifest_bytes = _read_regular_file(
        ARTIFACT_DIRECTORY / manifest_name,
        maximum=MAX_MANIFEST_BYTES,
        label="manifest_asset",
    )
    if hashlib.sha256(manifest_bytes).hexdigest() != pair_manifest_sha256:
        raise RehearsalError("pair_manifest_digest_mismatch")
    try:
        manifest: object = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("pair_manifest_invalid") from exc
    if isinstance(manifest, dict) and manifest.get("format_version") in {2, 3}:
        return _artifact_pair_hotfix(
            reviewed_head_sha,
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            candidate_image_id=candidate_image_id,
            candidate_source_context_sha256=candidate_source_context_sha256,
            recovery_image_id=recovery_image_id,
            recovery_source_context_sha256=recovery_source_context_sha256,
            recovery_overlay_sha256=recovery_overlay_sha256,
        )
    if not isinstance(manifest, dict):
        raise RehearsalError("pair_manifest_invalid")
    names = {
        "candidate": f"signal-ledger-image-{reviewed_head_sha}.tar.gz",
        "recovery": f"signal-ledger-recovery-{reviewed_head_sha}.tar.gz",
        "manifest": manifest_name,
    }
    assets = {"manifest": manifest_bytes}
    assets.update(
        {
            role: _read_regular_file(
                ARTIFACT_DIRECTORY / name,
                maximum=MAX_ARCHIVE_BYTES,
                label=f"{role}_asset",
            )
            for role, name in names.items()
            if role != "manifest"
        }
    )
    candidate = manifest.get("candidate")
    recovery = manifest.get("recovery")
    migration = manifest.get("migration")
    expected = (
        set(manifest)
        == {
            "format_version",
            "repository",
            "revision",
            "source_context_sha256",
            "migration",
            "candidate",
            "recovery",
        }
        and type(manifest.get("format_version")) is int
        and manifest.get("format_version") == 1
        and manifest.get("repository") == REPOSITORY
        and manifest.get("revision") == reviewed_head_sha
        and manifest.get("source_context_sha256") == candidate_source_context_sha256
        and isinstance(candidate, dict)
        and candidate.get("asset") == names["candidate"]
        and candidate.get("image_id") == candidate_image_id
        and candidate.get("archive_sha256") == hashlib.sha256(assets["candidate"]).hexdigest()
        and candidate.get("archive_size") == len(assets["candidate"])
        and candidate.get("platform") == "linux/amd64"
        and candidate.get("revision") == reviewed_head_sha
        and candidate.get("schema_version") == 13
        and candidate.get("source_context_sha256") == candidate_source_context_sha256
        and isinstance(recovery, dict)
        and recovery.get("asset") == names["recovery"]
        and recovery.get("image_id") == recovery_image_id
        and recovery.get("archive_sha256") == hashlib.sha256(assets["recovery"]).hexdigest()
        and recovery.get("archive_size") == len(assets["recovery"])
        and recovery.get("platform") == "linux/amd64"
        and recovery.get("revision") == reviewed_head_sha
        and recovery.get("schema_version") == 13
        and recovery.get("assistant_enabled") is False
        and recovery.get("source_context_sha256") == recovery_source_context_sha256
        and recovery.get("base_revision") == DEPLOYED_BASELINE["revision"]
        and recovery.get("base_image_id") == DEPLOYED_BASELINE["image_id"]
        and recovery.get("base_archive_sha256") == DEPLOYED_BASELINE["archive_sha256"]
        and recovery.get("overlay_sha256") == recovery_overlay_sha256
        and recovery.get("migration_sha256") == MIGRATION_SHA256
        and isinstance(migration, dict)
        and migration.get("from_schema") == 12
        and migration.get("to_schema") == 13
        and migration.get("sha256") == recovery.get("migration_sha256")
    )
    if not expected:
        raise RehearsalError("pair_manifest_identity_mismatch")
    return manifest, assets


def write_review_pins_from_current_pair() -> dict[str, str]:
    """Verify the current pair's fixed helper PR and persist its two public review pins."""

    environment_pins = _environment_review_pins()
    metadata_pins = _read_review_metadata()
    if (
        environment_pins is not None
        and metadata_pins is not None
        and environment_pins != metadata_pins
    ):
        raise RehearsalError("review_pins_disagree")
    head_raw = _run_fixed(
        [
            "/usr/bin/git",
            "-C",
            str(REPOSITORY_ROOT),
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        ],
        timeout=15,
    )
    try:
        reviewed_head_sha = head_raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise RehearsalError("reviewed_pr_head_invalid") from exc
    if REVISION.fullmatch(reviewed_head_sha) is None:
        raise RehearsalError("reviewed_pr_head_invalid")

    manifest_path = ARTIFACT_DIRECTORY / f"signal-ledger-pair-{reviewed_head_sha}.json"
    manifest_bytes = _read_regular_file(
        manifest_path,
        maximum=MAX_MANIFEST_BYTES,
        label="pair_manifest",
    )
    try:
        manifest_value: object = json.loads(
            manifest_bytes,
            object_pairs_hook=_strict_object_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RehearsalError("pair_manifest_invalid") from exc
    if not isinstance(manifest_value, dict):
        raise RehearsalError("pair_manifest_invalid")
    candidate = manifest_value.get("candidate")
    recovery = manifest_value.get("recovery")
    candidate_context = (
        candidate.get("source_context_sha256") if isinstance(candidate, dict) else None
    )
    recovery_context = recovery.get("source_context_sha256") if isinstance(recovery, dict) else None
    overlay_value = manifest_value.get("recovery_overlay")
    overlay = (
        overlay_value.get("sha256")
        if isinstance(overlay_value, dict)
        else recovery.get("overlay_sha256")
        if isinstance(recovery, dict)
        else None
    )
    candidate_image_id = candidate.get("image_id") if isinstance(candidate, dict) else None
    recovery_image_id = recovery.get("image_id") if isinstance(recovery, dict) else None
    if (
        manifest_value.get("revision") != reviewed_head_sha
        or not isinstance(candidate_context, str)
        or not isinstance(recovery_context, str)
        or not isinstance(overlay, str)
        or not isinstance(candidate_image_id, str)
        or not isinstance(recovery_image_id, str)
    ):
        raise RehearsalError("pair_manifest_identity_mismatch")
    pair_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    proposed_pins = (reviewed_head_sha, pair_manifest_sha256)
    if environment_pins is not None and environment_pins != proposed_pins:
        raise RehearsalError("review_pins_disagree")

    _artifact_pair(
        reviewed_head_sha,
        candidate_image_id=candidate_image_id,
        candidate_source_context_sha256=candidate_context,
        recovery_image_id=recovery_image_id,
        recovery_source_context_sha256=recovery_context,
        recovery_overlay_sha256=overlay,
        pair_manifest_sha256=pair_manifest_sha256,
    )
    if manifest_value.get("format_version") in {2, 3}:
        _verify_local_helper_checkout(reviewed_head_sha)
        verify_helper_source_pull_request(reviewed_head_sha)
        verify_hotfix_pull_request(
            manifest_value.get("reviewed_pr_head_sha")
            if manifest_value.get("format_version") == 3
            else None
        )
        if manifest_value.get("format_version") == 3:
            _verify_local_v3_pr_lineage(manifest_value["reviewed_pr_head_sha"], reviewed_head_sha)
    else:
        _verify_local_reviewed_source(
            reviewed_head_sha,
            candidate_source_context_sha256=candidate_context,
            recovery_source_context_sha256=recovery_context,
            recovery_overlay_sha256=overlay,
        )
        verify_pull_request(reviewed_head_sha)
    _write_review_metadata(*proposed_pins)
    return {
        "reviewed_pr_head_sha": reviewed_head_sha,
        "reviewed_pair_manifest_sha256": pair_manifest_sha256,
    }


def _verify_local_reviewed_source(
    reviewed_head_sha: str,
    *,
    candidate_source_context_sha256: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
) -> None:
    """Require a clean exact PR checkout and independently recompute both source manifests."""

    head = (
        _run_fixed(
            ["/usr/bin/git", "-C", str(REPOSITORY_ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
            timeout=15,
        )
        .decode("ascii", errors="strict")
        .strip()
    )
    origin = (
        _run_fixed(
            ["/usr/bin/git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"],
            timeout=15,
        )
        .decode("utf-8", errors="strict")
        .strip()
    )
    changes = _run_fixed(
        [
            "/usr/bin/git",
            "-C",
            str(REPOSITORY_ROOT),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        timeout=15,
    )
    if head != reviewed_head_sha or origin != "https://github.com/eddiesoz/stock_probs.git":
        raise RehearsalError("reviewed_local_source_mismatch")
    if changes:
        raise RehearsalError("reviewed_local_source_dirty")
    script = str(REPOSITORY_ROOT / "scripts" / "rehearse_schema13.py")
    manifests: list[dict[str, object]] = []
    for argument in ("--source-context-manifest", "--overlay-manifest"):
        raw = _run_fixed(["/usr/bin/python3", script, argument], timeout=120)
        try:
            value: object = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RehearsalError("reviewed_source_manifest_invalid") from exc
        if not isinstance(value, dict) or value.get("status") != "prepared":
            raise RehearsalError("reviewed_source_manifest_invalid")
        manifests.append(value)
    source_context = manifests[0].get("source_context_sha256")
    overlay = manifests[1].get("recovery_overlay")
    recovery_context = manifests[1].get("recovery_context_sha256")
    overlay_digest = overlay.get("overlay_sha256") if isinstance(overlay, dict) else None
    if (
        source_context != candidate_source_context_sha256
        or recovery_context != recovery_source_context_sha256
        or overlay_digest != recovery_overlay_sha256
    ):
        raise RehearsalError("reviewed_source_context_mismatch")


def _verify_local_helper_checkout(reviewed_head_sha: str) -> None:
    """Verify the exact clean PR #11 helper checkout, separate from PR #9 image pins."""

    head = (
        _run_fixed(
            ["/usr/bin/git", "-C", str(REPOSITORY_ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
            timeout=15,
        )
        .decode("ascii", errors="strict")
        .strip()
    )
    origin = (
        _run_fixed(
            ["/usr/bin/git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"],
            timeout=15,
        )
        .decode("utf-8", errors="strict")
        .strip()
    )
    changes = _run_fixed(
        [
            "/usr/bin/git",
            "-C",
            str(REPOSITORY_ROOT),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        timeout=15,
    )
    if head != reviewed_head_sha or origin != "https://github.com/eddiesoz/stock_probs.git":
        raise RehearsalError("reviewed_local_source_mismatch")
    if changes:
        raise RehearsalError("reviewed_local_source_dirty")


def _local_v3_pr9_delta_matches(raw_diff: bytes, numstat: bytes) -> bool:
    """Match Git's bounded raw diff and numstat to the frozen exact PR #9 delta."""

    expected = {
        filename: (base_blob.encode("ascii"), head_blob.encode("ascii"), additions, deletions)
        for (
            filename,
            base_blob,
            head_blob,
            additions,
            deletions,
        ) in HOTFIX_V3_REVIEWED_PR9_FILE_DELTA
    }
    raw_records = raw_diff.split(b"\0")
    if not raw_records or raw_records[-1] != b"" or (len(raw_records) - 1) % 2:
        return False
    observed_raw: dict[str, tuple[bytes, bytes, bytes, bytes]] = {}
    for index in range(0, len(raw_records) - 1, 2):
        fields = raw_records[index].split(b" ")
        try:
            filename = raw_records[index + 1].decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return False
        if (
            len(fields) != 5
            or fields[0] not in {b":100644", b":000000"}
            or fields[1] != b"100644"
            or fields[4] != (b"A" if fields[0] == b":000000" else b"M")
            or filename in observed_raw
        ):
            return False
        observed_raw[filename] = (fields[2], fields[3], fields[0], fields[1])
    expected_raw = {
        filename: (
            base_blob,
            head_blob,
            b":000000" if base_blob == (b"0" * 40) else b":100644",
            b"100644",
        )
        for filename, (base_blob, head_blob, _additions, _deletions) in expected.items()
    }
    if observed_raw != expected_raw:
        return False

    stat_records = numstat.split(b"\0")
    if not stat_records or stat_records[-1] != b"":
        return False
    observed_stats: dict[str, tuple[bytes, bytes]] = {}
    for record in stat_records[:-1]:
        fields = record.split(b"\t")
        if len(fields) != 3:
            return False
        try:
            filename = fields[2].decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return False
        if filename in observed_stats:
            return False
        observed_stats[filename] = (fields[0], fields[1])
    expected_stats = {
        filename: (str(additions).encode("ascii"), str(deletions).encode("ascii"))
        for filename, (_base_blob, _head_blob, additions, deletions) in expected.items()
    }
    return observed_stats == expected_stats


def _verify_local_v3_pr_lineage(reviewed_pr_head_sha: str, helper_sha: str) -> None:
    """Prove the exact PR #9 delta and both ancestry links before staging or admission."""

    if (
        reviewed_pr_head_sha != HOTFIX_V3_REVIEWED_PR_HEAD_SHA
        or REVISION.fullmatch(helper_sha) is None
    ):
        raise RehearsalError("reviewed_pr_head_invalid")
    for base, descendant in (
        (HOTFIX_V3_IMAGE_SOURCE_REVISION, reviewed_pr_head_sha),
        (reviewed_pr_head_sha, helper_sha),
    ):
        _run_fixed(["/usr/bin/git", "merge-base", "--is-ancestor", base, descendant], timeout=10)
    commits = _run_fixed(
        [
            "/usr/bin/git",
            "rev-list",
            "--reverse",
            f"{HOTFIX_V3_IMAGE_SOURCE_REVISION}..{reviewed_pr_head_sha}",
        ],
        timeout=10,
    )
    expected_commits = ("\n".join(HOTFIX_V3_REVIEWED_PR9_COMMITS) + "\n").encode("ascii")
    if commits != expected_commits:
        raise RehearsalError("reviewed_pr_lineage_mismatch")

    path = "tests/test_assistant_final_boundary_coverage.py"
    raw_diff = _run_fixed(
        [
            "/usr/bin/git",
            "diff",
            "--raw",
            "--no-abbrev",
            "-z",
            "--no-renames",
            HOTFIX_V3_IMAGE_SOURCE_REVISION,
            reviewed_pr_head_sha,
        ],
        timeout=10,
    )
    counts = _run_fixed(
        [
            "/usr/bin/git",
            "diff",
            "--numstat",
            "-z",
            "--no-renames",
            HOTFIX_V3_IMAGE_SOURCE_REVISION,
            reviewed_pr_head_sha,
        ],
        timeout=10,
    )
    patch = _run_fixed(
        [
            "/usr/bin/git",
            "diff",
            "--no-ext-diff",
            "--no-renames",
            "--unified=0",
            HOTFIX_V3_IMAGE_SOURCE_REVISION,
            reviewed_pr_head_sha,
            "--",
            path,
        ],
        timeout=10,
    )
    try:
        changed_lines = [
            line
            for line in patch.decode("utf-8", errors="strict").splitlines()
            if (line.startswith("+") and not line.startswith("+++"))
            or (line.startswith("-") and not line.startswith("---"))
        ]
    except UnicodeDecodeError as exc:
        raise RehearsalError("reviewed_pr_diff_invalid") from exc
    expected_changed_lines = list(HOTFIX_V3_REVIEWED_TEST_PATCH)
    if not _local_v3_pr9_delta_matches(raw_diff, counts) or changed_lines != expected_changed_lines:
        raise RehearsalError("reviewed_pr_test_diff_mismatch")


def _ssh_prefix(config: RehearsalConfig) -> list[str]:
    """Return the only permitted operator SSH option set and target."""

    return [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        f"UserKnownHostsFile={config.known_hosts_file}",
        "-i",
        str(config.identity_file),
        f"{USER}@{HOST}",
    ]


def _stage_assets(config: RehearsalConfig, revision: str, assets: dict[str, bytes]) -> None:
    """Copy the three fixed pair files to names derived only from the validated PR SHA."""

    names = {
        "candidate": f"signal-ledger-pr1-{revision}-candidate.tar.gz",
        "recovery": f"signal-ledger-pr1-{revision}-recovery.tar.gz",
        "manifest": f"signal-ledger-pr1-{revision}-pair.json",
    }
    _stage_named_assets(config, names, assets)


def _stage_named_assets(
    config: RehearsalConfig,
    names: dict[str, str],
    assets: dict[str, bytes],
) -> None:
    """Stage only caller-independent names already derived from fixed asset roles."""

    for role, content in assets.items():
        descriptor, raw_path = tempfile.mkstemp(prefix="signal-ledger-pr-pair-")
        path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            path.chmod(0o600)
            remote_path = f"{USER}@{HOST}:{INCOMING_DIRECTORY}/{names[role]}"
            command = [
                "scp",
                "-q",
                "-B",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                f"UserKnownHostsFile={config.known_hosts_file}",
                "-i",
                str(config.identity_file),
                str(path),
                remote_path,
            ]
            _run_fixed(command, timeout=180)
        finally:
            path.unlink(missing_ok=True)


def _ensure_incoming_directories(config: RehearsalConfig) -> None:
    """Create only the fixed sidecar staging path, with no production path involved."""

    command = [
        *_ssh_prefix(config),
        "sudo -n /usr/bin/install -d -o root -g signalops -m 0750 "
        f"{STATE_ROOT} && sudo -n /usr/bin/install -d -o {USER} -g {USER} -m 0700 "
        f"{INCOMING_DIRECTORY}",
    ]
    _run_fixed(command, timeout=30)


def _source_bundle(
    *, include_production_helper: bool = False
) -> tuple[dict[str, bytes], dict[str, str]]:
    assets: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    selected = {
        role: definition
        for role, definition in SOURCE_ASSETS.items()
        if include_production_helper or role != "production_helper"
    }
    for role, (relative, _remote_name, maximum) in selected.items():
        content = _read_regular_file(
            REPOSITORY_ROOT / relative,
            maximum=maximum,
            label="bootstrap_source",
        )
        assets[role] = content
        hashes[role] = hashlib.sha256(content).hexdigest()
    return assets, hashes


def _source_stage_names(
    revision: str, *, include_production_helper: bool = False
) -> dict[str, str]:
    """Derive only the fixed incoming basenames for one validated reviewed SHA."""

    if REVISION.fullmatch(revision) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    return {
        role: f"signal-ledger-pr1-{revision}-{remote_name}"
        for role, (_path, remote_name, _maximum) in SOURCE_ASSETS.items()
        if include_production_helper or role != "production_helper"
    }


def _stage_source_bundle(
    config: RehearsalConfig,
    revision: str,
    pair_manifest_sha256: str,
    assets: dict[str, bytes],
    hashes: dict[str, str],
    *,
    helper_source_contract: str | None = None,
) -> None:
    if helper_source_contract is not None and helper_source_contract != HOTFIX_CONTRACT:
        raise RehearsalError("helper_source_contract_invalid")
    include_production_helper = helper_source_contract == HOTFIX_CONTRACT
    names = _source_stage_names(
        revision,
        include_production_helper=include_production_helper,
    )
    if set(assets) != set(names) or set(hashes) != set(names):
        raise RehearsalError("bootstrap_assets_invalid")
    _stage_named_assets(config, names, assets)
    payload: dict[str, object] = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_manifest_sha256,
        "asset_sha256": hashes,
    }
    if helper_source_contract is not None:
        payload["helper_source_contract"] = helper_source_contract
    request = {
        "operation": "install",
        "payload": payload,
    }
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8")
    bootstrap_path = f"{INCOMING_DIRECTORY}/{names['bootstrap']}"
    response_raw = _run_fixed(
        [*_ssh_prefix(config), "sudo -n /usr/bin/python3 " + bootstrap_path],
        timeout=120,
        input_bytes=encoded,
    )
    try:
        response: object = json.loads(response_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("bootstrap_response_invalid") from exc
    if (
        not isinstance(response, dict)
        or response.get("status") != "installed"
        or response.get("reviewed_head_sha") != revision
        or response.get("reviewed_pair_manifest_sha256") != pair_manifest_sha256
        or response.get("asset_sha256") != hashes
        or (
            helper_source_contract is not None
            and (
                response.get("pull_number") != HELPER_SOURCE_PR_NUMBER
                or response.get("helper_source_contract") != helper_source_contract
            )
        )
    ):
        raise RehearsalError("bootstrap_install_failed")
    if include_production_helper and (
        response.get("production_helper_sha256") != hashes.get("production_helper")
        or not isinstance(response.get("previous_production_helper_sha256"), str)
        or DIGEST.fullmatch(response["previous_production_helper_sha256"]) is None
    ):
        raise RehearsalError("bootstrap_install_failed")


def _validate_common_host_response(
    response: dict[str, object],
    *,
    format_version: int,
    reviewed_head_sha: str,
    reviewed_pr_head_sha: str | None,
    pair_manifest_sha256: str,
    candidate_image_id: str,
    recovery_image_id: str,
) -> None:
    """Preserve v1's response shape and apply fixed-image identity checks only to v2/v3."""

    if type(format_version) is not int or format_version not in {1, 2, 3}:
        raise RehearsalError("host_response_invalid")
    invalid = (
        response.get("reviewed_head_sha") != reviewed_head_sha
        or response.get("pair_manifest_sha256") != pair_manifest_sha256
        or response.get("candidate_image_id") != candidate_image_id
        or response.get("recovery_image_id") != recovery_image_id
        or response.get("same_disposable_volume") is not True
        or response.get("production_mutation") is not False
        or response.get("candidate_container_removed") is not True
        or response.get("recovery_container_removed") is not True
        or response.get("volume_removed") is not True
        or response.get("images_retained") is not True
        or response.get("architecture") not in {"x86_64", "aarch64"}
    )
    if format_version in {2, 3}:
        invalid = invalid or (
            response.get("contract")
            != (HOTFIX_V3_CONTRACT if format_version == 3 else HOTFIX_CONTRACT)
            or response.get("candidate_revision")
            != (
                HOTFIX_V3_IMAGE_SOURCE_REVISION
                if format_version == 3
                else HOTFIX_CANDIDATE_REVISION
            )
            or response.get("candidate_source_context_sha256")
            != (
                HOTFIX_V3_IMAGE_CONTEXT_SHA256
                if format_version == 3
                else HOTFIX_CANDIDATE_CONTEXT_SHA256
            )
            or response.get("candidate_build_receipt_sha256")
            != (
                HOTFIX_V3_BUILD_RECEIPT_SHA256
                if format_version == 3
                else HOTFIX_BUILD_RECEIPT_SHA256
            )
        )
    if format_version == 3:
        invalid = invalid or (
            reviewed_pr_head_sha != HOTFIX_V3_REVIEWED_PR_HEAD_SHA
            or response.get("reviewed_pr_head_sha") != HOTFIX_V3_REVIEWED_PR_HEAD_SHA
            or response.get("reviewed_pr_lineage_verified") is not True
        )
    if invalid:
        raise RehearsalError("host_response_invalid")


def rehearse_pr_pair(
    *,
    reviewed_head_sha: str,
    candidate_image_id: str,
    candidate_source_context_sha256: str,
    recovery_image_id: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
    pair_manifest_sha256: str,
) -> dict[str, object]:
    """Run the fixed v1 PR #2 or v2 PR #11 pair through the operator helper."""

    config = RehearsalConfig.from_env()
    if reviewed_head_sha != config.reviewed_head_sha:
        raise RehearsalError("reviewed_pr_head_mismatch")
    if pair_manifest_sha256 != config.reviewed_pair_manifest_sha256:
        raise RehearsalError("reviewed_pair_manifest_mismatch")
    manifest, assets = _artifact_pair(
        reviewed_head_sha,
        candidate_image_id=candidate_image_id,
        candidate_source_context_sha256=candidate_source_context_sha256,
        recovery_image_id=recovery_image_id,
        recovery_source_context_sha256=recovery_source_context_sha256,
        recovery_overlay_sha256=recovery_overlay_sha256,
        pair_manifest_sha256=pair_manifest_sha256,
    )
    helper_source_receipt: dict[str, object] | None = None
    pr_receipt: dict[str, object] | None = None
    hotfix_pr_receipt: dict[str, object] | None = None
    if manifest.get("format_version") in {2, 3}:
        _verify_local_helper_checkout(reviewed_head_sha)
        helper_source_receipt = verify_helper_source_pull_request(reviewed_head_sha)
        hotfix_pr_receipt = verify_hotfix_pull_request(
            manifest.get("reviewed_pr_head_sha") if manifest.get("format_version") == 3 else None
        )
        if manifest.get("format_version") == 3:
            _verify_local_v3_pr_lineage(manifest["reviewed_pr_head_sha"], reviewed_head_sha)
    else:
        pr_receipt = verify_pull_request(reviewed_head_sha)
        _verify_local_reviewed_source(
            reviewed_head_sha,
            candidate_source_context_sha256=candidate_source_context_sha256,
            recovery_source_context_sha256=recovery_source_context_sha256,
            recovery_overlay_sha256=recovery_overlay_sha256,
        )
    source_assets, source_hashes = _source_bundle(
        include_production_helper=manifest.get("format_version") in {2, 3}
    )
    _ensure_incoming_directories(config)
    _stage_source_bundle(
        config,
        reviewed_head_sha,
        pair_manifest_sha256,
        source_assets,
        source_hashes,
        helper_source_contract=(
            HOTFIX_CONTRACT if manifest.get("format_version") in {2, 3} else None
        ),
    )
    try:
        _stage_assets(config, reviewed_head_sha, assets)
    except RehearsalError:
        _cleanup_staged_assets(config, reviewed_head_sha)
        raise
    request = {
        "operation": "rehearse_pr_pair",
        "payload": {
            "repository": REPOSITORY,
            "pull_number": (
                HELPER_SOURCE_PR_NUMBER if manifest.get("format_version") in {2, 3} else PULL_NUMBER
            ),
            "reviewed_head_sha": reviewed_head_sha,
            "candidate_image_id": candidate_image_id,
            "candidate_source_context_sha256": candidate_source_context_sha256,
            "recovery_image_id": recovery_image_id,
            "recovery_source_context_sha256": recovery_source_context_sha256,
            "recovery_overlay_sha256": recovery_overlay_sha256,
            "pair_manifest_sha256": pair_manifest_sha256,
            "candidate_archive_sha256": manifest["candidate"]["archive_sha256"],
            "recovery_archive_sha256": manifest["recovery"]["archive_sha256"],
            **(
                {"reviewed_pr_head_sha": manifest["reviewed_pr_head_sha"]}
                if manifest.get("format_version") == 3
                else {}
            ),
        },
    }
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8")
    try:
        response_raw = _run_fixed(
            [*_ssh_prefix(config), "sudo -n", HELPER_PATH],
            timeout=1_200,
            input_bytes=encoded,
        )
    except RehearsalError:
        _cleanup_staged_assets(config, reviewed_head_sha)
        raise
    try:
        response: object = json.loads(response_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("host_response_invalid") from exc
    if not isinstance(response, dict):
        raise RehearsalError("host_response_invalid")
    if response.get("status") != "pass":
        code = response.get("code")
        if not isinstance(code, str) or re.fullmatch(r"[a-z0-9_:-]{1,96}", code) is None:
            code = "host_rehearsal_failed"
        details = _safe_host_failure_details(response)
        raise RehearsalError(code, details=details)
    format_version = manifest.get("format_version")
    _validate_common_host_response(
        response,
        format_version=format_version,
        reviewed_head_sha=reviewed_head_sha,
        reviewed_pr_head_sha=(
            manifest.get("reviewed_pr_head_sha") if format_version == 3 else None
        ),
        pair_manifest_sha256=pair_manifest_sha256,
        candidate_image_id=candidate_image_id,
        recovery_image_id=recovery_image_id,
    )
    native_evidence: dict[str, object] = {}
    if manifest.get("format_version") in {2, 3} and (
        response.get("schema13_same_schema_verified") is not True
        or type(response.get("migration_commands_executed")) is not int
        or response.get("migration_commands_executed") != 0
        or type(response.get("restore_commands_executed")) is not int
        or response.get("restore_commands_executed") != 0
        or response.get("post_start_write_preserved") is not True
        or type(response.get("schema_after_recovery")) is not int
        or response.get("schema_after_recovery") != 13
        or response.get("production_assistant_enabled") is not False
        or response.get("production_assistant_disabled_maintenance_verified") is not True
        or response.get("recovery_process_isolation_verified") is not True
        or hotfix_pr_receipt is None
    ):
        raise RehearsalError("host_response_invalid")
    if manifest.get("format_version") in {2, 3}:
        native_evidence = _validated_native_evidence(response)
    if manifest.get("format_version") == 1 and (
        response.get("recovery_process_isolation_verified") is not True
    ):
        raise RehearsalError("host_response_invalid")
    production_baseline_value = response.get("production_baseline")
    production_baseline = (
        _validated_v2_production_baseline(production_baseline_value)
        if manifest.get("format_version") in {2, 3}
        else _validated_production_baseline(production_baseline_value)
    )
    resource_evidence = _validated_resource_evidence(response)
    result: dict[str, object] = {
        "status": "pass",
        "rehearsal": (
            "pr_bound_schema13_same_schema_hotfix"
            if manifest.get("format_version") in {2, 3}
            else "pr_bound_schema13_pair"
        ),
        "pull_request": (
            {
                "helper_source": helper_source_receipt,
                "hotfix_candidate": hotfix_pr_receipt,
            }
            if manifest.get("format_version") in {2, 3}
            else pr_receipt
        ),
        "reviewed_head_sha": reviewed_head_sha,
        "candidate_image_id": candidate_image_id,
        "candidate_source_context_sha256": candidate_source_context_sha256,
        "recovery_image_id": recovery_image_id,
        "recovery_source_context_sha256": recovery_source_context_sha256,
        "recovery_overlay_sha256": recovery_overlay_sha256,
        "pair_manifest_sha256": pair_manifest_sha256,
        "host_receipt": {
            "production_baseline": production_baseline,
            **{
                key: value
                for key, value in response.items()
                if key
                in {
                    "receipt_id",
                    "architecture",
                    "started_at",
                    "finished_at",
                    "host_memavailable_before_kib",
                    "host_memavailable_after_kib",
                    "production_health_samples",
                    "migration_backup_verified",
                    "post_migration_write_preserved",
                    "schema13_same_schema_verified",
                    "migration_commands_executed",
                    "restore_commands_executed",
                    "post_start_write_preserved",
                    "schema_after_recovery",
                    "production_assistant_enabled",
                    "production_assistant_disabled_maintenance_verified",
                    "ownership_isolation_verified",
                    "restore_guard_verified",
                    "recovery_process_isolation_verified",
                    "candidate_container_removed",
                    "recovery_container_removed",
                    "volume_removed",
                    "images_retained",
                    "native_model_id",
                    "mcp_workspace_summary_calls",
                    "native_search_source_count",
                    "simultaneous_two_owner_turns",
                }
            },
            **native_evidence,
            **resource_evidence,
        },
    }
    if manifest.get("format_version") in {2, 3}:
        result["hotfix_candidate_pull_number"] = HOTFIX_PR_NUMBER
    if manifest.get("format_version") == 3:
        result["image_source_revision"] = manifest["image_source_revision"]
        result["reviewed_pr_head_sha"] = manifest["reviewed_pr_head_sha"]
    return result


_SAFE_NATIVE_FAILURE_STAGES = {
    "input_validation",
    "model_inventory",
    "admin_step_up",
    "admin_model_policy",
    "user_consent_and_conversation_setup",
    "concurrent_turn_create",
    "turn_poll_and_search_confirmation",
    "owner_evidence_and_isolation",
    "conversation_delete_and_health",
    "acceptance_validation",
    "result_unavailable",
}
_SAFE_NATIVE_FAILURE_CONDITIONS = {
    "turn_requests_not_concurrent",
    "search_not_approved",
    "active_search_checkpoint_missing",
    "native_search_sources_missing",
    "owner0_turn_not_completed",
    "owner0_model_id_mismatch",
    "owner0_answer_empty",
    "owner0_workspace_summary_receipt_count_invalid",
    "owner0_workspace_summary_digest_mismatch",
    "owner0_selected_model_mismatch",
    "owner1_turn_not_completed",
    "owner1_model_id_mismatch",
    "owner1_answer_empty",
    "owner1_workspace_summary_receipt_count_invalid",
    "owner1_workspace_summary_digest_mismatch",
    "owner1_selected_model_mismatch",
    "owner0_conversation_delete_failed",
    "owner1_conversation_delete_failed",
    "cross_owner_access_not_denied",
    "forged_internal_mcp_not_denied",
    "worker_not_ready_after_turns",
    "supervised_app_not_reachable",
}
_SAFE_NATIVE_TURN_ERROR_CODES = {
    "worker_unavailable",
    "provider_unavailable",
    "provider_policy_changed",
    "tool_failed",
    "tool_unavailable",
    "turn_timeout",
    "turn_cancelled",
    "invalid_runtime_event",
    "runtime_restarted",
    "output_too_large",
    "empty_response",
    "sensitive_output_rejected",
    "session_revoked",
}
_SAFE_NATIVE_TURN_FAILURE_STAGES = {
    "none",
    "before_model_session_event",
    "after_model_session_event",
    "unknown_terminal",
}
_SAFE_FIXED_COMMAND_CATEGORIES = {
    "image_load",
    "image_inspect",
    "container_list",
    "container_inspect",
    "volume_create",
    "cli_run",
    "container_run",
    "container_exec",
    "fixture_seed",
    "fixture_verify_backup",
    "fixture_restore_guard",
    "fixture_marker",
    "fixture_snapshot",
    "container_remove",
    "container_stop",
    "volume_inspect",
    "volume_list",
    "volume_remove",
    "docker_version",
    "other_fixed",
}
_SAFE_CLEANUP_FAILURES = {
    "container_removal_unverified",
    "cli_container_removal_unverified",
    "network_or_volume_removal_unverified",
    "disposable_volume_retained_for_running_container",
    "staged_archive_cleanup_unverified",
    "asset_cleanup_unverified",
    "cleanup_unverified",
}


def _safe_fixed_command_failure(value: object) -> dict[str, object] | None:
    """Project only a closed command category and nonzero numeric exit status."""
    if not isinstance(value, dict) or set(value) != {"command_category", "exit_status"}:
        return None
    category = value.get("command_category")
    exit_status = value.get("exit_status")
    if (
        not isinstance(category, str)
        or category not in _SAFE_FIXED_COMMAND_CATEGORIES
        or type(exit_status) is not int
        or exit_status == 0
        or not -255 <= exit_status <= 255
    ):
        return None
    return {"command_category": category, "exit_status": exit_status}


def _safe_memory_reserve_failure(value: object) -> dict[str, object] | None:
    """Accept only a closed guard phase and its below-threshold numeric reading."""
    if not isinstance(value, dict) or set(value) != {
        "memory_reserve_phase",
        "host_memavailable_kib",
        "required_reserve_kib",
    }:
        return None
    phase = value.get("memory_reserve_phase")
    available = value.get("host_memavailable_kib")
    floor = value.get("required_reserve_kib")
    floors = {
        "preflight": START_RESERVE_KIB,
        "startup": START_RESERVE_KIB,
        "monitor": RUN_RESERVE_KIB,
        "final": RUN_RESERVE_KIB,
    }
    if (
        not isinstance(phase, str)
        or phase not in floors
        or type(available) is not int
        or type(floor) is not int
        or floor != floors[phase]
        or not 0 <= available < floor
    ):
        return None
    return {
        "memory_reserve_phase": phase,
        "host_memavailable_kib": available,
        "required_reserve_kib": floor,
    }


def _safe_host_failure_details(response: dict[str, object]) -> dict[str, object] | None:
    """Keep the existing native projection and add only typed command/receipt facts."""
    details: dict[str, object] = {}
    failure = response.get("failure")
    native_failure = _safe_native_failure(failure)
    if native_failure is not None:
        details["failure"] = native_failure
    command_failure = _safe_fixed_command_failure(failure)
    if command_failure is not None:
        details["fixed_command_failure"] = command_failure
    if response.get("code") == "host_memory_reserve_breached":
        reserve_failure = _safe_memory_reserve_failure(failure)
        if reserve_failure is not None:
            details["memory_reserve_failure"] = reserve_failure
    receipt_id = response.get("receipt_id")
    if isinstance(receipt_id, str) and re.fullmatch(r"[0-9a-f]{32}", receipt_id) is not None:
        details["host_receipt_id"] = receipt_id
    cleanup_failure = response.get("cleanup_failure")
    if isinstance(cleanup_failure, str) and cleanup_failure in _SAFE_CLEANUP_FAILURES:
        details["cleanup_failure"] = cleanup_failure
    return details or None


def _safe_native_failure(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) - {
        "failure_stage",
        "missing_conditions",
        "owners",
        "owner_evidence",
        "turn_requests_issued_concurrently",
        "search_approved",
        "active_search_scan_acknowledged",
        "same_supervised_app_reachable",
        "attached_candidate_acceptance",
        "cross_owner_conversation_status",
        "forged_internal_mcp_status",
        "builtin_search_source_count",
        "safe_error_code",
        "http_status",
    }:
        return None
    stage = value.get("failure_stage")
    missing = value.get("missing_conditions")
    if (
        not isinstance(stage, str)
        or stage not in _SAFE_NATIVE_FAILURE_STAGES
        or not isinstance(missing, list)
        or len(missing) > len(_SAFE_NATIVE_FAILURE_CONDITIONS)
        or any(item not in _SAFE_NATIVE_FAILURE_CONDITIONS for item in missing)
    ):
        return None
    safe_error_code = value.get("safe_error_code")
    if "safe_error_code" in value and (
        not isinstance(safe_error_code, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", safe_error_code) is None
    ):
        return None
    http_status = value.get("http_status")
    if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
        return None
    result: dict[str, object] = {
        "failure_stage": stage,
        "missing_conditions": missing,
    }
    if isinstance(safe_error_code, str):
        result["safe_error_code"] = safe_error_code
    if type(http_status) is int:
        result["http_status"] = http_status
    owners = value.get("owners")
    if owners is not None:
        if not isinstance(owners, list) or len(owners) > 2:
            return None
        safe_owners: list[dict[str, object]] = []
        allowed_owner = {
            "terminal_status",
            "turn_error_code",
            "turn_failure_stage",
            "model_id_matches",
            "nonempty_answer",
            "workspace_summary_digest_matches",
            "selected_model_id_matches",
            "workspace_summary_receipt_count",
            "native_search_source_count",
        }
        for owner in owners:
            if not isinstance(owner, dict) or set(owner) - allowed_owner:
                return None
            if any(
                type(owner[key]) is not bool
                for key in set(owner)
                & {
                    "model_id_matches",
                    "nonempty_answer",
                    "workspace_summary_digest_matches",
                    "selected_model_id_matches",
                }
            ):
                return None
            if any(
                type(owner[key]) is not int or not 0 <= owner[key] <= 10_000
                for key in set(owner)
                & {"workspace_summary_receipt_count", "native_search_source_count"}
            ):
                return None
            status = owner.get("terminal_status")
            if status not in {
                "running",
                "completed",
                "cancelled",
                "failed",
                "timed_out",
                "unknown",
            }:
                return None
            error_code = owner.get("turn_error_code")
            if error_code is not None and error_code not in _SAFE_NATIVE_TURN_ERROR_CODES:
                return None
            failure_stage = owner.get("turn_failure_stage")
            if failure_stage is not None and failure_stage not in _SAFE_NATIVE_TURN_FAILURE_STAGES:
                return None
            safe_owners.append(dict(owner))
        result["owners"] = safe_owners
    evidence = value.get("owner_evidence")
    if evidence is not None:
        if not isinstance(evidence, list) or len(evidence) > 2:
            return None
        allowed_evidence = {
            "owner_index",
            "terminal_status",
            "turn_error_code",
            "turn_failure_stage",
            "model_id_matches",
            "answer_nonempty",
            "workspace_summary_digest_present",
            "workspace_summary_digest_matches",
            "selected_model_id_matches",
            "assistant_message_count",
            "assistant_text_bytes",
            "workspace_summary_receipt_count",
            "selected_model_event_count",
            "native_search_source_count",
            "conversation_event_count",
        }
        safe_evidence: list[dict[str, object]] = []
        for row in evidence:
            if not isinstance(row, dict) or set(row) - allowed_evidence:
                return None
            if type(row.get("owner_index")) is not int or row["owner_index"] not in {0, 1}:
                return None
            if row.get("terminal_status") not in {
                "not_started",
                "running",
                "completed",
                "cancelled",
                "failed",
                "timed_out",
                "unknown",
            }:
                return None
            error_code = row.get("turn_error_code")
            if error_code is not None and error_code not in _SAFE_NATIVE_TURN_ERROR_CODES:
                return None
            if row.get("turn_failure_stage") not in _SAFE_NATIVE_TURN_FAILURE_STAGES:
                return None
            for key in {
                "model_id_matches",
                "answer_nonempty",
                "workspace_summary_digest_present",
                "workspace_summary_digest_matches",
                "selected_model_id_matches",
            } & set(row):
                if type(row[key]) is not bool:
                    return None
            for key in {
                "assistant_message_count",
                "assistant_text_bytes",
                "workspace_summary_receipt_count",
                "selected_model_event_count",
                "native_search_source_count",
                "conversation_event_count",
            } & set(row):
                if type(row[key]) is not int or not 0 <= row[key] <= 1_000_000:
                    return None
            safe_evidence.append(dict(row))
        result["owner_evidence"] = safe_evidence
    for key in (
        "turn_requests_issued_concurrently",
        "search_approved",
        "active_search_scan_acknowledged",
        "same_supervised_app_reachable",
        "attached_candidate_acceptance",
    ):
        if key in value:
            if type(value[key]) is not bool:
                return None
            result[key] = value[key]
    for key in (
        "cross_owner_conversation_status",
        "forged_internal_mcp_status",
        "builtin_search_source_count",
    ):
        if key in value:
            if type(value[key]) is not int or not 0 <= value[key] <= 10_000:
                return None
            result[key] = value[key]
    return result


def _cleanup_staged_assets(config: RehearsalConfig, revision: str) -> None:
    """Ask only the installed sidecar helper to unlink this SHA's fixed staged filenames."""

    request = json.dumps(
        {"operation": "cleanup_assets", "payload": {"reviewed_head_sha": revision}},
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        _run_fixed([*_ssh_prefix(config), "sudo -n", HELPER_PATH], timeout=30, input_bytes=request)
    except RehearsalError:
        return
