# Ponytail checkout provenance

This directory is the minimum runtime closure of the official Ponytail
OpenCode checkout integration. It is not installed from npm and it does not
configure or invoke Ponytail MCP.

- Upstream: <https://github.com/DietrichGebert/ponytail>
- Immutable source commit: `16f29800fd2681bdf24f3eb4ccffe38be3baec6b`
- Immutable raw base: <https://raw.githubusercontent.com/DietrichGebert/ponytail/16f29800fd2681bdf24f3eb4ccffe38be3baec6b/>
- Source verification: GitHub's commit API returned that exact SHA with a valid
  signature on 2026-07-30.
- License: [MIT](./LICENSE), copied from upstream.

The files below retain their immutable upstream sources, except for the two-line
broker-prompt exclusion in `.opencode/plugins/ponytail.mjs`. The focused checkout
test removes only that exact guard before comparing its upstream hash and tests
that the canonical broker prompt is unchanged by the transform.
`upstream blob` is Git's upstream blob SHA-1; `SHA-256` is the upstream file
content hash. `package.json` is a local shim: it scopes the vendored
CommonJS hooks below this repository's ESM extension package without placing a
package manifest beside the configured plugin entrypoint.

| Vendored path | Upstream path | Upstream blob | SHA-256 |
| --- | --- | --- | --- |
| `.opencode/plugins/ponytail.mjs` | `.opencode/plugins/ponytail.mjs` | `aa165bd4e3a8f487f56e1364bc27bc745b43cf26` | `e9e2214149ace3e589a584a27136bf5bd9da558fbad948f8cf1d3bc2c50d3828` |
| `.opencode/plugins/ponytail-frontmatter.cjs` | `.opencode/plugins/ponytail-frontmatter.cjs` | `1145929b65e6d02ea10d4072d1d1c8fc05246bbd` | `36073b0749a62bebadb22c01b7fc018d063fb20b337591269008051151a1513d` |
| `hooks/ponytail-instructions.js` | `hooks/ponytail-instructions.js` | `3ec3980a08d9565602020e6789f1759d9e2e52e1` | `23c050103f28dbe6bad953ae21d98cd06d720a20f33d4716e9de419f947d495e` |
| `hooks/ponytail-config.js` | `hooks/ponytail-config.js` | `9ba7fdc2e7853aa296507731f6ed2b7fcbcd0bff` | `0a8daf96cf9ac703dc4cb7b5065253567e513c951d60b8eb94a0fe727514aeca` |
| `skills/ponytail/SKILL.md` | `skills/ponytail/SKILL.md` | `02c0712c86277d49d18a77da3a2b825657bf02d1` | `1316a2f3f95741d2300b116fe0c2d81ce4a9568656ed0a62643f54aaf09957f2` |
| `skills/ponytail-audit/SKILL.md` | `skills/ponytail-audit/SKILL.md` | `5582d10335daff5b5947f9b77927fbc97f2047f3` | `5560b8e383dbe2ddfddc873a1e2bf2e586e23e0cd7d995537482b2315331f6d1` |
| `skills/ponytail-debt/SKILL.md` | `skills/ponytail-debt/SKILL.md` | `ecbc0ca8161b25ced3b4f728398c2ec33988a777` | `c84fba75f0ca12bfe83f9a78ea02fd125c5dd3f1fbb18124105a489937f284e6` |
| `skills/ponytail-gain/SKILL.md` | `skills/ponytail-gain/SKILL.md` | `012e37b6bf31da1ed4bf936ec8aff53974d5291e` | `24e01d1c9715cb136ba1c4f1e52a95940c0193558b876828e537736480d6408b` |
| `skills/ponytail-help/SKILL.md` | `skills/ponytail-help/SKILL.md` | `ba145c0ebb7c7e5682bb2f36047af3bf2030d470` | `2264d1615117b02b0fd5a69ec84cd2757006471a78e4d6c22eed6d581c1d37a4` |
| `skills/ponytail-review/SKILL.md` | `skills/ponytail-review/SKILL.md` | `e137a855bd87119a4517895a1000a59b0999e1b8` | `40df33b58fc6ef889b93585733feb9566b76e9586efa7f376785c1e995197ac0` |
| `.opencode/command/ponytail.md` | `.opencode/command/ponytail.md` | `7a6892b3b36ac729594920eac28ca2f4cd9b8409` | `800919b5c7b53f05e9adb96e5978818f3b5cd9137bc2df35b1575590d5464f14` |
| `.opencode/command/ponytail-audit.md` | `.opencode/command/ponytail-audit.md` | `4722747fe4c874466e4e4798e4e3d2853a83f4ca` | `6278f820b117a6a57e4c0b013906e06fe4719652e6adc4b9a1b868d6bd1ba6f2` |
| `.opencode/command/ponytail-debt.md` | `.opencode/command/ponytail-debt.md` | `d853778ea9bde8b57e2c015bd4dbed23a9a36213` | `ddbadb1f484a1ecc54ed577b80aa3f7b326ccd1ae2a35159652a52221eb31301` |
| `.opencode/command/ponytail-gain.md` | `.opencode/command/ponytail-gain.md` | `9243a0e980ced41984a3b4170e57cf62ee407eb8` | `33514a67319e30072e1daeef336b4f4af8de31ef25595a23353f0719004189b2` |
| `.opencode/command/ponytail-help.md` | `.opencode/command/ponytail-help.md` | `d1751759cd5ef5d7bc7e1c0bd18fe25e3214c2ca` | `3052afd5cc1ea528d9405729b2620d1b81c36ca3287ec1ae964a68d6feb4c178` |
| `.opencode/command/ponytail-review.md` | `.opencode/command/ponytail-review.md` | `119cda5f3b5e717bf2b165d486cd5a1c255d5989` | `ff09bd42b1d23bd3e3919c6b7ab4710c0a71b04e23c0fc30fb3c1b1b50451485` |
| `LICENSE` | `LICENSE` | `715d483338cea4365f0d91a27799cf61226d6bcf` | `fb1bc6909ac3ef82d5c22106e32ef682b0cff66788fa915fb9b53b15c9d2f3ab` |

The configured adapter is deliberately outside the worktree's
`.opencode/plugins/` discovery root. Its `ponytail-frontmatter.cjs` companion
therefore remains a runtime dependency only and cannot be independently
auto-discovered as a plugin by OpenCode 1.18.9's legacy loader.
