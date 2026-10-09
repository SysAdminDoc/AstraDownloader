"""The installer stays responsive, survives close attempts and reports failure."""

import threading
from unittest import mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialog
from setup_dialog import SetupDialog, run_setup_dialog
from shiboken6 import isValid

from astra_downloader import APP_VERSION


def test_operation_runs_off_thread_and_success_closes(qtbot):
    entered, release = threading.Event(), threading.Event()
    observed = {}

    def operation(progress):
        observed["thread"] = QThread.currentThread()
        progress("Copying the application…")
        entered.set()
        assert release.wait(3)
        return {"installed": True}

    dialog = SetupDialog(operation, title="Installing Astra Downloader", version=APP_VERSION)
    qtbot.addWidget(dialog)
    dialog.show()
    try:
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: dialog.status.text() == "Copying the application…")
        assert observed["thread"] != QApplication.instance().thread()
        assert not dialog.close_button.isVisible()
        assert dialog.progress.maximum() == 0
        with mock.patch("setup_dialog.tr", side_effect=lambda text: f"translated: {text}"):
            dialog._show_progress("Verifying the new app...")
            assert dialog.status.text() == "translated: Verifying the new app..."
            dialog._show_progress("Custom operation detail")
            assert dialog.status.text() == "Custom operation detail"
        dialog.close()
        dialog.reject()
        dialog.done(QDialog.DialogCode.Rejected)
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        assert isValid(dialog) and dialog.isVisible()
        ticked = []
        QTimer.singleShot(0, lambda: ticked.append(True))
        qtbot.waitUntil(lambda: bool(ticked))
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog._complete)
    assert dialog.operation_result == {"installed": True}
    assert not dialog.isVisible()


@pytest.mark.parametrize("error_type", (PermissionError, SystemExit))
def test_failure_shows_actionable_text_until_closed(qtbot, error_type):
    def operation(progress):
        progress("Replacing application files…")
        raise error_type("Close the running copy, then start this installer again.")

    dialog = SetupDialog(operation, title="Updating Astra Downloader", version=APP_VERSION)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._complete)
    assert dialog.isVisible()
    assert dialog.close_button.isVisible()
    assert dialog.details.toPlainText() == "Close the running copy, then start this installer again."
    assert not dialog.progress.isVisible()
    dialog.close_button.click()
    assert not dialog.isVisible()


def test_runner_returns_value_and_raises_after_error_close(qapp):
    assert run_setup_dialog(lambda progress: 42, title="Installing Astra Downloader", version=APP_VERSION) == 42

    def close_error_dialog():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, SetupDialog) and dialog.close_button.isVisible():
            dialog.close_button.click()

    timer = QTimer()
    timer.timeout.connect(close_error_dialog)
    timer.start(5)
    try:
        with pytest.raises(RuntimeError, match="Disk is full"):
            run_setup_dialog(
                lambda progress: (_ for _ in ()).throw(OSError("Disk is full. Free space and retry.")),
                title="Updating Astra Downloader", version=APP_VERSION,
            )
    finally:
        timer.stop()


def test_runner_refuses_ui_creation_from_background_thread(qapp):
    failures = []

    def invoke():
        try:
            run_setup_dialog(lambda progress: True, title="Installing Astra Downloader", version=APP_VERSION)
        except RuntimeError as error:
            failures.append(str(error))

    thread = threading.Thread(target=invoke)
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert failures == ["The setup dialog must run on the application thread."]
