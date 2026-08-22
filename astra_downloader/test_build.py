import importlib.util
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
import io
import json
import re
import shutil
import subprocess
import sys
import time
import types
import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403



MODULE_PATH = Path(__file__).with_name('build.py')
SPEC = importlib.util.spec_from_file_location('astra_downloader_release_build', MODULE_PATH)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class FakeDistribution:
    def __init__(self, name, version, requires=()):
        self.metadata = {'Name': name, 'License': 'MIT'}
        self.version = version
        self.requires = list(requires)
        self.files = []


class ReleaseConstraintsTests(unittest.TestCase):
    def test_frozen_build_keeps_lazy_boundary_modules_in_the_graph(self):
        source = MODULE_PATH.read_text(encoding='utf-8')
        for module_name in ('_compat', 'config', 'download', 'health', 'routes', 'gui'):
            self.assertIn(f'"--hidden-import", "{module_name}"', source)
        self.assertIn('--onefile', build.pyinstaller_args('onefile'))
        self.assertIn('--onedir', build.pyinstaller_args('onedir'))

    def test_reviewed_constraints_are_exact_and_cover_release_roots(self):
        constraints = build.parse_release_constraints()
        for required in ('pyinstaller', 'pyside6-essentials', 'flask', 'requests', 'waitress', 'yt-dlp'):
            self.assertIn(required, constraints)
            self.assertTrue(constraints[required]['version'])

        # A count floor goes stale the moment the graph legitimately shrinks —
        # dropping PyQt6's three distributions for PySide6's two did exactly
        # that. What has to hold is that every direct requirement is pinned and
        # that transitives were captured alongside them.
        direct = set()
        for raw in build.REQUIREMENTS.read_text(encoding='utf-8').splitlines():
            line = raw.split('#', 1)[0].strip()
            if line:
                direct.add(build.canonicalize_name(build.Requirement(line).name))
        self.assertTrue(direct, 'requirements.txt declared no direct dependency')
        self.assertLessEqual(direct, set(constraints))
        self.assertGreater(len(constraints), len(direct),
                           'the reviewed graph must pin transitives, not only the direct set')

    def test_constraint_parser_rejects_ranges_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'constraints.txt'
            for invalid in ('demo>=1\n', 'demo==1\ndemo==1\n'):
                path.write_text(invalid, encoding='utf-8')
                with self.assertRaises(SystemExit):
                    build.parse_release_constraints(path)

    def test_sha256_sidecar_is_derived_from_the_exact_exe_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'AstraDownloader.exe'
            sidecar = Path(tmp) / 'AstraDownloader.exe.sha256'
            exe.write_bytes(b'MZ' + b'companion-build')

            digest = build.write_sha256_sidecar(exe, sidecar)

            self.assertEqual(digest, build.sha256_file(exe))
            self.assertEqual(
                sidecar.read_text(encoding='ascii'),
                f'{digest}  AstraDownloader.exe\n',
            )

    def test_onedir_archive_has_a_stable_root_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'AstraDownloader'
            (source / 'translations').mkdir(parents=True)
            (source / 'AstraDownloader.exe').write_bytes(b'MZ' + b'app')
            (source / 'translations' / 'astra_downloader_en.qm').write_bytes(b'qm')
            archive = root / 'AstraDownloader-onedir.zip'

            self.assertEqual(build.write_onedir_archive(source, archive), archive)
            with zipfile.ZipFile(archive) as handle:
                self.assertEqual(
                    handle.namelist(),
                    [
                        'AstraDownloader/.astradownloader-portable',
                        'AstraDownloader/AstraDownloader.exe',
                        'AstraDownloader/translations/astra_downloader_en.qm',
                    ],
                )
                self.assertEqual(handle.read('AstraDownloader/AstraDownloader.exe'), b'MZ' + b'app')
            digest = build.write_sha256_sidecar(archive)
            self.assertEqual(digest, build.sha256_file(archive))
            self.assertEqual(
                archive.with_name(archive.name + '.sha256').read_text(encoding='ascii'),
                f'{digest}  {archive.name}\n',
            )

    def test_onedir_archive_can_carry_shared_build_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'AstraDownloader'
            source.mkdir()
            (source / 'AstraDownloader.exe').write_bytes(b'MZ' + b'app')
            metadata = root / 'companion-build-metadata.json'
            metadata.write_text(
                '{"version":"2.6.0","buildId":"a"}',
                encoding='utf-8',
            )
            archive = root / 'AstraDownloader-onedir.zip'

            build.write_onedir_archive(source, archive, metadata_path=metadata)

            with zipfile.ZipFile(archive) as handle:
                self.assertEqual(
                    handle.read('AstraDownloader/companion-build-metadata.json'),
                    metadata.read_bytes(),
                )

    def test_clean_removes_stale_release_outputs_before_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            astra_root = root / 'astra_downloader'
            build_dir = astra_root / 'build'
            dist_dir = astra_root / 'dist'
            build_dir.mkdir(parents=True)
            dist_dir.mkdir(parents=True)
            artifacts = (
                root / 'AstraDownloader.exe',
                root / 'AstraDownloader.exe.sha256',
                root / 'AstraDownloader-onedir.zip',
                root / 'AstraDownloader-onedir.zip.sha256',
            )
            for artifact in artifacts:
                artifact.write_bytes(b'stale')

            with mock.patch.object(build, 'ROOT', root), \
                    mock.patch.object(build, 'HERE', astra_root), \
                    mock.patch.object(build, 'BUILD_DIR', build_dir), \
                    mock.patch.object(build, 'DIST_DIR', dist_dir), \
                    mock.patch.object(build, 'OUT_EXE', artifacts[0]), \
                    mock.patch.object(build, 'OUT_SHA256', artifacts[1]), \
                    mock.patch.object(build, 'OUT_ONEDIR_ZIP', artifacts[2]), \
                    mock.patch.object(build, 'OUT_ONEDIR_SHA256', artifacts[3]):
                build.clean()

            self.assertFalse(build_dir.exists())
            self.assertFalse(dist_dir.exists())
            self.assertTrue(all(not artifact.exists() for artifact in artifacts))

    def test_build_keeps_the_onefile_analysis_for_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            astra_root = root / 'astra_downloader'
            build_dir = astra_root / 'build'
            dist_dir = astra_root / 'dist'
            spec_dir = build_dir / 'spec'
            outputs = {
                'exe': root / 'AstraDownloader.exe',
                'exe_sha': root / 'AstraDownloader.exe.sha256',
                'zip': root / 'AstraDownloader-onedir.zip',
                'zip_sha': root / 'AstraDownloader-onedir.zip.sha256',
            }
            metadata_calls = []

            def fake_pyinstaller(mode):
                analysis = build_dir / 'AstraDownloader' / 'Analysis-00.toc'
                analysis.parent.mkdir(parents=True, exist_ok=True)
                analysis.write_text(mode, encoding='utf-8')
                if mode == 'onefile':
                    dist_dir.mkdir(parents=True, exist_ok=True)
                    (dist_dir / 'AstraDownloader.exe').write_bytes(b'MZ' + b'app')
                else:
                    folder = dist_dir / 'AstraDownloader'
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / 'AstraDownloader.exe').write_bytes(b'MZ' + b'app')

            def fake_metadata(exe_path, analysis_toc=None):
                metadata_calls.append((Path(exe_path), Path(analysis_toc)))

            def fake_archive(_source, archive_path, metadata_path=None):
                Path(archive_path).write_bytes(b'zip')
                self.assertIsNotNone(metadata_path)

            with mock.patch.object(build, 'preflight'), \
                    mock.patch.object(build, 'prepare_translations'), \
                    mock.patch.object(build, 'clean'), \
                    mock.patch.object(build, 'BUILD_DIR', build_dir), \
                    mock.patch.object(build, 'DIST_DIR', dist_dir), \
                    mock.patch.object(build, 'SPEC_DIR', spec_dir), \
                    mock.patch.object(build, 'OUT_EXE', outputs['exe']), \
                    mock.patch.object(build, 'OUT_SHA256', outputs['exe_sha']), \
                    mock.patch.object(build, 'OUT_ONEDIR_ZIP', outputs['zip']), \
                    mock.patch.object(build, 'OUT_ONEDIR_SHA256', outputs['zip_sha']), \
                    mock.patch.object(build, 'run_pyinstaller', side_effect=fake_pyinstaller), \
                    mock.patch.object(build, 'write_build_metadata', side_effect=fake_metadata), \
                    mock.patch.object(build, 'write_onedir_archive', side_effect=fake_archive):
                build.build()

            self.assertEqual(len(metadata_calls), 1)
            self.assertEqual(metadata_calls[0][1].read_text(encoding='utf-8'), 'onefile')

    def test_build_metadata_records_the_onefile_analysis_identity(self):
        class Metadata:
            def __init__(self, name):
                self._values = {'Name': name, 'License': 'MIT'}

            def get(self, key, default=None):
                return self._values.get(key, default)

            def get_all(self, _key):
                return []

        class Distribution:
            def __init__(self, name, files=()):
                self.metadata = Metadata(name)
                self.version = '6.21.0'
                self.files = list(files)

            def locate_file(self, item):
                return Path(item)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'AstraDownloader.exe'
            exe.write_bytes(b'MZ' + b'app')
            analysis = root / 'onefile-analysis.toc'
            packaged_pyqt = root / 'site-packages' / 'PySide6' / '__init__.py'
            packaged_pyqt.parent.mkdir(parents=True)
            packaged_pyqt.write_text('fixture', encoding='utf-8')
            analysis.write_text(repr([str(packaged_pyqt)]), encoding='utf-8')
            constraints = root / 'constraints-release.txt'
            constraints.write_text('pyside6-essentials==6.11.2\n', encoding='utf-8')
            script = root / 'astra_downloader.py'
            script.write_text('APP_VERSION = "2.6.0"\n', encoding='utf-8')
            metadata_path = root / 'companion-build-metadata.json'
            pyqt = Distribution('PySide6-Essentials', [packaged_pyqt])
            pyqt.version = '6.11.0'
            pyinstaller = Distribution('PyInstaller')

            environment = {
                'distributions': {'pyinstaller': pyinstaller, 'pyside6-essentials': pyqt},
                'buildNames': {'pyinstaller'},
                'graph': {'pyinstaller': [], 'pyside6-essentials': []},
                'directNames': ['pyinstaller', 'pyside6-essentials'],
            }
            with mock.patch.object(build, 'BUILD_METADATA', metadata_path), \
                    mock.patch.object(build, 'OUT_ONEDIR_ZIP', root / 'AstraDownloader-onedir.zip'), \
                    mock.patch.object(build, 'RELEASE_CONSTRAINTS', constraints), \
                    mock.patch.object(build, 'SCRIPT', script), \
                    mock.patch.object(build, 'verify_release_environment', return_value=environment):
                build.write_build_metadata(exe, analysis_toc=analysis)

            payload = build.json.loads(metadata_path.read_text(encoding='utf-8'))
            self.assertEqual(payload['version'], '2.6.0')
            self.assertEqual(payload['buildId'], build.sha256_file(analysis))
            self.assertEqual(payload['artifacts']['onefile'], payload['artifact'])
            self.assertEqual(
                payload['artifacts']['onedir']['buildId'], payload['buildId']
            )

    def _verify_fixture(self, app_requires=('dep>=2',), app_version='1.0'):
        distributions = {
            'app': FakeDistribution('app', app_version, app_requires),
            'dep': FakeDistribution('dep', '2.0'),
            'pyinstaller': FakeDistribution('pyinstaller', '3.0'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = root / 'requirements.txt'
            constraints = root / 'constraints.txt'
            requirements.write_text('app>=1,<2\n', encoding='utf-8')
            constraints.write_text('app==1.0\ndep==2.0\npyinstaller==3.0\n', encoding='utf-8')

            def distribution(name):
                key = build.canonicalize_name(name)
                if key not in distributions:
                    raise build.importlib.metadata.PackageNotFoundError(name)
                return distributions[key]

            with mock.patch.object(build, 'REQUIREMENTS', requirements), \
                 mock.patch.object(build, 'RELEASE_CONSTRAINTS', constraints), \
                 mock.patch.object(build.sys, 'platform', 'win32'), \
                 mock.patch.object(build.importlib.metadata, 'distribution', side_effect=distribution):
                return build.verify_release_environment()

    def test_environment_verifier_returns_exact_dependency_edges(self):
        result = self._verify_fixture()
        self.assertEqual(result['graph']['app'], ['dep'])
        self.assertEqual(result['constraints']['dep']['version'], '2.0')

    def test_environment_verifier_rejects_unreviewed_active_dependency(self):
        with self.assertRaisesRegex(SystemExit, 'Unreviewed active dependency'):
            self._verify_fixture(app_requires=('rogue>=1',))

    def test_environment_verifier_rejects_installed_version_drift(self):
        with self.assertRaisesRegex(SystemExit, 'Release environment drift'):
            self._verify_fixture(app_version='1.1')

    def test_prepare_translations_fails_on_stale_qm_without_compiler(self):
        expected = (
            'ar', 'de', 'en', 'es', 'fr', 'it', 'ja', 'ko', 'pt_BR', 'ru',
            'zh_CN',
        )
        with tempfile.TemporaryDirectory() as tmp:
            translations = Path(tmp)
            for locale in expected:
                ts = translations / f'astra_downloader_{locale}.ts'
                qm = translations / f'astra_downloader_{locale}.qm'
                ts.write_text('<TS/>', encoding='utf-8')
                qm.write_bytes(b'compiled')

            stale_ts = translations / 'astra_downloader_en.ts'
            stale_qm = translations / 'astra_downloader_en.qm'
            os.utime(stale_qm, ns=(1_000_000_000, 1_000_000_000))
            os.utime(stale_ts, ns=(2_000_000_000, 2_000_000_000))

            with mock.patch.object(build, 'TRANSLATIONS_DIR', translations), \
                 mock.patch.object(build.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(SystemExit, r'stale \.qm catalogues.*en'):
                    build.prepare_translations()


if __name__ == '__main__':
    unittest.main()


class UninstallCleanupTests(unittest.TestCase):
    def test_uninstall_removes_app_owned_artifacts_but_keeps_downloads(self):
        deleted = []

        def delete_key(_root, path):
            deleted.append(path)

        fake_winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            DeleteKey=delete_key,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "AstraDownloader"
            native = root / "native-host"
            desktop = root / "Desktop"
            start_menu = root / "Start Menu"
            downloads = root / "Videos"
            install.mkdir()
            native.mkdir()
            desktop.mkdir()
            start_menu.mkdir()
            downloads.mkdir()
            (install / "config.json").write_text("state", encoding="utf-8")
            (native / "host.json").write_text("manifest", encoding="utf-8")
            (desktop / ad.SHORTCUT_NAME).write_text("shortcut", encoding="utf-8")
            (start_menu / ad.SHORTCUT_NAME).write_text("shortcut", encoding="utf-8")
            downloaded = downloads / "keep-me.mp4"
            downloaded.write_bytes(b"downloaded")

            with mock.patch.dict(sys.modules, {"winreg": fake_winreg}), \
                 mock.patch.object(ad, "write_persistent_log"), \
                 mock.patch.object(ad, "stop_running_companion_for_uninstall"), \
                 mock.patch.object(ad.subprocess, "run"), \
                 mock.patch.object(ad, "NATIVE_HOST_DIR", native), \
                 mock.patch.object(ad, "INSTALL_DIR", install), \
                 mock.patch.object(ad, "start_menu_programs_dir", return_value=start_menu), \
                 mock.patch.object(ad.Path, "home", return_value=root):
                with self.assertRaises(SystemExit) as ctx:
                    ad.run_uninstall()

            self.assertEqual(ctx.exception.code, 0)
            self.assertFalse(install.exists())
            self.assertFalse(native.exists())
            self.assertFalse((desktop / ad.SHORTCUT_NAME).exists())
            self.assertFalse((start_menu / ad.SHORTCUT_NAME).exists())
            self.assertTrue(downloaded.exists(), "uninstall must not remove downloads")
            self.assertIn(ad.INTEGRATIONS_STAMP_KEY, deleted)

    def test_portable_state_sweep_covers_rotations_quarantine_and_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "AstraDownloader"
            install.mkdir()
            executable = install / "AstraDownloader.exe"
            executable.write_bytes(b"portable")
            media = install / "keep-me.mp4"
            media.write_bytes(b"media")
            (install / ad.PORTABLE_MARKER_NAME).write_text("portable\n", encoding="utf-8")

            (install / "config.json").write_text("state", encoding="utf-8")
            (install / "site-logins").mkdir()
            (install / "site-logins" / "index.json").write_text("{}", encoding="utf-8")
            (install / "download-temp" / "dl_1").mkdir(parents=True)
            (install / "download-temp" / "dl_1" / "audio.wav").write_bytes(b"scratch")
            for name in (
                ".cookies.probe.deadbeef.txt",
                ".cookies.dl_1.txt",
                "server.log.1",
                "crash.log.1",
                "config.json.corrupt-20260811120000",
                ".history.json.deadbeef.tmp",
                ".AstraDownloader.update.deadbeef.exe",
                ".yt-dlp.update.deadbeef.exe",
                ".whisper.deadbeef.zip",
                "archive.txt",
            ):
                (install / name).write_text("orphan", encoding="utf-8")
            bystander = install / "notes.txt"
            bystander.write_text("keep", encoding="utf-8")

            with mock.patch.object(ad, "INSTALL_DIR", install), \
                 mock.patch.object(ad, "current_executable_path", return_value=executable), \
                 mock.patch.object(ad, "write_persistent_log"):
                ad.remove_portable_state()

            self.assertTrue(executable.exists())
            self.assertTrue(media.exists())
            self.assertTrue((install / ad.PORTABLE_MARKER_NAME).exists())
            self.assertTrue(bystander.exists())
            self.assertFalse((install / "config.json").exists())
            self.assertFalse((install / "site-logins").exists())
            self.assertFalse((install / "download-temp").exists())
            for name in (
                ".cookies.probe.deadbeef.txt",
                ".cookies.dl_1.txt",
                "server.log.1",
                "crash.log.1",
                "config.json.corrupt-20260811120000",
                ".history.json.deadbeef.tmp",
                ".AstraDownloader.update.deadbeef.exe",
                ".yt-dlp.update.deadbeef.exe",
                ".whisper.deadbeef.zip",
                "archive.txt",
            ):
                self.assertFalse((install / name).exists(), name)

    def test_uninstall_removes_the_integration_stamp(self):
        deleted = []

        def delete_key(_root, path):
            deleted.append(path)

        fake_winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            DeleteKey=delete_key,
        )
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(sys.modules, {"winreg": fake_winreg}), \
             mock.patch.object(ad, "write_persistent_log"), \
             mock.patch.object(ad, "stop_running_companion_for_uninstall"), \
             mock.patch.object(ad.subprocess, "run"), \
             mock.patch.object(ad, "NATIVE_HOST_DIR", Path(tmp) / "native"), \
             mock.patch.object(ad, "INSTALL_DIR", Path(tmp) / "AstraDownloader"):
            with self.assertRaises(SystemExit) as ctx:
                ad.run_uninstall()

        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(ad.INTEGRATIONS_STAMP_KEY, deleted)

    def test_uninstall_shutdown_does_not_kill_other_data_roots(self):
        with mock.patch.object(ad, "send_instance_command", return_value=True) as send, \
             mock.patch.object(ad.time, "sleep") as sleep, \
             mock.patch.object(ad.sys, "platform", "win32"), \
             mock.patch.object(ad.subprocess, "run") as run:
            self.assertTrue(ad.stop_running_companion_for_uninstall())

        send.assert_called_once_with("shutdown", attempts=3, delay=0.2)
        sleep.assert_called_once_with(0.75)
        run.assert_not_called()

    def test_shutdown_instance_command_closes_owned_window(self):
        class Window:
            pass

        window = Window()
        events = []
        window._append_log = events.append
        window._force_close = lambda: events.append("closed")

        ad.MainWindow._handle_instance_command(window, "shutdown")

        self.assertEqual(events[-1], "closed")

    def test_delayed_install_dir_removal_only_accepts_app_owned_dir_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(ad.is_safe_install_dir_for_removal(Path(tmp) / "AstraDownloader"))
            self.assertFalse(ad.is_safe_install_dir_for_removal(Path(tmp) / "NotAstraDownloader"))
            self.assertFalse(ad.is_safe_install_dir_for_removal(Path(tmp)))

    @unittest.skipUnless(sys.platform == "win32", "the delayed removal is a Windows path")
    def test_delayed_install_dir_removal_actually_deletes_the_directory(self):
        # The outcome is the contract. An argv-shape assertion let a version
        # ship that spawned a well-formed command which removed nothing:
        # `powershell -Command <script> <path>` never populates $args.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AstraDownloader"
            (target / "site-logins").mkdir(parents=True)
            (target / "site-logins" / "youtube.com.txt").write_text("canary", encoding="utf-8")

            spawned = []
            real_popen = ad.subprocess.Popen

            def capture(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                spawned.append(process)
                return process

            with mock.patch.object(ad.subprocess, "Popen", capture):
                self.assertTrue(ad.spawn_delayed_install_dir_removal(target))

            self.assertEqual(len(spawned), 1)
            spawned[0].wait(timeout=30)
            self.assertFalse(
                target.exists(),
                "the delayed removal reported success and left the install directory behind",
            )

    def test_delayed_install_dir_removal_quotes_a_path_containing_a_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            awkward = Path(tmp) / "o'brien's data" / "AstraDownloader"
            awkward.mkdir(parents=True)
            with mock.patch.object(ad.sys, "platform", "win32"), \
                    mock.patch.object(ad.subprocess, "Popen") as popen:
                self.assertTrue(ad.spawn_delayed_install_dir_removal(awkward))
                args = popen.call_args.args[0]

        script = args[-1]
        self.assertEqual(args[0], ad.system32_command("powershell"))
        self.assertNotIn("$args", script)
        self.assertIn(str(awkward.resolve()).replace("'", "''"), script)
        self.assertNotIn("cmd", args)
        self.assertNotIn("rmdir", args)


class PortableModeTests(unittest.TestCase):
    def test_portable_mode_requested_by_flag_or_environment(self):
        self.assertTrue(ad.portable_mode_requested(["--portable"]))
        self.assertFalse(ad.portable_mode_requested(["--background"]))
        with mock.patch.dict(os.environ, {"ASTRA_PORTABLE": "yes"}, clear=False):
            self.assertTrue(ad.portable_mode_requested([]))

    def test_portable_marker_selects_a_frozen_copy_outside_managed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portable = root / "Portable"
            managed = root / "AppData" / "AstraDownloader"
            executable = portable / "AstraDownloader.exe"
            portable.mkdir(parents=True)
            executable.write_bytes(b"portable")
            ad.portable_marker_path(executable).write_text("portable\n", encoding="utf-8")

            self.assertTrue(ad.portable_mode_requested(
                [], executable=executable, install_dir=managed, frozen=True,
            ))
            self.assertFalse(ad.portable_mode_requested(
                [], executable=managed / "AstraDownloader.exe",
                install_dir=managed, frozen=True,
            ))
            self.assertFalse(ad.portable_mode_requested(
                ["--install"], executable=executable,
                install_dir=managed, frozen=True,
            ))

    def test_one_file_copy_needs_the_explicit_portable_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "Downloads" / "AstraDownloader.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"one-file")
            self.assertFalse(ad.portable_mode_requested(
                [], executable=executable,
                install_dir=root / "AppData" / "AstraDownloader",
                frozen=True,
            ))
            self.assertTrue(ad.portable_mode_requested(
                ["--portable"], executable=executable,
                install_dir=root / "AppData" / "AstraDownloader",
                frozen=True,
            ))

    def test_instance_ports_and_mutex_namespace_follow_the_state_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "AppData" / "AstraDownloader"
            portable_a = root / "PortableA"
            portable_b = root / "PortableB"
            self.assertEqual(
                ad.instance_ports_for_root(installed, installed),
                (ad.INSTANCE_CONTROL_PORT_DEFAULT, ad.INSTANCE_LOCK_PORT_DEFAULT),
            )
            self.assertNotEqual(
                ad.instance_ports_for_root(portable_a, installed),
                ad.instance_ports_for_root(portable_b, installed),
            )
            self.assertNotEqual(
                ad.instance_namespace_for_root(portable_a),
                ad.instance_namespace_for_root(portable_b),
            )

    def test_onedir_build_is_never_relocated_or_silently_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "AstraDownloader.exe"
            (root / "_internal").mkdir()
            executable.write_bytes(b"onedir")
            with mock.patch.object(ad, "is_frozen_app", return_value=True), \
                 mock.patch.object(ad, "current_executable_path", return_value=executable), \
                 mock.patch.object(ad, "PORTABLE_MODE", False), \
                 mock.patch.object(ad, "write_persistent_log") as log:
                self.assertTrue(ad.is_onedir_build())
                self.assertEqual(ad.ensure_installed_executable(), executable)
                self.assertEqual(ad.companion_install_exit_code(["--install"]), 2)
            log.assert_called_once()

    def test_portable_one_file_self_update_restarts_with_the_portable_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b"MZ" + (b"portable-update" * 256)
            expected_hash = "a" * 64

            def fake_download(_url, path, **_kwargs):
                Path(path).write_bytes(payload)

            with mock.patch.object(ad, "INSTALL_DIR", root), \
                 mock.patch.object(ad, "PORTABLE_MODE", True), \
                 mock.patch.object(ad, "is_onedir_build", return_value=False), \
                 mock.patch.object(ad, "fetch_latest_companion_version", return_value="9.9.9"), \
                 mock.patch.object(ad, "download_file_atomic", side_effect=fake_download), \
                 mock.patch.object(ad, "validate_companion_update_binary"), \
                 mock.patch.object(ad, "fetch_expected_sha256", return_value=expected_hash), \
                 mock.patch.object(ad, "verify_file_sha256"), \
                 mock.patch.object(ad, "probe_companion_update_binary", return_value=True), \
                 mock.patch.object(ad, "schedule_companion_update_restart", return_value={"scheduled": True}) as schedule, \
                 mock.patch.object(ad, "write_persistent_log"), \
                 mock.patch.object(ad, "schedule_companion_process_exit"):
                result = ad._run_companion_self_update_unlocked(restart=False)

            self.assertTrue(result["ok"])
            self.assertEqual(schedule.call_args.args[2], ["--start-server", "--portable"])

    def test_portable_one_folder_self_update_fails_before_downloading(self):
        with mock.patch.object(ad, "PORTABLE_MODE", True), \
             mock.patch.object(ad, "is_onedir_build", return_value=True), \
             mock.patch.object(ad, "fetch_latest_companion_version") as fetch:
            result = ad._run_companion_self_update_unlocked(restart=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "portable-onedir-update-unsupported")
        fetch.assert_not_called()

    def test_onedir_archive_carries_the_portable_marker(self):
        import importlib.util

        build_path = Path(ad.__file__).with_name("build.py")
        spec = importlib.util.spec_from_file_location("astra_test_build", build_path)
        build_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "AstraDownloader"
            source.mkdir()
            (source / "AstraDownloader.exe").write_bytes(b"MZ")
            archive_path = root / "AstraDownloader-onedir.zip"
            build_module.write_onedir_archive(source, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn(
                    "AstraDownloader/" + build_module.PORTABLE_MARKER_NAME,
                    archive.namelist(),
                )

    def test_portable_state_root_is_the_executable_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "AstraDownloader.exe"
            with mock.patch.object(ad.sys, "frozen", True, create=True), \
                 mock.patch.object(ad.sys, "executable", str(executable)):
                self.assertEqual(ad.runtime_state_dir(True), executable.parent.resolve())

    def test_portable_install_target_and_copy_stay_with_the_running_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "AstraDownloader.exe"
            executable.write_bytes(b"portable")
            with mock.patch.object(ad, "PORTABLE_MODE", True), \
                 mock.patch.object(ad, "is_frozen_app", return_value=True), \
                 mock.patch.object(ad, "current_executable_path", return_value=executable), \
                 mock.patch.object(ad, "atomic_copy_verified") as copy:
                self.assertEqual(ad.install_target_exe(), executable)
                self.assertEqual(ad.ensure_installed_executable(), executable)
            copy.assert_not_called()

    def test_portable_integrations_are_a_noop(self):
        with mock.patch.object(ad, "PORTABLE_MODE", True), \
             mock.patch.object(ad, "launch_command_parts", return_value=("portable", [])) as launch, \
             mock.patch.object(ad, "register_desktop_shortcut") as desktop, \
             mock.patch.object(ad, "register_start_menu_shortcut") as start_menu, \
             mock.patch.object(ad, "register_startup_task") as startup, \
             mock.patch.object(ad, "register_protocol_handlers") as protocol:
            self.assertEqual(ad.ensure_system_integrations(), ("portable", []))
        launch.assert_called_once_with(prefer_installed=False)
        desktop.assert_not_called()
        start_menu.assert_not_called()
        startup.assert_not_called()
        protocol.assert_not_called()

    def test_silent_install_requires_a_packaged_nonportable_copy(self):
        with mock.patch.object(ad, "write_persistent_log") as log:
            self.assertEqual(ad.companion_install_exit_code(["--install"]), 2)
        log.assert_called_once()

    def test_silent_install_rejects_portable_combination(self):
        with mock.patch.object(ad, "PORTABLE_MODE", True), \
             mock.patch.object(ad, "write_persistent_log") as log:
            self.assertEqual(
                ad.companion_install_exit_code(["--install", "--portable"]),
                2,
            )
        log.assert_called_once()

    def test_silent_install_registers_integrations_after_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AstraDownloader.exe"
            target.write_bytes(b"installed")
            with mock.patch.object(ad, "PORTABLE_MODE", False), \
                 mock.patch.object(ad, "is_frozen_app", return_value=True), \
                 mock.patch.object(ad, "install_target_exe", return_value=target), \
                 mock.patch.object(ad, "ensure_installed_executable", return_value=target), \
                 mock.patch.object(ad, "ensure_system_integrations") as integrations, \
                 mock.patch.object(ad.sys, "stdout", io.StringIO()):
                self.assertEqual(ad.companion_install_exit_code(["--install"]), 0)
        integrations.assert_called_once_with(prefer_installed=True, force=True)
