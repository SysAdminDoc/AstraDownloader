#!/usr/bin/env python3
"""Bounded, offline captures of actual packaged widgets in an owned profile."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback


def prepare_review(argv):
    """Select review mode before importing Qt or computing application paths."""
    if '--review-dir' not in argv:
        return None
    if len(argv) != 2 or argv[0] != '--review-dir' or not argv[1].strip():
        raise SystemExit('--review-dir requires one new absolute directory and no other arguments')
    requested = Path(argv[1])
    if not requested.is_absolute():
        raise SystemExit('The review directory must be absolute')
    root = requested.resolve()
    root.mkdir(parents=True, exist_ok=False)
    profile = root / 'profile'
    for name, relative in (
        ('USERPROFILE', ''), ('HOME', ''), ('LOCALAPPDATA', 'LocalAppData'),
        ('APPDATA', 'AppData'), ('TEMP', 'Temp'), ('TMP', 'Temp'),
    ):
        target = profile / relative
        target.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(target)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['QT_SCALE_FACTOR'] = '1'
    os.environ['ASTRA_DOWNLOADER_NO_BOOTSTRAP'] = '1'
    os.environ.pop('ASTRA_PORTABLE', None)
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    return root


def run_review(ad, root):
    """Render first-run and example states, exercise controls, then exit."""
    if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
        raise RuntimeError('Review requires the offscreen backend')
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont, QFontDatabase, QIcon, QRawFont
    from PySide6.QtWidgets import QApplication

    report = {
        'version': ad.APP_VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
        'backend': 'offscreen', 'dataset': 'Seeded examples, not completed downloads',
        'network': 'Disabled. No server, browser pairing, helper setup or media transfers.',
        'checks': [], 'captures': [], 'passed': False,
    }
    app = QApplication(['astra-review'])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(ad.APP_NAME)
    # Windows' offscreen backend doesn't enumerate system fonts itself.
    # Load the installed family explicitly; never publish missing-glyph boxes.
    for filename in ('segoeui.ttf', 'seguisb.ttf', 'segoeuib.ttf'):
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / filename
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI', 9))
    window = None

    def check(condition, name):
        if not condition:
            raise AssertionError(name)
        report['checks'].append(name)

    try:
        check(QRawFont.fromFont(app.font()).supportsCharacter('A'), 'text font has Latin glyphs')
        check(Path(ad.INSTALL_DIR).resolve().is_relative_to(root), 'isolated state root')
        ad.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        icon = Path(ad.__file__).resolve().parent / 'AstraDownloader.ico'
        if not icon.exists():
            icon = Path(ad.__file__).resolve().parent.parent / 'AstraDownloader.ico'
        if icon.exists():
            shutil.copy2(icon, ad.ICON_PATH)
            app.setWindowIcon(QIcon(str(ad.ICON_PATH)))
        config = ad.Config()
        videos = root / 'profile' / 'Videos'
        videos.mkdir()
        check(config.update({
            'DownloadPath': str(videos), 'AudioDownloadPath': str(videos),
            'Theme': 'dark', 'Language': 'en', 'FirstRunComplete': False,
            'CloseToTray': False, 'StartMinimized': False,
            'ClipboardLinkGrabber': False, 'NotifyOnComplete': False,
            'NotifyOnFailure': False,
        }), 'review configuration saved')
        ad.apply_application_theme('dark')
        history = ad.History(config)
        manager = ad.DownloadManager(config, history, queue_path=ad.DOWNLOAD_QUEUE_PATH)

        class ReviewWindow(ad.MainWindow):
            # These background boundaries are intentionally disabled only in
            # this disposable review process. All widgets/renderers are real.
            def _start_instance_command_listener(self):
                pass

            def _stop_instance_command_listener(self):
                pass

            def _start_readiness_probe(self):
                pass

            def _load_site_catalog_extractors(self):
                pass

            def _refresh_tools_status(self):
                self._set_tools_status_text('Review mode. Tools not started.')

            def _animate_page(self):
                pass

        window = ReviewWindow(config, manager, history, first_run=True)
        for timer in (window.update_timer, window.cleanup_timer, window.tools_status_timer):
            timer.stop()
        window.tray.hide()
        window._refresh_tools_status()
        window.resize(1440, 1040)
        window.show()

        def capture(name):
            app.processEvents()
            window.repaint()
            window.sidebar.repaint()
            window.sidebar.grab()
            app.processEvents()
            frame = window.grab().toImage()
            check(not frame.isNull() and frame.size() == window.size(), name + ' frame geometry')
            for button in window.nav_buttons:
                check(button.isVisible() and window.sidebar.rect().contains(button.geometry()),
                      name + ' navigation ' + button.text())
                top = button.mapTo(window, QPoint(0, 0))
                colors = {frame.pixelColor(x, y).rgba()
                          for y in range(top.y(), top.y() + button.height(), 4)
                          for x in range(top.x(), top.x() + button.width(), 4)}
                check(len(colors) >= 3, name + ' painted navigation ' + button.text())
            output = root / (name + '.png')
            check(frame.save(str(output), 'PNG'), name + ' PNG saved')
            report['captures'].append({'file': output.name, 'width': frame.width(),
                                       'height': frame.height(),
                                       'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})

        check(window.first_run_panel.isVisible(), 'first-run panel visible')
        capture('first-run')
        window.first_run_confirm.click()
        check(config.get('FirstRunComplete') is True, 'destination confirmation persisted')
        window._first_run = False
        window._apply_first_run_panel_state()
        for order, (key, title, status) in enumerate((
            ('example-queue', 'City soundscape (example)', 'pending'),
            ('example-video', 'Open film project (example)', 'downloading'),
        )):
            item = ad.Download(key, 'https://example.com/' + key,
                               fmt='mp4', quality='1080', output_dir=str(videos),
                               title=title, queue_order=order)
            item.status = status
            if status == 'downloading':
                item.progress = 62
                manager._running_ids.add(key)
            manager.downloads[key] = item
        window._downloads_signature = None
        window._update_ui()
        check(sum(key[0] == 'download' for key in window._download_widgets) == 2,
              'example queue rendered')
        capture('downloads')
        for page, name in (('Sites', 'sites'), ('History', 'history'),
                           ('Sign-ins', 'sign-ins'), ('Settings', 'settings')):
            window._nav_click(page)
            check(window.tabs.currentIndex() == window._page_names.index(page), page + ' navigation')
            capture(name)
        window._nav_click('Download')
        ad.apply_application_theme('light', windows=(window,))
        capture('downloads-light')
        check(config.get('ClipboardLinkGrabber') is False, 'clipboard monitoring remains off')
        check(not window.server_running and window._instance_command_thread is None,
              'no server or instance listener started')
        check(not ad.YTDLP_PATH.exists() and not ad.FFMPEG_PATH.exists(), 'no helpers downloaded')
        report['passed'] = True
    except Exception:
        # reason: a failed review must leave diagnostics and return a nonzero exit code
        report['error'] = traceback.format_exc()
    finally:
        if window is not None:
            window.tray.hide()
            window.hide()
        ad.flush_all_persistence()
        (root / 'review.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1
