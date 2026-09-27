data "external" "source_gate" {
  # Keep this program path and query shape fixed. The script rejects dirty trees, repository
  # changes, stale remote main, unreviewed revisions, and non-regular source files.
  program = [
    "/usr/bin/env",
    "-i",
    "PATH=/usr/bin:/bin",
    "GIT_CONFIG_GLOBAL=/dev/null",
    "GIT_CONFIG_NOSYSTEM=1",
    "GIT_TERMINAL_PROMPT=0",
    "/usr/bin/bash",
    "${path.module}/verify-source.sh",
  ]

  query = {
    reviewed_revision = var.reviewed_revision
  }
}

data "external" "source_gate_apply" {
  # timestamp() is unknown while planning a saved plan. That forces this second gate to run
  # during apply, rechecking the checkout immediately before a managed resource can change.
  program = [
    "/usr/bin/env",
    "-i",
    "PATH=/usr/bin:/bin",
    "GIT_CONFIG_GLOBAL=/dev/null",
    "GIT_CONFIG_NOSYSTEM=1",
    "GIT_TERMINAL_PROMPT=0",
    "/usr/bin/bash",
    "${path.module}/verify-source.sh",
  ]

  query = {
    reviewed_revision = var.reviewed_revision
    apply_nonce       = timestamp()
  }
}
