import importlib.util
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


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
        self.assertGreaterEqual(len(constraints), 28)
        for required in ('pyinstaller', 'pyqt6', 'flask', 'requests', 'waitress', 'yt-dlp'):
            self.assertIn(required, constraints)
            self.assertTrue(constraints[required]['version'])

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
            packaged_pyqt = root / 'site-packages' / 'PyQt6' / '__init__.py'
            packaged_pyqt.parent.mkdir(parents=True)
            packaged_pyqt.write_text('fixture', encoding='utf-8')
            analysis.write_text(repr([str(packaged_pyqt)]), encoding='utf-8')
            constraints = root / 'constraints-release.txt'
            constraints.write_text('pyqt6==6.11.0\n', encoding='utf-8')
            script = root / 'astra_downloader.py'
            script.write_text('APP_VERSION = "2.6.0"\n', encoding='utf-8')
            metadata_path = root / 'companion-build-metadata.json'
            pyqt = Distribution('PyQt6', [packaged_pyqt])
            pyqt.version = '6.11.0'
            pyinstaller = Distribution('PyInstaller')

            environment = {
                'distributions': {'pyinstaller': pyinstaller, 'pyqt6': pyqt},
                'buildNames': {'pyinstaller'},
                'graph': {'pyinstaller': [], 'pyqt6': []},
                'directNames': ['pyinstaller', 'pyqt6'],
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
