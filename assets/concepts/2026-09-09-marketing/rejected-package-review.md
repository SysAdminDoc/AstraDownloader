# Package review notes

The first v2.15.1 candidate built successfully but failed to import Qt when launched from either distribution layout. It is not the published package.

The native dependency inventory showed an ICU library from an unrelated document tool on the build machine's PATH. That library exported version-suffixed symbols instead of the Windows ICU entry points Qt expected. Both candidates were launched only on a private desktop with offscreen Qt; no active desktop was used.

The builder now restricts the child process's PATH to the selected Python environment and Windows directories. It also rejects collected native libraries from unreviewed directories. Regression tests cover the environment boundary and a similarly named sibling directory.

Earlier source-capture iterations are retained as well. The first had an incorrect card-count assertion. The second rendered missing-glyph boxes because the Windows offscreen backend hadn't loaded its fonts. Explicitly loading the installed Segoe UI family and checking glyph support corrected the capture, not the product interface.

The larger fixture suite initially stopped at the stored-sign-in error scenario because its expected text omitted the recovery sentence already present in the app. The assertion now checks the full message. The rejected screenshots and the completed 85-state run remain in separate folders.
