"""Responsive startup progress for installing and updating the companion."""

from threading import current_thread, main_thread

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

try:
    from .gui_support import tr
    from .i18n import install_companion_translator
except ImportError:  # Flat source-path compatibility.
    from gui_support import tr
    from i18n import install_companion_translator


class _SetupWorker(QThread):
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.value = None
        self.error = None

    def run(self):
        try:
            self.value = self.operation(self.progress.emit)
        except BaseException as error:  # noqa: BLE001
            # reason: report every worker failure, including an operation calling sys.exit.
            self.error = error


class SetupDialog(QDialog):
    """Run one operation without permitting the active worker to be destroyed."""

    def __init__(self, operation, *, title, version, icon_path=None, parent=None):
        super().__init__(parent)
        self._complete = False
        self.operation_result = None
        self.error_message = ""
        titles = {
            "Installing Astra Downloader": tr("Installing Astra Downloader"),
            "Updating Astra Downloader": tr("Updating Astra Downloader"),
        }
        heading = titles.get(title, tr(title))
        self.setWindowTitle(heading)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedWidth(560)
        self.setStyleSheet("""
            QDialog { background: #101318; color: #f2f0ed; }
            QLabel { background: transparent; color: #f2f0ed; font: 14px 'Segoe UI'; }
            QLabel#setupBrand { font-size: 13px; font-weight: 650; }
            QLabel#setupVersion, QLabel#setupHint { color: #9da6b2; font-size: 13px; }
            QLabel#setupHeading { font-size: 26px; font-weight: 650; }
            QLabel#setupStatus { color: #c5cbd3; }
            QProgressBar { border: none; background: #252d37; border-radius: 3px; }
            QProgressBar::chunk { background: #ff6552; border-radius: 3px; }
            QPlainTextEdit { background: #15191f; color: #f2f0ed; border: 1px solid
                #607080; border-radius: 6px; padding: 10px; font: 13px 'Segoe UI'; }
            QPushButton { background: #ff6552; color: #170806; border: 1px solid
                #ff6552; border-radius: 6px; padding: 9px 24px;
                font: 600 14px 'Segoe UI'; }
            QPushButton:hover { background: #ff7867; }
            QPushButton:focus { border: 2px solid #fff8f4; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(18)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        if icon_path:
            icon = QIcon(str(icon_path))
            self.setWindowIcon(icon)
            mark = QLabel()
            mark.setPixmap(icon.pixmap(40, 40))
            brand.addWidget(mark)
        identity = QVBoxLayout()
        identity.setSpacing(3)
        name = QLabel("ASTRA DOWNLOADER")
        name.setObjectName("setupBrand")
        identity.addWidget(name)
        release = QLabel(tr("Version {version}").format(version=version))
        release.setObjectName("setupVersion")
        identity.addWidget(release)
        brand.addLayout(identity, 1)
        layout.addLayout(brand)
        self.heading = QLabel(heading)
        self.heading.setObjectName("setupHeading")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.status = QLabel(tr("Preparing setup…"))
        self.status.setObjectName("setupStatus")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName(tr("Setup progress"))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName(tr("Setup progress"))
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)
        self.hint = QLabel(tr("This window closes when setup finishes."))
        self.hint.setObjectName("setupHint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName(tr("Setup error details"))
        self.details.setMinimumHeight(120)
        self.details.setMaximumHeight(144)
        self.details.hide()
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        actions.addStretch()
        self.close_button = QPushButton(tr("Close"))
        self.close_button.clicked.connect(self.reject)
        self.close_button.hide()
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.worker = _SetupWorker(operation, self)
        self.worker.progress.connect(self._show_progress)
        self.worker.finished.connect(self._finish)
        QTimer.singleShot(0, self.worker.start)

    @Slot(str)
    def _show_progress(self, message):
        messages = {
            "Checking the installed version...": tr("Checking the installed version..."),
            "Verifying the new app...": tr("Verifying the new app..."),
            "Closing the running downloader...": tr("Closing the running downloader..."),
            "Installing the update...": tr("Installing the update..."),
            "Installing Astra Downloader...": tr("Installing Astra Downloader..."),
            "Restoring the previous version...": tr("Restoring the previous version..."),
            "Updating shortcuts and browser connections...": tr("Updating shortcuts and browser connections..."),
            "Closing Astra Downloader...": tr("Closing Astra Downloader..."),
            "Astra Downloader is not responding. Closing it now...": tr(
                "Astra Downloader is not responding. Closing it now..."
            ),
        }
        self.status.setText(messages.get(message, message))

    @Slot()
    def _finish(self):
        self._complete = True
        self.operation_result = self.worker.value
        if self.worker.error is None:
            self.accept()
            return
        self.error_message = str(self.worker.error) or type(self.worker.error).__name__
        self.status.setText(tr("Setup couldn't finish."))
        self.progress.hide()
        self.hint.hide()
        self.details.setPlainText(self.error_message)
        self.details.show()
        self.close_button.show()
        self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self.adjustSize()

    def closeEvent(self, event):
        if not self._complete:
            event.ignore()
        else:
            super().closeEvent(event)

    def done(self, result):
        if self._complete:
            super().done(result)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete and not getattr(self, "_complete", True):
            return True
        return super().event(event)


def run_setup_dialog(operation, *, title, version, icon_path=None):
    """Return the worker result, or raise its failure after the user closes it."""
    if current_thread() is not main_thread():
        raise RuntimeError("The setup dialog must run on the application thread.")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app._setup_translator = install_companion_translator(app, "system")
    if QThread.currentThread() != app.thread():
        raise RuntimeError("The setup dialog must run on the application thread.")
    dialog = SetupDialog(operation, title=title, version=version, icon_path=icon_path)
    dialog.exec()
    if dialog.worker.error is not None:
        raise RuntimeError(dialog.error_message) from dialog.worker.error
    return dialog.operation_result
