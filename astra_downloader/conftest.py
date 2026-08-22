"""Test-run isolation for the companion suite.

The suite exercises the REAL DownloadManager / updater wiring, whose logger
is ``astra_downloader.write_persistent_log``. Without redirection every run
appended fabricated failure lines ("updater exploded", "disk full",
"SHA-256 mismatch") to the production ``%LOCALAPPDATA%/AstraDownloader/
server.log`` — growing it and poisoning any later support/debug read.
``write_persistent_log`` binds ``LOG_PATH`` late specifically so this
fixture can point the module globals at a per-run temp file.

``INSTALL_DIR`` is redirected for the same reason and it is not optional:
``DownloadManagerCore`` roots the site-login store there, so a test that
builds a real manager and imports a fixture cookie wrote
``site-logins/x.com.txt`` into the user's live install — a fabricated sign-in
that would then be listed in the GUI and attached to real downloads for that
site. The dependency reads the module global on each call, so redirecting it
here covers every manager the suite constructs.

The JavaScript runtime paths are redirected too, and they need their own
line because redirecting ``INSTALL_DIR`` does not reach them: ``DENO_PATH``
and ``QUICKJS_PATH`` are derived from it at import, so they keep pointing at
the live install. That made runtime tests depend on whether the developer's
own machine happened to have a runtime provisioned — a test asserting "no
runtime is available" passed only because this box had none.
"""

import os
from pathlib import Path

import pytest


# A full run is the product's regression contract. This floor catches a
# missing optional dependency, a Qt bootstrap failure, or an accidentally
# deleted test group even when pytest would otherwise report a green run.
MIN_FULL_SUITE_EXECUTED_TESTS = 1080

_executed_nodeids = set()
_skipped_nodeids = {}
_TEST_ROOT = Path(__file__).resolve().parent
_FULL_SUITE_TARGETS = frozenset({_TEST_ROOT, _TEST_ROOT.parent})


def _is_full_suite_run(config):
    """Return True only for an unfiltered, executable suite run."""
    option = config.option
    if any((
        getattr(option, "collectonly", False),
        getattr(option, "keyword", ""),
        getattr(option, "markexpr", ""),
        getattr(option, "lf", False),
        getattr(option, "failedfirst", False),
        getattr(option, "newfirst", False),
        getattr(option, "stepwise", False),
        getattr(option, "ignore", None),
        getattr(option, "ignore_glob", None),
        getattr(option, "deselect", None),
    )):
        return False

    invocation_dir = Path(config.invocation_params.dir).resolve()
    collection_targets = getattr(config, "args", None)
    if collection_targets is None:
        collection_targets = (
            argument for argument in config.invocation_params.args
            if not str(argument).startswith("-")
        )
    for argument in collection_targets:
        text = str(argument)
        if "::" in text:
            return False
        target = Path(text)
        if not target.is_absolute():
            target = invocation_dir / target
        if target.resolve() not in _FULL_SUITE_TARGETS:
            return False
    return True


def _skipped_group(reason):
    normalized = str(reason).casefold()
    if "yt-dlp" in normalized or "yt_dlp" in normalized:
        return "yt-dlp integration"
    if any(token in normalized for token in ("qapplication", "pyside6", "qt gui")):
        return "Qt GUI"
    return "other skipped tests"


def _execution_floor_message(executed, minimum, skipped):
    groups = {}
    for reason in skipped.values():
        group = _skipped_group(reason)
        groups[group] = groups.get(group, 0) + 1
    if groups:
        detail = ", ".join(
            f"{name} ({count})" for name, count in sorted(groups.items())
        )
    else:
        detail = "none recorded; check collection and early-stop settings"
    return (
        f"Executed-test floor missed: {executed} ran; at least {minimum} are "
        f"required. Skipped groups: {detail}."
    )


def pytest_sessionstart(session):
    del session
    _executed_nodeids.clear()
    _skipped_nodeids.clear()


def pytest_runtest_logreport(report):
    if report.when == "call" and not report.skipped:
        _executed_nodeids.add(report.nodeid)
    elif report.skipped:
        reason = report.longrepr
        if isinstance(reason, tuple) and len(reason) >= 3:
            reason = reason[2]
        _skipped_nodeids[report.nodeid] = str(reason)


def pytest_sessionfinish(session, exitstatus):
    del exitstatus
    config = session.config
    if hasattr(config, "workerinput") or not _is_full_suite_run(config):
        return
    executed = len(_executed_nodeids)
    if executed >= MIN_FULL_SUITE_EXECUTED_TESTS:
        return
    message = _execution_floor_message(
        executed, MIN_FULL_SUITE_EXECUTED_TESTS, _skipped_nodeids
    )
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "TEST EXECUTION FLOOR FAILED", red=True)
        reporter.write_line(message, red=True)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


# The suite constructs real windows as part of its GUI coverage. Keep those
# windows off the operator's display by default; an explicit opt-out is useful
# when a maintainer is deliberately checking native platform rendering.
if not os.environ.get("ASTRA_DOWNLOADER_ALLOW_ONSCREEN"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Module globals the suite redirects, and the subdirectory each one takes
# under the temporary install.
_REDIRECTED_INSTALL_PATHS = (
    ("DENO_DIR", ("deno",)),
    ("DENO_PATH", ("deno", "deno.exe")),
    ("QUICKJS_DIR", ("quickjs",)),
    ("QUICKJS_PATH", ("quickjs", "qjs.exe")),
    ("NATIVE_HOST_DIR", ("native-hosts",)),
)


@pytest.fixture(autouse=True, scope="session")
def _redirect_persistent_state(tmp_path_factory):
    import astra_downloader as ad

    log_dir = tmp_path_factory.mktemp("astra-test-logs")
    install_dir = tmp_path_factory.mktemp("astra-test-install")
    original_log, original_crash = ad.LOG_PATH, ad.CRASH_LOG_PATH
    original_install = ad.INSTALL_DIR
    originals = {name: getattr(ad, name) for name, _ in _REDIRECTED_INSTALL_PATHS}
    ad.LOG_PATH = log_dir / "server.log"
    ad.CRASH_LOG_PATH = log_dir / "crash.log"
    ad.INSTALL_DIR = install_dir
    for name, parts in _REDIRECTED_INSTALL_PATHS:
        setattr(ad, name, install_dir.joinpath(*parts))
    yield
    ad.LOG_PATH = original_log
    ad.CRASH_LOG_PATH = original_crash
    ad.INSTALL_DIR = original_install
    for name, value in originals.items():
        setattr(ad, name, value)
