#!/usr/bin/env python3
"""
Build the one-file and one-folder Astra Downloader distributions.
Outputs both artifacts and their checksum sidecars beside the logo/icon.
"""
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError as exc:
    raise SystemExit(
        "The release builder requires packaging from the reviewed constraints graph. "
        "Create the release virtual environment before running build.py."
    ) from exc

HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent
SCRIPT = HERE / "astra_downloader.py"
ICON = ROOT / "AstraDownloader.ico"
OUT_EXE = ROOT / "AstraDownloader.exe"
OUT_SHA256 = ROOT / "AstraDownloader.exe.sha256"
OUT_ONEDIR_ZIP = ROOT / "AstraDownloader-onedir.zip"
OUT_ONEDIR_SHA256 = ROOT / "AstraDownloader-onedir.zip.sha256"
PORTABLE_MARKER_NAME = ".astradownloader-portable"
TRANSLATIONS_DIR = HERE / "translations"
TRANSLATION_BUILD_SCRIPT = ROOT / "scripts" / "build-companion-translations.py"

BUILD_DIR = HERE / "build"
DIST_DIR = HERE / "dist"
SPEC_DIR = BUILD_DIR / "spec"
BUILD_METADATA = BUILD_DIR / "companion-build-metadata.json"
REQUIREMENTS = HERE / "requirements.txt"
RELEASE_CONSTRAINTS = HERE / "constraints-release.txt"
SUPPORTED_RELEASE_PYTHONS = {(3, 11), (3, 12)}
RELEASE_PLATFORM = {
    "system": "Windows",
    "minimumVersion": "10",
    "architecture": "x86_64",
}


def parse_release_constraints(path=None):
    path = Path(path or RELEASE_CONSTRAINTS)
    constraints = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"Missing reviewed release constraints: {path}") from exc
    for line_number, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
        if not match:
            raise SystemExit(
                f"Release constraint line {line_number} must be one exact name==version pin: {raw}"
            )
        name, version = match.groups()
        key = canonicalize_name(name)
        if key in constraints:
            raise SystemExit(f"Duplicate release constraint for {name}")
        constraints[key] = {"name": name, "version": version}
    if not constraints:
        raise SystemExit("Reviewed release constraints are empty")
    return constraints


def _active_dependency(requirement):
    if requirement.marker is None:
        return True
    environment = default_environment()
    environment["extra"] = ""
    return requirement.marker.evaluate(environment)


def verify_release_environment():
    """Fail unless every reviewed node is installed at its exact version.

    Dependency metadata is traversed as well: any active edge to a package not
    present in the reviewed graph fails the build instead of silently becoming
    part of a fresh PyInstaller environment.
    """
    python_minor = sys.version_info[:2]
    if python_minor not in SUPPORTED_RELEASE_PYTHONS:
        supported = ", ".join(".".join(map(str, value)) for value in sorted(SUPPORTED_RELEASE_PYTHONS))
        raise SystemExit(
            f"Astra Downloader release builds require CPython {supported}; "
            f"active interpreter is {platform.python_version()}."
        )
    if sys.platform != "win32":
        raise SystemExit("Astra Downloader release builds must run on Windows for the Windows 10 x64 artifact.")

    constraints = parse_release_constraints()
    direct_names = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        key = canonicalize_name(requirement.name)
        direct_names.add(key)
        if key not in constraints:
            raise SystemExit(f"Direct requirement {requirement.name} is absent from release constraints")
        if constraints[key]["version"] not in requirement.specifier:
            raise SystemExit(
                f"Release pin {requirement.name}=={constraints[key]['version']} violates {requirement.specifier}"
            )
    direct_names.add("pyinstaller")

    distributions = {}
    for key, constraint in constraints.items():
        try:
            dist = importlib.metadata.distribution(constraint["name"])
        except importlib.metadata.PackageNotFoundError as exc:
            raise SystemExit(
                f"Release environment is incomplete: {constraint['name']}=={constraint['version']} is not installed. "
                f"Install with -r {REQUIREMENTS.name} -c {RELEASE_CONSTRAINTS.name}."
            ) from exc
        if dist.version != constraint["version"]:
            raise SystemExit(
                f"Release environment drift: {constraint['name']}=={dist.version} is installed; "
                f"reviewed version is {constraint['version']}."
            )
        distributions[key] = dist

    graph = {}
    for key, dist in distributions.items():
        dependencies = set()
        for raw_requirement in dist.requires or ():
            requirement = Requirement(raw_requirement)
            if not _active_dependency(requirement):
                continue
            dep_key = canonicalize_name(requirement.name)
            if dep_key not in constraints:
                raise SystemExit(
                    f"Unreviewed active dependency: {dist.metadata.get('Name')} -> {requirement}"
                )
            dep_version = constraints[dep_key]["version"]
            if requirement.specifier and dep_version not in requirement.specifier:
                raise SystemExit(
                    f"Reviewed pin {requirement.name}=={dep_version} violates {dist.metadata.get('Name')} requirement {requirement.specifier}"
                )
            dependencies.add(dep_key)
        graph[key] = sorted(dependencies)

    def closure(root):
        found = set()
        pending = [root]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(graph.get(current, ()))
        return found

    build_names = closure("pyinstaller")
    return {
        "constraints": constraints,
        "distributions": distributions,
        "graph": graph,
        "directNames": sorted(direct_names),
        "buildNames": build_names,
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sha256_sidecar(exe_path, sidecar_path=None):
    """Write the standard checksum manifest beside the exact EXE bytes."""
    exe_path = Path(exe_path)
    sidecar_path = Path(
        sidecar_path or exe_path.with_name(exe_path.name + ".sha256")
    )
    digest = sha256_file(exe_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        f"{digest}  {exe_path.name}\n",
        encoding="ascii",
    )
    return digest


def write_onedir_archive(source_dir, archive_path, metadata_path=None):
    """Pack a one-folder build under a stable root, optionally with metadata."""
    source_dir = Path(source_dir)
    archive_path = Path(archive_path)
    if not source_dir.is_dir():
        raise SystemExit(f"Missing one-folder build directory: {source_dir}")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = archive_path.with_name(archive_path.name + ".tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    try:
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            marker = zipfile.ZipInfo(
                (Path(source_dir.name) / PORTABLE_MARKER_NAME).as_posix()
            )
            marker.date_time = (1980, 1, 1, 0, 0, 0)
            marker.compress_type = zipfile.ZIP_DEFLATED
            marker.external_attr = 0o100644 << 16
            archive.writestr(marker, b"Astra Downloader portable one-folder layout\n")
            if metadata_path is not None:
                metadata_path = Path(metadata_path)
                if not metadata_path.is_file():
                    raise SystemExit(f"Missing companion build metadata: {metadata_path}")
                metadata = zipfile.ZipInfo(
                    (Path(source_dir.name) / metadata_path.name).as_posix()
                )
                metadata.date_time = (1980, 1, 1, 0, 0, 0)
                metadata.compress_type = zipfile.ZIP_DEFLATED
                metadata.external_attr = 0o100644 << 16
                archive.writestr(metadata, metadata_path.read_bytes())
            files = sorted(
                (path for path in source_dir.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(source_dir).as_posix().lower(),
            )
            for path in files:
                relative = Path(source_dir.name) / path.relative_to(source_dir)
                info = zipfile.ZipInfo(relative.as_posix())
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary_path, archive_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return archive_path


def iter_toc_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_toc_strings(item)


def distribution_license_files(dist):
    results = []
    for item in dist.files or ():
        lowered = str(item).replace("\\", "/").lower()
        name = Path(lowered).name
        if not any(token in name for token in ("license", "copying", "notice", "copyright")):
            continue
        path = Path(dist.locate_file(item))
        if not path.is_file():
            continue
        results.append({
            "path": str(item).replace("\\", "/"),
            "sha256": sha256_file(path),
        })
    return sorted(results, key=lambda item: item["path"].lower())


def distribution_record_hash(dist):
    for item in dist.files or ():
        if str(item).replace("\\", "/").lower().endswith(".dist-info/record"):
            path = Path(dist.locate_file(item))
            if path.is_file():
                return sha256_file(path)
    return None


def distribution_metadata(dist, scope):
    metadata = dist.metadata
    name = metadata.get("Name") or "unknown"
    project_urls = metadata.get_all("Project-URL") or []
    source_url = metadata.get("Home-page") or ""
    if not source_url and project_urls:
        source_url = project_urls[0].partition(",")[2].strip()
    return {
        "name": name,
        "version": dist.version,
        "scope": scope,
        "license": metadata.get("License-Expression") or metadata.get("License") or "",
        "sourceUrl": source_url,
        "recordSha256": distribution_record_hash(dist),
        "licenseFiles": distribution_license_files(dist),
    }


def write_build_metadata(exe_path, analysis_toc=None):
    """Write metadata tied to the exact one-file analysis and EXE bytes."""
    exe_path = Path(exe_path)
    analysis_toc = Path(
        analysis_toc or BUILD_DIR / "AstraDownloader" / "Analysis-00.toc"
    )
    if not analysis_toc.is_file():
        raise SystemExit(f"Missing PyInstaller analysis inventory: {analysis_toc}")
    try:
        toc = ast.literal_eval(analysis_toc.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise SystemExit(f"Could not parse PyInstaller analysis inventory: {exc}") from exc

    packaged_paths = {
        str(Path(value).resolve()).casefold()
        for value in iter_toc_strings(toc)
        if Path(value).is_absolute()
    }
    release_environment = verify_release_environment()
    resolved_packages = []
    distributions = []
    for key, dist in sorted(release_environment["distributions"].items()):
        name = canonicalize_name(dist.metadata.get("Name") or "")
        included = any(
            str(Path(dist.locate_file(item)).resolve()).casefold() in packaged_paths
            for item in dist.files or ()
        )
        scope = "embedded" if included else (
            "build" if key in release_environment["buildNames"] else "validation"
        )
        record = distribution_metadata(dist, scope)
        record["dependsOn"] = release_environment["graph"].get(key, [])
        resolved_packages.append(record)
        if included or key == "pyinstaller":
            distributions.append(record)

    if not any(item["name"].casefold() == "pyqt6" for item in distributions):
        raise SystemExit("PyInstaller analysis did not inventory the embedded PyQt6 distribution")
    distributions.sort(key=lambda item: (item["name"].casefold(), item["scope"]))

    source = SCRIPT.read_text(encoding="utf-8")
    version_match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if not version_match:
        raise SystemExit(f"Could not read APP_VERSION from {SCRIPT}")

    version = version_match.group(1)
    build_id = sha256_file(analysis_toc)
    artifact = {
        "name": exe_path.name,
        "size": exe_path.stat().st_size,
        "sha256": sha256_file(exe_path),
    }
    payload = {
        "schemaVersion": 2,
        "version": version,
        "buildId": build_id,
        "artifact": artifact,
        "artifacts": {
            "onefile": dict(artifact),
            "onedir": {
                "name": OUT_ONEDIR_ZIP.name,
                "version": version,
                "buildId": build_id,
            },
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "license": "Python-2.0",
            "sourceUrl": f"https://www.python.org/downloads/release/python-{platform.python_version().replace('.', '')}/",
        },
        "platform": RELEASE_PLATFORM,
        "resolution": {
            "schemaVersion": 1,
            "constraintsPath": "astra_downloader/constraints-release.txt",
            "constraintsSha256": sha256_file(RELEASE_CONSTRAINTS),
            "supportedPythonMinors": ["3.11", "3.12"],
            "direct": release_environment["directNames"],
            "packages": resolved_packages,
        },
        "distributions": distributions,
    }
    BUILD_METADATA.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def assert_inside_workspace(path):
    resolved = path.resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise SystemExit(f"Refusing to clean path outside the repository: {resolved}")


def clean():
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            assert_inside_workspace(d)
            shutil.rmtree(d, ignore_errors=True)
    for artifact in (OUT_EXE, OUT_SHA256, OUT_ONEDIR_ZIP, OUT_ONEDIR_SHA256):
        if not artifact.exists() and not artifact.is_symlink():
            continue
        assert_inside_workspace(artifact)
        if artifact.is_dir():
            raise SystemExit(f"Refusing to remove release directory: {artifact}")
        artifact.unlink()


def preflight():
    if not SCRIPT.exists():
        raise SystemExit(f"Missing entry point: {SCRIPT}")
    if not ICON.exists():
        raise SystemExit(f"Missing icon: {ICON}")
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit(
            "PyInstaller is not installed in the active virtual environment. Run: "
            f"{sys.executable} -m pip install --require-virtualenv pyinstaller"
        )
    verify_release_environment()


def prepare_translations():
    """Refresh Qt catalogues when tooling exists, then fail closed on gaps."""
    compiler = next(
        (
            shutil.which(name)
            for name in ("pyside6-lrelease", "lrelease", "lrelease-qt6")
            if shutil.which(name)
        ),
        None,
    )
    if compiler:
        subprocess.check_call([sys.executable, str(TRANSLATION_BUILD_SCRIPT)])
    expected = (
        "ar", "de", "en", "es", "fr", "it", "ja", "ko", "pt_BR", "ru",
        "zh_CN",
    )
    missing = [
        locale
        for locale in expected
        if not (TRANSLATIONS_DIR / f"astra_downloader_{locale}.ts").exists()
        or not (TRANSLATIONS_DIR / f"astra_downloader_{locale}.qm").exists()
    ]
    if missing:
        raise SystemExit(
            "Missing companion translation catalogues: " + ", ".join(missing)
        )
    if not compiler:
        stale = [
            locale
            for locale in expected
            if (TRANSLATIONS_DIR / f"astra_downloader_{locale}.qm").stat().st_mtime_ns
            < (TRANSLATIONS_DIR / f"astra_downloader_{locale}.ts").stat().st_mtime_ns
        ]
        if stale:
            raise SystemExit(
                "Qt translation compiler unavailable (tried pyside6-lrelease, "
                "lrelease, lrelease-qt6); stale .qm catalogues for: "
                + ", ".join(stale)
            )
        print(
            "WARNING: Qt translation compiler unavailable (tried "
            "pyside6-lrelease, lrelease, lrelease-qt6); using existing .qm catalogues."
        )


def pyinstaller_args(mode):
    if mode not in ("onefile", "onedir"):
        raise ValueError(f"Unsupported PyInstaller mode: {mode}")
    return [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--{mode}",
        "--windowed",
        "--name", "AstraDownloader",
        "--icon", str(ICON),
        "--add-data", (
            str(TRANSLATIONS_DIR / "*.qm")
            + os.pathsep
            + "translations"
        ),
        "--specpath", str(SPEC_DIR),
        # Required hidden imports
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "flask",
        "--hidden-import", "werkzeug",
        "--hidden-import", "requests",
        # Boundary modules are imported lazily while the extraction from the
        # legacy composition root proceeds. Keep them explicit in the frozen
        # graph so legacy imports remain available in packaged builds.
        "--hidden-import", "_compat",
        "--hidden-import", "companion_ports",
        "--hidden-import", "config",
        "--hidden-import", "download",
        "--hidden-import", "health",
        "--hidden-import", "i18n",
        "--hidden-import", "routes",
        "--hidden-import", "gui",
        # Exclude unused stdlib to shrink size
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        str(SCRIPT),
    ]


def run_pyinstaller(mode):
    print(f"Building AstraDownloader ({mode})...")
    subprocess.check_call(pyinstaller_args(mode), cwd=str(HERE))


def build():
    preflight()
    prepare_translations()
    clean()
    SPEC_DIR.mkdir(parents=True, exist_ok=True)

    run_pyinstaller("onefile")
    built = DIST_DIR / "AstraDownloader.exe"
    if not built.exists():
        raise SystemExit(f"Build failed: {built} not found")

    onefile_analysis = BUILD_DIR / "AstraDownloader" / "Analysis-00.toc"
    if not onefile_analysis.is_file():
        raise SystemExit(f"Missing one-file PyInstaller analysis inventory: {onefile_analysis}")
    onefile_analysis_snapshot = BUILD_DIR / "AstraDownloader-onefile-Analysis-00.toc"
    shutil.copy2(onefile_analysis, onefile_analysis_snapshot)

    OUT_EXE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, OUT_EXE)

    run_pyinstaller("onedir")
    built_onedir = DIST_DIR / "AstraDownloader"
    write_build_metadata(OUT_EXE, analysis_toc=onefile_analysis_snapshot)
    write_onedir_archive(
        built_onedir,
        OUT_ONEDIR_ZIP,
        metadata_path=BUILD_METADATA,
    )

    write_sha256_sidecar(OUT_EXE, OUT_SHA256)
    write_sha256_sidecar(OUT_ONEDIR_ZIP, OUT_ONEDIR_SHA256)
    size_mb = OUT_EXE.stat().st_size / (1024 * 1024)
    print(f"OK: {OUT_EXE} ({size_mb:.1f} MB)")
    print(f"SHA-256 sidecar: {OUT_SHA256}")
    print(f"OK: {OUT_ONEDIR_ZIP} ({OUT_ONEDIR_ZIP.stat().st_size / (1024 * 1024):.1f} MB)")
    print(f"SHA-256 sidecar: {OUT_ONEDIR_SHA256}")
    print(f"License inventory input: {BUILD_METADATA}")


if __name__ == "__main__":
    build()
