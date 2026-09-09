# Building and checking Astra Downloader v2.15.1

[Back to the project](../README.md)

Builds run locally on Windows x64. The release environment uses CPython 3.13 and the reviewed dependency graph, including PyInstaller. A system Python installation with different transitive versions is rejected by the builder.

## Release environment

```powershell
py -3.13 -m venv .release-venv
.\.release-venv\Scripts\python.exe -m pip install --require-virtualenv -r astra_downloader/constraints-release.txt
.\.release-venv\Scripts\python.exe astra_downloader/build.py
```

The constraints file lists the exact reviewed graph. The builder checks installed versions and active dependency edges against it before producing anything. It builds both `AstraDownloader.exe` and `AstraDownloader-onedir.zip`, with separate SHA-256 sidecars. Existing build outputs are cleaned first.

The build subprocess uses only the active Python environment and Windows system directories for its executable search path. Native-library origins are checked after collection. This prevents an unrelated tool's DLL from entering a release merely because its folder appeared on the caller's PATH.

The portable archive leaves the Qt libraries replaceable. Keep both layouts available at the same version, with their shared build metadata. Distribution obligations are recorded in the [license policy](../astra_downloader/license-policy.json); do not infer a bundled library's license from the app's MIT license.

```powershell
npm run release:stage
```

Staging resolves pinned helper metadata, writes the CycloneDX SBOM and PEP 751 lock, and validates the complete candidate before replacing the staged release. A failed helper, hash, inventory or provenance check leaves the previous staged set unchanged.

These builds aren't Authenticode-signed. Do not describe a checksum as a publisher signature. If a signing certificate is available for a later release, sign before generating final hashes and staging the release.

## Local checks

Use a Git checkout with tags for the full gate. Node 22+ and Python 3.13 must be available; `npm run check` invokes `py -3.13`. The development interpreter needs the app requirements and pytest, pytest-xdist, pytest-qt, pytest-asyncio and pip-audit. Keep development tools separate from the reviewed release environment.

```powershell
npm test
py -3.13 -m pytest -rs       # 1327 tests collected; the gate verifies this count
npm run check
npm run smoke:gui
```

The command runs all nine gates: both test suites, port-catalogue agreement, catch-reason checks, license inventory, site registry, translations, version agreement and dependency auditing. Missing interpreters count as a failure, not a pass.

Version agreement includes the package, app constant, README badge, newest changelog entry, Scoop manifest and a named regression test. It also requires a local `vX.Y.Z` tag. For a new release, test the candidate, make the local release commit and tag, then run the complete gate **before pushing**. The source ZIP has no Git metadata and cannot establish tag agreement by itself.

## Isolated package review

The packaged app supports a bounded capture run:

```powershell
.\AstraDownloader.exe --review-dir C:\temp\astra-review-new
```

Choose a directory that doesn't exist. The mode creates its own profile, forces Qt's offscreen backend before Qt loads, captures real widgets, writes `review.json` and exits. Seeded queue entries are labeled as examples in the report. No tools are downloaded, no media transfer starts, no API listens, and no browser or system integration is registered. It doesn't read the system clipboard.

Run this on each distribution layout. Review the images, not just the process exit code. A source-window render doesn't establish that the executable contains every required module.

The larger `smoke:gui` suite covers 85 fixture states, including small layouts and translated pages. It writes under `build/companion-ui-smoke`. Preserve earlier captures before regenerating them if they are part of a review record.

For a network smoke test, set `ASTRA_YTDLP_SMOKE_URL` to a small public clip you have permission to download, then run `npm run smoke:yt-dlp` or `npm run smoke:yt-dlp:managed`. Don't use a private browser session as test data. Keep a record of the source, its license and the output check.
