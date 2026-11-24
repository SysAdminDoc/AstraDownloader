"""Knowing the installed version without running it, and updating from GitHub.

On 2026-11-23 a stale v2.16.0 download replaced an installed v2.18.1 because
the only evidence of the installed version was a ``--version`` probe that
timed out. These pin the static evidence that replaced it, the update state
that pairs a digest with its version, and the in-app update flow.
"""

import hashlib
import importlib.util
import json
import platform
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403


MODULE_PATH = Path(__file__).with_name('build.py')
SPEC = importlib.util.spec_from_file_location('astra_downloader_release_build_updates', MODULE_PATH)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class VersionResourceTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows version resources')
    def test_reads_product_version_from_a_real_exe_without_running_it(self):
        # python.exe carries a ProductVersion such as "3.13.15".
        with mock.patch.object(ad.subprocess, 'run') as run:
            self.assertEqual(ad._read_exe_version_resource(sys.executable), platform.python_version())
        run.assert_not_called()

    def test_a_file_without_a_resource_reads_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'AstraDownloader.exe'
            fake.write_bytes(b'MZ' + b'\0' * 64)
            self.assertEqual(ad._read_exe_version_resource(fake), '')
            self.assertEqual(ad._read_exe_version_resource(Path(tmp) / 'missing.exe'), '')

    def test_build_writes_the_app_version_into_the_resource(self):
        text = build.version_resource_text('2.19.0')
        self.assertIn('filevers=(2, 19, 0, 0)', text)
        self.assertIn("StringStruct('ProductVersion', '2.19.0')", text)
        self.assertIn("StringStruct('FileVersion', '2.19.0')", text)
        self.assertIn('filevers=(3, 0, 1, 0)', build.version_resource_text('3.0.1-beta.2'))
        compile(text, 'version_info.txt', 'eval')
        args = build.pyinstaller_args('onefile')
        self.assertEqual(args[args.index('--version-file') + 1], str(build.VERSION_RESOURCE))
        self.assertEqual(build.read_app_version(), ad.APP_VERSION)


class InstalledVersionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exe = self.root / 'AstraDownloader.exe'
        self.exe.write_bytes(b'MZ installed bytes')
        self.digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        patcher = mock.patch.object(ad, 'INSTALL_DIR', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = mock.patch.object(ad, 'write_persistent_log').start()
        self.addCleanup(mock.patch.stopall)

    def write_state(self, **fields):
        (self.root / 'companion-update-state.json').write_text(json.dumps(fields), encoding='utf-8')

    def test_matching_update_state_answers_without_the_probe(self):
        self.write_state(sha256=self.digest, app_version='2.18.1', status='active')
        with mock.patch.object(ad, '_read_exe_version_resource', return_value=''), \
                mock.patch.object(ad, '_probe_companion_version') as probe:
            self.assertEqual(ad._installed_companion_version(self.exe), '2.18.1')
        probe.assert_not_called()

    def test_state_for_other_bytes_is_not_evidence_and_the_probe_gets_a_retry(self):
        self.write_state(sha256='0' * 64, app_version='2.18.1')
        with mock.patch.object(ad, '_read_exe_version_resource', return_value=''), \
                mock.patch.object(ad, '_probe_companion_version', side_effect=['', '2.18.0']) as probe:
            self.assertEqual(ad._installed_companion_version(self.exe), '2.18.0')
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(probe.call_args_list[1].kwargs, {'timeout': 60})

    def test_version_resource_wins_over_everything_else(self):
        self.write_state(sha256=self.digest, app_version='2.18.1')
        with mock.patch.object(ad, '_read_exe_version_resource', return_value='2.19.0'), \
                mock.patch.object(ad, '_probe_companion_version') as probe:
            self.assertEqual(ad._installed_companion_version(self.exe), '2.19.0')
        probe.assert_not_called()

    def test_floor_is_the_newest_recorded_version(self):
        self.assertEqual(ad._installed_version_floor(), '')
        self.write_state(app_version='2.18.1', active_version='2.19.0', sha256='a' * 64)
        self.assertEqual(ad._installed_version_floor(), '2.19.0')
        self.write_state(app_version='2.20.0', active_version='not-a-version')
        self.assertEqual(ad._installed_version_floor(), '2.20.0')

    def test_a_self_update_records_the_release_version_with_its_digest(self):
        ad.record_last_installed_update_sha256('b' * 64, status='activation-pending', app_version='9.9.9')
        state = json.loads((self.root / 'companion-update-state.json').read_text(encoding='utf-8'))
        self.assertEqual((state['sha256'], state['app_version']), ('b' * 64, '9.9.9'))
        ad.record_last_installed_update_sha256('c' * 64)
        state = json.loads((self.root / 'companion-update-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['app_version'], ad.APP_VERSION)

    def test_a_plain_install_reports_its_version_as_the_active_one(self):
        # An install records app_version and never runs the activation helper
        # that writes active_version, so the log and /health read "unknown".
        ad.record_last_installed_update_sha256(self.digest)
        self.assertEqual(ad.read_update_recovery_status()['companion']['activeVersion'], ad.APP_VERSION)
        # A scheduled update is not active yet, so its version is not claimed.
        ad.record_last_installed_update_sha256('b' * 64, status='activation-pending', app_version='9.9.9')
        self.assertNotIn('activeVersion', ad.read_update_recovery_status()['companion'])
        # The activation helper's own field still wins.
        self.write_state(status='active', app_version='9.9.9', active_version='9.9.8')
        self.assertEqual(ad.read_update_recovery_status()['companion']['activeVersion'], '9.9.8')

    def test_a_timed_out_probe_no_longer_lets_an_old_download_replace_the_install(self):
        # The 2026-11-23 sequence: stale v2.16.0 in Downloads, v2.18.1 installed,
        # its --version probe times out under load.
        current = self.root / 'Downloads' / 'AstraDownloader.exe'
        current.parent.mkdir()
        current.write_bytes(b'MZ stale download')
        self.write_state(sha256=self.digest, app_version='2.18.1', status='active')
        with mock.patch.object(ad, 'APP_VERSION', '2.16.0'), \
                mock.patch.object(ad, 'is_frozen_app', return_value=True), \
                mock.patch.object(ad, 'is_portable_mode', return_value=False), \
                mock.patch.object(ad, 'is_onedir_build', return_value=False), \
                mock.patch.object(ad, 'current_executable_path', return_value=current), \
                mock.patch.object(ad, 'install_target_exe', return_value=self.exe), \
                mock.patch.object(ad, '_read_exe_version_resource', return_value=''), \
                mock.patch.object(ad, '_probe_companion_version', return_value=''), \
                mock.patch.object(ad, 'probe_companion_update_binary', return_value=True), \
                mock.patch.object(ad, 'stop_existing_installation') as stop:
            result = ad._install_managed_executable()
        self.assertFalse(result.changed)
        self.assertEqual(result.previous_version, '2.18.1')
        self.assertEqual(self.exe.read_bytes(), b'MZ installed bytes')
        stop.assert_not_called()


class UpdateCheckTests(unittest.TestCase):
    def test_check_reports_a_newer_release(self):
        with mock.patch.object(ad, 'fetch_latest_companion_version', return_value='99.0.0'):
            result = ad.check_companion_update()
        self.assertEqual(result, {
            'ok': True, 'update_available': True,
            'current_version': ad.APP_VERSION, 'latest_version': '99.0.0',
        })
        with mock.patch.object(ad, 'fetch_latest_companion_version', return_value=ad.APP_VERSION):
            self.assertFalse(ad.check_companion_update()['update_available'])

    def test_check_failure_is_quiet_and_not_an_update(self):
        with mock.patch.object(ad, 'fetch_latest_companion_version', side_effect=OSError('offline')), \
                mock.patch.object(ad, 'write_persistent_log') as log:
            result = ad.check_companion_update()
        self.assertFalse(result['ok'])
        self.assertFalse(result['update_available'])
        self.assertIn('offline', str(log.call_args))

    def test_only_copies_that_can_replace_themselves_update(self):
        exe = Path(tempfile.gettempdir()) / 'AstraDownloader.exe'
        cases = (
            # frozen, portable, onedir, running == installed, expected
            (False, False, False, True, False),
            (True, False, True, True, False),
            (True, True, True, False, False),
            (True, True, False, False, True),
            (True, False, False, True, True),
            (True, False, False, False, False),
        )
        for frozen, portable, onedir, managed, expected in cases:
            with self.subTest(frozen=frozen, portable=portable, onedir=onedir, managed=managed), \
                    mock.patch.object(ad, 'is_frozen_app', return_value=frozen), \
                    mock.patch.object(ad, 'is_portable_mode', return_value=portable), \
                    mock.patch.object(ad, 'is_onedir_build', return_value=onedir), \
                    mock.patch.object(ad, 'current_executable_path',
                                      return_value=exe if managed else exe.with_name('other.exe')), \
                    mock.patch.object(ad, 'install_target_exe', return_value=exe):
                self.assertEqual(ad.companion_self_update_supported(), expected)

    def test_an_empty_restart_list_reopens_the_window_instead_of_the_tray(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(ad, 'INSTALL_DIR', Path(tmp.name)), \
                mock.patch.object(ad, 'fetch_latest_companion_version', return_value='99.0.0'), \
                mock.patch.object(ad, 'download_file_atomic',
                                  side_effect=lambda _url, path, **_kw: Path(path).write_bytes(b'MZ')), \
                mock.patch.object(ad, 'validate_companion_update_binary', return_value=True), \
                mock.patch.object(ad, 'fetch_expected_sha256', return_value='d' * 64), \
                mock.patch.object(ad, 'verify_file_sha256'), \
                mock.patch.object(ad, 'probe_companion_update_binary', return_value=True), \
                mock.patch.object(ad, 'is_frozen_app', return_value=False), \
                mock.patch.object(ad, 'is_portable_mode', return_value=False), \
                mock.patch.object(ad, 'read_last_installed_update_sha256', return_value=None), \
                mock.patch.object(ad, 'record_last_installed_update_sha256') as record, \
                mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later, \
                mock.patch.object(ad, 'schedule_companion_update_restart',
                                  return_value={'target': 'x'}) as schedule, \
                mock.patch.object(ad, 'write_persistent_log'):
            result = ad._run_companion_self_update(restart=False, restart_args=[])
            self.assertEqual(result['status'], 'restart_scheduled')
            self.assertEqual(schedule.call_args.args[2], [])
            ad._run_companion_self_update(restart=False)
            self.assertEqual(schedule.call_args.args[2], ['--start-server'])
        exit_later.assert_not_called()
        self.assertEqual(record.call_args.kwargs['app_version'], '99.0.0')


class _ImmediateThread:
    def __init__(self, target=None, **_kwargs):
        self._target = target

    def start(self):
        self._target()


class AppUpdateFlowTests(unittest.TestCase):
    """The window's update decisions, without Qt."""

    def _window(self, *, auto=True, supported=True, active=0, check=None, install=None):
        gui = gui_module_for_tests()
        window = types.SimpleNamespace()
        window.config = FakeConfig({"AutoUpdateApp": auto})
        window.dl_manager = mock.Mock()
        window.dl_manager.active_count.return_value = active
        window.logs = []
        window._append_log = window.logs.append
        window.statuses = []
        window._set_app_update_status = lambda message, tone='neutral': window.statuses.append((message, tone))
        window.scheduled = []
        window._schedule_app_update_check = window.scheduled.append
        window._app_update_busy = False
        window._app_update_offered = ''
        window.isVisible = lambda: True
        window._force_close = mock.Mock()
        window.app_update_checked = mock.Mock()
        window.app_update_finished = mock.Mock()
        window._set_control_label = mock.Mock()
        window._dependencies = {
            'APP_VERSION': lambda: '2.18.1',
            'companion_self_update_supported': lambda: supported,
            'APP_UPDATE_CHECK_INTERVAL_SECONDS': lambda: 21600,
            'APP_UPDATE_RETRY_SECONDS': lambda: 300,
            'check_companion_update': check or (lambda: {}),
            '_run_companion_self_update': install or mock.Mock(return_value={'ok': True}),
        }
        window._value = lambda name: window._dependencies[name]()
        for name in ('_check_app_update_in_background', '_on_app_update_checked',
                     '_install_app_update', '_finish_app_update'):
            setattr(window, name, types.MethodType(getattr(gui.MainWindowCore, name), window))
        return window

    def available(self, **extra):
        return {'ok': True, 'update_available': True, 'latest_version': '2.19.0',
                'current_version': '2.18.1', **extra}

    def test_an_idle_queue_installs_automatically_and_comes_back_in_the_tray(self):
        install = mock.Mock(return_value={'ok': True, 'status': 'restart_scheduled', 'latest_version': '2.19.0'})
        window = self._window(install=install)
        with mock.patch.object(gui_module_for_tests().threading, 'Thread', _ImmediateThread):
            window._on_app_update_checked(self.available())
        install.assert_called_once_with(restart=False, dl_manager=window.dl_manager, restart_args=None)
        finished = window.app_update_finished.emit.call_args.args[0]
        window._finish_app_update(finished)
        window._force_close.assert_called_once_with()

    def test_a_manual_check_reopens_the_window_after_the_update(self):
        install = mock.Mock(return_value={'ok': True, 'status': 'restart_scheduled'})
        window = self._window(install=install, auto=False)
        with mock.patch.object(gui_module_for_tests().threading, 'Thread', _ImmediateThread):
            window._on_app_update_checked(self.available(manual=True))
        self.assertEqual(install.call_args.kwargs['restart_args'], [])

    def test_running_downloads_postpone_the_install(self):
        install = mock.Mock()
        window = self._window(active=2, install=install)
        window._on_app_update_checked(self.available())
        install.assert_not_called()
        self.assertEqual(window.scheduled, [300])
        self.assertIn('2.19.0', window.statuses[-1][0])

    def test_automatic_updates_off_only_offers_it_once_per_version(self):
        install = mock.Mock()
        window = self._window(auto=False, install=install)
        with mock.patch.object(gui_module_for_tests(), 'show_tray_message') as tray:
            window._on_app_update_checked(self.available())
            window._on_app_update_checked(self.available())
        install.assert_not_called()
        self.assertEqual(tray.call_count, 1)
        self.assertEqual(window.scheduled, [21600, 21600])

    def test_a_failed_install_keeps_the_current_version_and_retries_later(self):
        window = self._window()
        window._finish_app_update({'ok': False, 'error': 'SHA-256 verification failed.'})
        window._force_close.assert_not_called()
        self.assertEqual(window.statuses[-1][1], 'danger')
        self.assertEqual(window.scheduled, [1800])
        self.assertIn('SHA-256 verification failed', window.logs[-1])

    def test_up_to_date_and_offline_checks_reschedule(self):
        window = self._window()
        window._on_app_update_checked({'ok': True, 'update_available': False, 'latest_version': '2.18.1'})
        window._on_app_update_checked({'ok': False})
        self.assertEqual(window.scheduled, [21600, 1800])
        self.assertEqual(window.statuses, [])

    def test_the_background_check_reports_through_the_signal(self):
        window = self._window(check=lambda: self.available())
        with mock.patch.object(gui_module_for_tests().threading, 'Thread', _ImmediateThread):
            window._check_app_update_in_background()
        emitted = window.app_update_checked.emit.call_args.args[0]
        self.assertTrue(emitted['update_available'])
        self.assertFalse(emitted['manual'])


if __name__ == '__main__':
    unittest.main()
