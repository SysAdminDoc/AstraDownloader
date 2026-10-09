"""Verified replacement of a managed executable without touching user data."""

import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallResult:
    target: Path
    changed: bool = False
    stopped: bool = False
    previous_version: str = ''


class InstallationError(RuntimeError):
    def __init__(self, message, *, restart_previous=False):
        super().__init__(message)
        self.restart_previous = restart_previous


def _refresh_existing_checksum(target, checksum):
    sidecar = target.with_suffix(target.suffix + '.sha256')
    if not sidecar.exists():
        return
    text = f'{checksum}  {target.name}\n'
    if sidecar.read_text(encoding='utf-8').strip() == text.strip():
        return
    temporary = sidecar.with_name(f'.{sidecar.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(text, encoding='utf-8')
        os.replace(temporary, sidecar)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def installation_lock(directory, timeout=90):
    """Serialize setup processes; the OS releases the lock after a crash."""
    path = Path(directory) / '.AstraDownloader.install.lock'
    with path.open('a+b') as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b'\0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise InstallationError(
                        'Another setup is still running. Wait for it to finish, then open this file again.'
                    ) from error
                time.sleep(0.2)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def install_verified_copy(source, target, version, *, probe_version, compare_versions,
                          health_check, copy_verified, digest, stop_running,
                          progress=lambda _message: None, allow_downgrade=False):
    """Verify first, stop only this installation, then replace or restore it."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        return InstallResult(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    progress('Checking the installed version...')
    with installation_lock(target.parent):
        previous_version = probe_version(target) if target.is_file() else ''
        if (previous_version and not allow_downgrade
                and compare_versions(previous_version, version) > 0):
            return InstallResult(target, previous_version=previous_version)
        incoming_hash = digest(source)
        if not incoming_hash:
            raise InstallationError('The downloaded app could not be read. Download it again and retry.')
        if target.is_file() and digest(target) == incoming_hash:
            return InstallResult(target, previous_version=previous_version)

        stage = target.with_name(f'.AstraDownloader.install.{uuid.uuid4().hex}.exe')
        backup = target.with_name('.AstraDownloader.last-known-good.exe')
        existed = target.is_file()
        stopped = activated = backup_ready = False
        try:
            progress('Verifying the new app...')
            copy_verified(source, stage)
            if not health_check(stage, version):
                raise RuntimeError('The new app failed its startup check. Download the release again.')
            if existed:
                copy_verified(target, backup)
                backup_ready = True
            progress('Closing the running downloader...')
            stopped = stop_running()
            progress('Installing the update...' if existed else 'Installing Astra Downloader...')
            deadline = time.monotonic() + 5
            while True:
                try:
                    copy_verified(stage, target)
                    break
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)
            activated = True
            if digest(target) != incoming_hash or not health_check(target, version):
                raise RuntimeError('The installed app failed its startup check.')
            _refresh_existing_checksum(target, incoming_hash)
            return InstallResult(target, True, stopped, previous_version)
        except Exception as error:
            restored = not activated and existed
            if activated and backup_ready:
                progress('Restoring the previous version...')
                try:
                    copy_verified(backup, target)
                    _refresh_existing_checksum(target, digest(target))
                    restored = bool(previous_version and health_check(target, previous_version))
                except Exception as rollback_error:
                    raise InstallationError(
                        f'Setup failed and the previous app could not be restored. '
                        f'Your settings and downloads are unchanged. {rollback_error}'
                    ) from rollback_error
            elif activated:
                target.unlink(missing_ok=True)
            message = (
                'Setup could not finish. The previous app was kept. '
                if restored else 'Setup could not finish. '
            )
            raise InstallationError(message + str(error), restart_previous=stopped and restored) from error
        finally:
            try:
                stage.unlink(missing_ok=True)
            except OSError as error:
                logging.getLogger(__name__).warning('Could not remove setup staging file %s: %s', stage, error)
