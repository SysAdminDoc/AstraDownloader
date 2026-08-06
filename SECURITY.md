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

Astra Downloader binds to loopback only and rejects any request whose `Host`
header is not loopback, which closes DNS rebinding. Requests must carry the
session token.

These are known and accepted properties, not vulnerabilities:

- **Anything on the machine that can read the token can drive the server.**
  The trust boundary is the local user account, not the process.
- **URL policy is literal-only.** Private-network targets are refused by
  inspecting the URL, not by resolving it: resolving at validation time proves
  nothing about resolution a millisecond later. See
  [`docs/yt-dlp-cookie-threat-model.md`](docs/yt-dlp-cookie-threat-model.md).
- **The executable is unsigned by design.** Verify the published SHA-256
  sidecar against the downloaded binary rather than relying on a signature.

## Third-Party Components

Astra Downloader drives yt-dlp and ffmpeg. Vulnerabilities in those belong
upstream — report them to their projects. Report to us if Astra Downloader
pins a version that is known-vulnerable, or invokes them in a way that creates
an issue they do not have on their own.
