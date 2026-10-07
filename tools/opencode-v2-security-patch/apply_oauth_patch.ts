#!/usr/bin/env bun
/** Apply the separately hash-pinned native OAuth broker transform. */
import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import { applyOAuthHandoffPatch } from "./oauth-handoff.ts"

const sourceRoot = process.argv[2]
if (!sourceRoot || process.argv.length !== 3) throw new Error("expected one fixed source root")

const transformed = await applyOAuthHandoffPatch(sourceRoot)
const broker = await readFile(new URL("./oauth-broker.ts", import.meta.url))
const callback = await readFile(new URL("./oauth-callback.ts", import.meta.url))
const sourceSet = createHash("sha256")
  .update(
    JSON.stringify(
      Object.entries(transformed).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
    ),
  )
  .digest("hex")
console.log(
  JSON.stringify({
    oauth_transformed_source_set_sha256: sourceSet,
    oauth_broker_sha256: createHash("sha256").update(broker).digest("hex"),
    oauth_callback_sha256: createHash("sha256").update(callback).digest("hex"),
  }),
)
