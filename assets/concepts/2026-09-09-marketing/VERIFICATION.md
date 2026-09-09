# Astra Downloader v2.15.1 review record

Checked on Windows 11 x64 on September 9, 2026. The screenshots and package checks use disposable profiles, not a personal browser session or media library.

## What was checked

| Check | Result |
| --- | --- |
| Python tests | 1,326 passed. One symlink test was skipped because this Windows account can't create symlinks. |
| Node tests | All 54 passed. |
| Qt fixture review | All 85 states rendered and passed their assertions. |
| One-file executable | 125 review checks passed, with seven captures from the frozen app. |
| Portable executable | 125 review checks passed, with seven captures from the extracted release ZIP. |
| README layout | Dark, light and 390-pixel-wide renders had no horizontal overflow or missing local images. |
| Original-source archive | Every one of its 97 files matches the original Git blob. |
| Original icon | Unchanged. Reviewed at 16, 24, 32, 48, 64 and 128 pixels on both surface colors. |

The packaged checks confirmed first-run destination persistence, page navigation and rendered queue cards. They also checked that no server or instance listener started and no helpers were downloaded. The example queue is interface test data, not a benchmark.

## Real download check

Separately from the screenshots, the application's download manager fetched MDN's public [flower video](https://mdn.github.io/shared-assets/videos/flower.mp4) into a disposable folder. No account was used. FFmpeg decoded the entire resulting MP4 successfully: 5.055 seconds, 960 by 540 pixels, H.264 video and AAC audio.

The output was 1,128,375 bytes. Its SHA-256 was `0cd83d944a6ca7822b4a8306cecc60a36e859b041f6702c6a1ad9ead78924451`. The sample itself isn't redistributed here. This check establishes one public-link download, not compatibility with every supported site.

An earlier public test URL returned a 403 challenge. The challenge wasn't bypassed; a different public sample was used. The rejected initial Windows packages are described in [package review notes](rejected-package-review.md).

## Package identity

| File | SHA-256 |
| --- | --- |
| `AstraDownloader.exe` | `2cbde09e26087fc07075d85bfef4273af5bbdfae148b0a73305998ab050a0b55` |
| `AstraDownloader-onedir.zip` | `2a0ff287ae5d6201750617f73ecee0c23ecf2bb12d29cd672e1d91358ebfad5c` |

Both layouts were built with the pinned release interpreter after correcting the native-library search-path collision. Their provenance was staged together. See the [build guide](../../../docs/BUILDING.md) for the process and the release's checksum sidecars for the downloadable files.

## Limits

These builds are unsigned. The review didn't validate a managed installation, browser-extension pairing, account-gated downloads or live subscription delivery. Offscreen captures don't establish native-display accessibility or high-DPI behavior. No GitHub Settings social-preview upload is claimed; the share cards are saved as reusable assets.
