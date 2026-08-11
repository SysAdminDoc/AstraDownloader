# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Actionable Items

## Research-Driven Additions

Filed 2026-08-11. Findings were made against `1428bc5` and **re-verified against
`2811827`** after the intervening 12 commits; everything already fixed there was
dropped rather than filed. Line numbers are from `2811827`.

### P2

- [ ] P2 — Publish a lock file and an SBOM beside the release
  Why: The license gate's unresolved entries and the release's missing
  provenance are the same problem, and the standards that fix both landed in
  2026.
  Evidence: PEP 751 is **Final**; `pylock.toml` is installable by pip 26.1+
  (`pip install -r pylock.toml`) and consumable in-process via `packaging`
  26.3's `Pylock.select()`. pip 26.0/26.1 added `--uploaded-prior-to` (relative
  durations like `P3D` since 26.1), which refuses packages published inside the
  window when typosquats and compromised releases are normally caught. CISA's
  **2026 Minimum Elements for an SBOM** (2026-07-29) supersedes NTIA 2021 and
  adds component hash, license, tool name and generation context to the required
  fields; CycloneDX and SPDX both satisfy it. The repo already builds an
  inventory (`scripts/companion-license-inventory.js`) and already runs
  pip-audit (`scripts/audit-python-deps.js`) — the missing pieces are a
  published lock artifact and a standard serialization. Depends on the release
  item for somewhere to publish them.
  Touches: `scripts/audit-python-deps.js`,
  `scripts/companion-license-inventory.js`,
  `scripts/stage-companion-release.js`,
  `astra_downloader/constraints-release.txt`
  Acceptance: a release publishes `pylock.toml` plus a CycloneDX JSON SBOM
  carrying every field CISA's 2026 minimum elements require; the release resolve
  uses a cooldown; the staging gate fails when the SBOM does not describe the
  staged artifact.
  Complexity: M

### P3

- [ ] P3 — Close the second batch of smaller gaps
  Why: Individually minor, each is a concrete wrong behaviour with a known fix.
  Evidence and scope, each verified at `2811827`:
  (a) `/download` truncates cookies to a hardcoded 200 with no warning and no
  field in the response (`routes.py:670`), while the sign-in store accepts
  `MAX_SITE_LOGIN_COOKIES` = **400** (`download.py:1041`) — so a jar the store
  keeps whole is halved on the download path and the only symptom the user sees
  is an authentication failure.
  (b) `_precondition_cache` (`download.py:3448`) now has its own lock and a 2 s
  read TTL (`:6786`, `:6808`) but still has **no eviction** — one entry per URL
  that ever produced a `sign-in-required` failure, retained for the process
  lifetime of a tray app that runs for days, emptied only by an explicit
  `clear()`.
  (c) Scan intervals drift by the scan duration every cycle: `finish_scan` sets
  `record["nextScanAt"] = now + intervalMinutes * 60` (`subscriptions.py:763`)
  from a clock read after the scan finished, so a 2-minute scan on an hourly
  subscription slips ~48 minutes a day.
  (d) `archive_entries()` deep-copies the entire archive under the store lock,
  and the retry-exhausted branch calls it once per candidate
  (`subscriptions.py:1231`) to read two fields of one entry.
  (e) `SERVICE_API_VERSION = 2` is advertised in `/health` and read **nowhere**
  in Astra Deck (0 hits for `apiVersion`/`api_version` in
  `extension/ytkit.js`), so two independently-versioned products that share a
  gate-checked port catalogue have no version handshake at all.
  Touches: `astra_downloader/routes.py`, `astra_downloader/download.py`,
  `astra_downloader/subscriptions.py`
  Acceptance: each sub-item is fixed with a test, or explicitly recorded as
  accepted in `SECURITY.md` where it is a deliberate property.
  Complexity: M
