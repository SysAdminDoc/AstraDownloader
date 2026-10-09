"""Setup must leave either the verified replacement or a usable old app."""

import hashlib
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import installer
except ImportError:
    import installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'Downloads' / 'AstraDownloader.exe'
        self.target = self.root / 'installed' / 'AstraDownloader.exe'
        self.source.parent.mkdir()
        self.target.parent.mkdir()
        self.source.write_bytes(b'new executable')
        self.target.write_bytes(b'old executable')
        self.events = []
        self.stop = mock.Mock(side_effect=lambda: self.events.append('stop') or True)
        self.health = mock.Mock(side_effect=lambda path, version: self.events.append(('health', path, version)) or True)
        self.copy = mock.Mock(side_effect=shutil.copyfile)
        self.options = {
            'probe_version': lambda _path: '1.0.0',
            'compare_versions': lambda a, b: (a > b) - (a < b),
            'health_check': self.health, 'copy_verified': self.copy,
            'digest': lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
            'stop_running': self.stop,
        }

    def install(self, **overrides):
        return installer.install_verified_copy(
            self.source, self.target, '2.0.0', **(self.options | overrides),
        )

    def test_upgrade_checks_stage_before_stopping_and_keeps_backup(self):
        result = self.install()
        self.assertTrue(result.changed)
        self.assertTrue(result.stopped)
        self.assertEqual(result.previous_version, '1.0.0')
        self.assertEqual(self.events[0][0], 'health')
        self.assertNotEqual(self.events[0][1], self.target)
        self.assertEqual(self.events[1], 'stop')
        self.assertEqual(self.events[2], ('health', self.target, '2.0.0'))
        self.assertEqual(self.target.read_bytes(), b'new executable')
        self.assertEqual(self.target.with_name('.AstraDownloader.last-known-good.exe').read_bytes(), b'old executable')
        self.assertEqual(list(self.target.parent.glob('.AstraDownloader.install.*.exe')), [])

    def test_failed_stage_health_does_not_stop_or_change_old_app(self):
        self.health.return_value = False
        self.health.side_effect = None
        with self.assertRaisesRegex(installer.InstallationError, 'previous app was kept') as caught:
            self.install()
        self.assertFalse(caught.exception.restart_previous)
        self.stop.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b'old executable')

    def test_failed_stage_copy_does_not_stop_the_running_app(self):
        self.copy.side_effect = OSError('Disk full')
        with self.assertRaisesRegex(installer.InstallationError, 'Disk full'):
            self.install()
        self.stop.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b'old executable')

    def test_failed_shutdown_leaves_executable_intact(self):
        self.stop.side_effect = RuntimeError('Process still running')
        with self.assertRaisesRegex(installer.InstallationError, 'Process still running'):
            self.install()
        self.assertEqual(self.target.read_bytes(), b'old executable')

    def test_failed_activation_requests_restart_of_preserved_old_copy(self):
        def copy(source, target):
            if target == self.target:
                raise OSError('Read-only destination')
            shutil.copyfile(source, target)
        with self.assertRaises(installer.InstallationError) as caught:
            self.install(copy_verified=copy)
        self.assertTrue(caught.exception.restart_previous)
        self.assertEqual(self.target.read_bytes(), b'old executable')

    def test_failed_installed_health_restores_and_checks_previous_version(self):
        self.health.side_effect = [True, False, True]
        with self.assertRaises(installer.InstallationError) as caught:
            self.install()
        self.assertTrue(caught.exception.restart_previous)
        self.assertEqual(self.target.read_bytes(), b'old executable')
        self.assertEqual(self.health.call_args, mock.call(self.target, '1.0.0'))

    def test_failed_rollback_never_claims_or_relaunches_a_working_install(self):
        self.health.side_effect = [True, False]
        def copy(source, target):
            if source.name == '.AstraDownloader.last-known-good.exe':
                raise OSError('Rollback write failed')
            shutil.copyfile(source, target)
        with self.assertRaisesRegex(installer.InstallationError, 'could not be restored') as caught:
            self.install(copy_verified=copy)
        self.assertFalse(caught.exception.restart_previous)

    def test_fresh_install_failure_removes_unhealthy_executable(self):
        self.target.unlink()
        self.health.side_effect = [True, False]
        with self.assertRaises(installer.InstallationError) as caught:
            self.install()
        self.assertFalse(caught.exception.restart_previous)
        self.assertFalse(self.target.exists())

    def test_fresh_install_succeeds_without_a_previous_version(self):
        self.target.unlink()
        self.stop.side_effect = None
        self.stop.return_value = False
        result = self.install()
        self.assertEqual(result, installer.InstallResult(self.target, True, False, ''))

    def test_same_executable_is_a_noop(self):
        result = installer.install_verified_copy(self.target, self.target, '2.0.0', **self.options)
        self.assertFalse(result.changed)
        self.copy.assert_not_called()
        self.stop.assert_not_called()

    def test_identical_download_does_not_interrupt_running_app(self):
        self.source.write_bytes(self.target.read_bytes())
        self.assertFalse(self.install().changed)
        self.stop.assert_not_called()
        self.copy.assert_not_called()

    def test_newer_installation_is_preserved_unless_downgrade_is_explicit(self):
        self.assertFalse(self.install(probe_version=lambda _path: '3.0.0').changed)
        self.stop.assert_not_called()
        self.assertTrue(self.install(probe_version=lambda _path: '3.0.0', allow_downgrade=True).changed)

    def test_user_data_is_untouched(self):
        names = ['config.json', 'queue.json', 'history.json', 'site_logins.json', 'downloads/video.mp4']
        for name in names:
            path = self.target.parent / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        self.install()
        for name in names:
            with self.subTest(name=name):
                self.assertEqual((self.target.parent / name).read_bytes(), name.encode())

    def test_existing_checksum_is_refreshed_on_activation_and_rollback(self):
        sidecar = self.target.with_suffix('.exe.sha256')
        for fail_health in (False, True):
            with self.subTest(fail_health=fail_health):
                self.target.write_bytes(b'old executable')
                sidecar.write_text('previous checksum')
                self.health.side_effect = [True, False, True] if fail_health else [True, True]
                if fail_health:
                    with self.assertRaises(installer.InstallationError):
                        self.install()
                else:
                    self.install()
                expected = self.options['digest'](self.target)
                self.assertEqual(sidecar.read_text(), f'{expected}  {self.target.name}\n')

    def test_install_does_not_add_optional_checksum_sidecar(self):
        self.install()
        self.assertFalse(self.target.with_suffix('.exe.sha256').exists())

    def test_locked_unchanged_sidecar_does_not_prevent_rollback(self):
        sidecar = self.target.with_suffix('.exe.sha256')
        sidecar.write_text(f"{self.options['digest'](self.target)}  {self.target.name}\n")
        with mock.patch.object(installer.os, 'replace', side_effect=PermissionError('Checksum is locked')), \
                self.assertRaises(installer.InstallationError) as caught:
            self.install()
        self.assertTrue(caught.exception.restart_previous)
        self.assertEqual(self.target.read_bytes(), b'old executable')
        self.assertEqual(sidecar.read_text().split()[0], self.options['digest'](self.target))

    def test_serializes_competing_installers_and_releases_after_failure(self):
        outcomes = []
        def competing():
            try:
                with installer.installation_lock(self.target.parent, timeout=0.1):
                    outcomes.append('entered')
            except installer.InstallationError:
                outcomes.append('locked')
        with installer.installation_lock(self.target.parent):
            worker = threading.Thread(target=competing)
            worker.start()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes, ['locked'])
        competing()
        self.assertEqual(outcomes, ['locked', 'entered'])
