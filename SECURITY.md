# Security Policy

## Supported Versions

| Version | Support status |
|---------|----------------|
| v2.x | Supported |
| v1.x, released from the Astra Deck repository | Best effort only; update to the latest release first unless the report is about the upgrade path itself |

## Report a Vulnerability

Use GitHub private vulnerability reporting from the repository's
[Security tab](https://github.com/SysAdminDoc/AstraDownloader/security/advisories/new).
Do not open a public issue for vulnerabilities, suspected credential exposure,
exploit chains, or private logs.

Include:

- Affected Astra Downloader version or commit (`/health` reports the running
  version, and the About line in the rail shows it).
- Operating system and how it was installed (release executable or source).
- Short impact summary and the vulnerable behaviour.
- Minimal reproduction steps, with cookies, tokens, account data, and local
  paths redacted.

Do not include:

- Cookies, session tokens, API keys, or the contents of a site sign-in jar.
- Working exploit payloads beyond the minimum needed to explain impact.
- Full logs or unredacted local filesystem paths. The in-app **Review
  diagnostics** action produces a redacted payload — prefer that.

Public issues remain appropriate for non-sensitive bugs, usability problems,
documentation mistakes, and feature requests.

## Response Expectations

- Acknowledgement within 5 business days.
- A fix or a documented mitigation for confirmed high-severity reports in the
  next release.
- Credit in the changelog on request.

## Scope Notes

Astra Downloader binds to loopback only. Flask accepts only canonical
`127.0.0.1`, `localhost`, or `[::1]` Host authorities with valid ports, which
closes DNS rebinding before a route runs. Requests must carry the session
token.

These are known and accepted properties, not vulnerabilities:

- **Anything on the machine that can read the token can drive the server.**
  The trust boundary is the local user account, not the process.
- **Stored site credentials travel to yt-dlp on its command line.**
  `--username`/`--password`/`--video-password` are visible in
  `Win32_Process.CommandLine` to any process running as the same user, and
  to endpoint software that records command lines. This is a deliberate
  consequence of the boundary above: the alternatives all hand the secret to
  something worse — the `--netrc` family is refused at the spawn boundary
  because a netrc file is a durable, format-ambiguous credential store, and
  yt-dlp offers no stdin credential channel. The store itself is ACL'd to
  the owner and the values are redacted from history, diagnostics, logs, the
  API, and the in-app command inspector.
- **URL policy is literal-only.** Private-network targets are refused by
  inspecting the URL, not by resolving it: resolving at validation time proves
  nothing about resolution a millisecond later. The accepted residual is a
  public DNS name pointed at a private address — DNS itself is not a boundary
  the local user account model defends. See
  [`docs/yt-dlp-cookie-threat-model.md`](docs/yt-dlp-cookie-threat-model.md).
- **Client-supplied output paths are confined.** A `/download` request may
  name an output directory, but it is accepted only inside the configured
  download roots (plus the reviewed extra roots), resolved through symlinks
  and checked before any directory is created — a compromised extension
  cannot hand the server an arbitrary absolute path and watch it write there.
- **The executable is unsigned by design.** Verify the published SHA-256
  sidecar against the downloaded binary rather than relying on a signature.
  SmartScreen will warn on first run; that is expected, not a compromise
  indicator. See the README for the verification command.
- **No external downloader is offered, and none can be requested.** aria2c,
  curl and the rest are refused at the process boundary along with `--exec`,
  `--exec-before-download` and the `--netrc` family. This is deliberate:
  those options hand the transfer, or a command line, to a process this
  program does not control, and 2026 brought code-execution advisories
  against two of the common choices (CVE-2026-50574, CVE-2026-50019). yt-dlp
  itself has had its own run of advisories in the same period — GHSA-6v4j-43gg-vj32,
  GHSA-c6mh-fpjc-4pr3 and GHSA-f7j3-774f-rfhj landed on 2026-06-09, and
  CVE-2026-55404 (`--write-link` shortcut injection) on 2026-07-04. Astra
  Downloader tracks the pinned release forward and denies every link-file flag
  at the process boundary regardless. The
  refusal is enforced in `validate_ytdlp_spawn_args` and pinned by test, so
  a future builder change cannot reintroduce one by accident.
- **yt-dlp is spawned with its plugin directories disabled.**
  `--ignore-config` stops configuration *files* only; plugin directories are
  a separate mechanism with their own defaults, so without
  `--no-plugin-dirs` any Python under `%APPDATA%\yt-dlp\plugins` would be
  imported and executed inside the spawned process. That is consistent with
  refusing `--exec`, and it means a yt-dlp plugin you install deliberately
  will not be loaded by Astra Downloader. `--no-remote-components` is passed
  alongside it.

## Third-Party Components

Astra Downloader drives yt-dlp and ffmpeg. Vulnerabilities in those belong
upstream — report them to their projects. Report to us if Astra Downloader
pins a version that is known-vulnerable, or invokes them in a way that creates
an issue they do not have on their own.

The optional SponsorBlock integration uses SponsorBlock's data/API under the
[CC BY-NC-SA 4.0 licence](https://sponsor.ajay.app/). The Settings UI provides
the required attribution link; Astra Downloader's own code remains MIT-licensed.
