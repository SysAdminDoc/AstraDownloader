"""Setup reports actual integration failures without requiring elevation."""

import contextlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import astra_downloader as ad


class RegistryKey(str):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Registry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_WRITE, REG_SZ, REG_DWORD = 2, 1, 4

    def __init__(self):
        self.values = {}
        self.fail_path = ""
        self.closed = []

    def CreateKeyEx(self, _root, path, *_args):
        self.values.setdefault(path, {})
        return RegistryKey(path)

    def OpenKey(self, _root, path, *_args):
        if path not in self.values:
            raise FileNotFoundError(path)
        return RegistryKey(path)

    def SetValueEx(self, key, name, _reserved, kind, value):
        if self.fail_path and self.fail_path in key:
            raise PermissionError("Registry write denied")
        self.values[key][name] = (value, kind)

    def QueryValueEx(self, key, name):
        try:
            return self.values[key][name]
        except KeyError as error:
            raise FileNotFoundError(name) from error

    def DeleteValue(self, key, name):
        if name not in self.values[key]:
            raise FileNotFoundError(name)
        del self.values[key][name]

    def DeleteKey(self, _root, key):
        if self.fail_path and self.fail_path in key:
            raise PermissionError("Registry removal denied")
        del self.values[key]

    def CloseKey(self, key):
        self.closed.append(key)


class InstallIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        self.root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.registry = Registry()
        self.shortcut_code = self.task_code = 0
        self.write_shortcut = True
        self.shell_calls = []
        self.config = {
            "NativeChromeExtensionIds": "a" * 32,
            "NativeFirefoxExtensionIds": ad.DEFAULT_FIREFOX_EXTENSION_IDS[0],
        }
        (self.root / 'config.json').write_text('{}', encoding='utf-8')
        self.context.enter_context(mock.patch.dict(sys.modules, {'winreg': self.registry}))
        for name, value in (
            ('INSTALL_DIR', self.root), ('CONFIG_PATH', self.root / 'config.json'),
            ('NATIVE_HOST_DIR', self.root / 'native-hosts'),
            ('ICON_PATH', self.root / 'missing.ico'),
        ):
            self.context.enter_context(mock.patch.object(ad, name, value))
        self.context.enter_context(mock.patch.object(ad.sys, 'platform', 'win32'))
        self.context.enter_context(mock.patch.object(ad.Path, 'home', return_value=self.root))
        self.context.enter_context(mock.patch.object(ad, 'start_menu_programs_dir', return_value=self.root / 'Programs'))
        self.context.enter_context(mock.patch.object(ad, 'Config', return_value=self.config))
        self.context.enter_context(mock.patch.object(ad, 'stamp_shortcut_app_user_model_id'))
        self.log = self.context.enter_context(mock.patch.object(ad, 'write_persistent_log'))
        self.context.enter_context(mock.patch.object(ad.subprocess, 'run', side_effect=self.shell))

    def shell(self, args, **_kwargs):
        self.shell_calls.append(args)
        task = Path(args[0]).stem.lower() == 'schtasks'
        code = self.task_code if task else self.shortcut_code
        if not task and code == 0 and self.write_shortcut:
            match = re.search(r"CreateShortcut\('((?:[^']|'')*)'\)", args[-1])
            self.assertIsNotNone(match)
            Path(match[1].replace("''", "'")).write_bytes(b'new shortcut')
        return subprocess.CompletedProcess(args, code, b'', b'Access denied' if code else b'')

    def register(self, force=True):
        return ad._register_system_integrations(str(self.root / 'AstraDownloader.exe'), [], force=force)

    def stamp(self):
        return self.registry.values.get(ad.INTEGRATIONS_STAMP_KEY, {}).get(ad.INTEGRATIONS_STAMP_VALUE)

    def test_success_registers_real_boundaries_and_only_then_stamps(self):
        self.register()
        self.assertEqual(self.stamp()[0], ad.APP_VERSION)
        self.assertTrue((self.root / 'Desktop' / ad.SHORTCUT_NAME).exists())
        self.assertTrue((self.root / 'Programs' / ad.SHORTCUT_NAME).exists())
        self.assertEqual(len(list((self.root / 'native-hosts').glob('*.json'))), 2)
        self.assertTrue(any('Uninstall' in path for path in self.registry.values))
        previous_calls = len(self.shell_calls)
        self.register(force=False)
        self.assertEqual(len(self.shell_calls), previous_calls)

    def test_shortcut_nonzero_exit_rejects_an_existing_stale_link(self):
        self.register()
        self.shortcut_code = 1
        with self.assertRaisesRegex(RuntimeError, 'desktop shortcut.*Start Menu shortcut.*run setup again'):
            self.register()
        self.assertIsNone(self.stamp())
        self.assertIn('Access denied', str(self.log.call_args_list))

    def test_missing_shortcut_is_a_required_failure_even_with_zero_exit(self):
        self.write_shortcut = False
        with self.assertRaisesRegex(RuntimeError, 'desktop shortcut'):
            self.register()
        self.assertIsNone(self.stamp())

    def test_registry_exceptions_report_the_failed_integration_and_close_handles(self):
        for path, label in (('Classes\\ytdl', 'video link handlers'),
                            ('Uninstall\\AstraDownloader', 'Apps & Features entry'),
                            ('NativeMessagingHosts', 'browser connections')):
            with self.subTest(path=path):
                self.registry.fail_path = path
                with self.assertRaisesRegex(RuntimeError, label):
                    self.register()
                self.assertIsNone(self.stamp())
                self.assertTrue(any(path in key for key in self.registry.closed))

    def test_schtasks_denial_does_not_fail_standard_user_setup_or_stamp_success(self):
        self.task_code = 1
        self.register()
        self.assertIsNone(self.stamp())
        self.assertIn('Startup task registration failed: Access denied', str(self.log.call_args_list))
        self.task_code = 0
        self.register(force=False)
        self.assertEqual(self.stamp()[0], ad.APP_VERSION)

    def test_normal_startup_logs_failure_and_retries_after_permissions_recover(self):
        self.registry.fail_path = 'NativeMessagingHosts'
        self.register(force=False)
        self.assertIsNone(self.stamp())
        self.registry.fail_path = ''
        self.register(force=False)
        self.assertEqual(self.stamp()[0], ad.APP_VERSION)

    def test_revocation_failure_is_not_reported_as_browser_registration_success(self):
        self.register()
        self.config['NativeChromeExtensionIds'] = ''
        self.config['NativeFirefoxExtensionIds'] = ''
        self.registry.fail_path = 'NativeMessagingHosts'
        with self.assertRaisesRegex(RuntimeError, 'browser connections'):
            self.register()
        self.assertIsNone(self.stamp())


if __name__ == '__main__':
    unittest.main()
