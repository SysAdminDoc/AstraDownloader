"""Exercise Windows update activation without touching a real installation."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import astra_downloader as ad


class WindowsUpdateActivationTests(unittest.TestCase):
    def _helper(self, root):
        target = root / "AstraDownloader.exe"
        source = root / ".AstraDownloader.update.test.exe"
        target.write_bytes(b"old-companion")
        source.write_bytes(b"new-companion")
        with mock.patch.object(ad, "INSTALL_DIR", root), \
                mock.patch.object(ad.sys, "platform", "win32"), \
                mock.patch.object(ad.subprocess, "Popen"):
            ad.schedule_companion_update_restart(
                source, target, ["--start-server"], pid=2147483646,
                expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                expected_version="99.0.0", previous_version="98.0.0",
            )
        helper = next(root.glob(".AstraDownloader.apply-update.*.ps1"))
        return helper, source, target

    def test_helper_scopes_process_shutdown_and_gates_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper, _, _ = self._helper(Path(tmp))
            text = helper.read_text(encoding="utf-8")
        self.assertIn("$Process.SessionId -ne $helperSession", text)
        self.assertIn("$owner.Sid -ne $helperOwner", text)
        self.assertIn("$started -ne $ExpectedStartTicks", text)
        self.assertIn("Get-OwnedProcess $live $snapshot.StartTicks $snapshot.Path", text)
        self.assertIn("$verified.Process.Kill()", text)
        self.assertIn("Sort-Object Depth -Descending", text)
        self.assertIn("$parent.Process.ExitTime.ToUniversalTime().Ticks", text)
        self.assertIn("$runtimeNames -notcontains", text)
        self.assertIn("$stream.Lock(0, 1)", text)
        self.assertIn("$installLock.Unlock(0, 1)", text)
        self.assertNotIn("taskkill", text.lower())
        self.assertIn("if ($restartVerified)", text)
        self.assertIn("Write-TargetSidecar $targetHash", text)
        self.assertIn("Write-TargetSidecar $restoredHash", text)
        self.assertIn("$failureCode = 'process-shutdown-failed'", text)
        self.assertLess(text.index("Test-Companion $SourcePath $ExpectedVersion"),
                        text.index("\n    Wait-CompanionExit\n"))
        self.assertLess(text.index("\n    Wait-CompanionExit\n"),
                        text.index("$rollbackHash = Copy-Verified"))

    @unittest.skipUnless(os.name == "nt", "Windows activation helper")
    def test_activation_and_rollback_update_only_existing_sidecars(self):
        for outcome, has_sidecar in (("active", True), ("active", False),
                                     ("rolled-back", True), ("sidecar-rollback", True), ("locked-sidecar", True),
                                     ("rollback-failed", True),
                                     ("activation-failed", True), ("installed-version-changed", True)):
            with self.subTest(outcome=outcome, sidecar=has_sidecar), \
                    tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                helper, source, target = self._helper(root)
                old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                new_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                sidecar = target.with_name(target.name + ".sha256")
                if has_sidecar:
                    sidecar.write_text(f"{old_hash}  {target.name}\n", encoding="ascii")
                    if outcome == "locked-sidecar":
                        sidecar.chmod(0o444)
                overrides = """
$script:oldProbes = 0
function Test-Companion([string] $Path, [string] $Version) {
    if ($Path -eq $SourcePath) { return 'OUTCOME' -ne 'activation-failed' }
    if ($Version -eq $ExpectedVersion) { return 'OUTCOME' -in @('active', 'sidecar-rollback', 'locked-sidecar') }
    $script:oldProbes++
    if ('OUTCOME' -eq 'installed-version-changed') { return $false }
    return 'OUTCOME' -ne 'rollback-failed' -or $script:oldProbes -eq 1
}
function Start-Process($FilePath, $ArgumentList, $WindowStyle) {
    [IO.File]::WriteAllText("$TargetPath.relaunched", $FilePath)
}
$script:originalRecovery = ${function:Write-RecoveryState}
function Write-RecoveryState($Status, $ActiveVersion, $RollbackVersion, $ErrorCode) {
    if ('OUTCOME' -eq 'sidecar-rollback' -and $Status -eq 'active') { throw 'Recovery state write failed' }
    & $script:originalRecovery @PSBoundParameters
}
""".replace("OUTCOME", outcome)
                text = helper.read_text(encoding="utf-8")
                text = text.replace("$activated = $false", overrides + "\n$activated = $false", 1)
                text = text.replace("} catch {\n    $restartVerified = $false",
                                    "} catch {\n    Write-Output $_.Exception.Message\n    $restartVerified = $false", 1)
                helper.write_text(text, encoding="utf-8")
                state = root / "result.json"
                try:
                    result = subprocess.run([
                        ad.system32_command("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(helper), "-ProcessId", "2147483646",
                        "-SourcePath", str(source), "-TargetPath", str(target),
                        "-BackupPath", str(root / "rollback.exe"), "-StatePath", str(state),
                        "-RestartArgs", "--start-server", "-ExpectedSHA256", new_hash,
                        "-ExpectedVersion", "99.0.0", "-PreviousVersion", "98.0.0",
                    ], capture_output=True, text=True, timeout=30, check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                finally:
                    if has_sidecar:
                        sidecar.chmod(0o666)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                recovery = json.loads(state.read_text(encoding="utf-8"))
                expected_status = "rolled-back" if outcome in {"sidecar-rollback", "locked-sidecar"} else outcome
                if outcome == "installed-version-changed":
                    expected_status = "activation-failed"
                    self.assertEqual(recovery["error_code"], outcome)
                self.assertEqual(recovery["status"], expected_status, (recovery, result.stdout, result.stderr))
                self.assertEqual(target.read_bytes(), b"new-companion" if outcome == "active" else b"old-companion")
                self.assertEqual(target.with_name(target.name + ".relaunched").exists(),
                                 outcome in {"active", "rolled-back", "sidecar-rollback", "locked-sidecar"})
                self.assertEqual(sidecar.exists(), has_sidecar)
                if has_sidecar:
                    expected_hash = new_hash if outcome == "active" else old_hash
                    self.assertEqual(sidecar.read_text(encoding="ascii").split()[0], expected_hash)

    @unittest.skipUnless(os.name == "nt", "Windows process identity")
    def test_shutdown_stops_only_owned_exact_path_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper, _, target = self._helper(root)
            control = root / "unrelated.exe"
            ping = Path(os.environ["SystemRoot"]) / "System32" / "ping.exe"
            shutil.copyfile(ping, target)
            shutil.copyfile(ping, control)
            processes = [subprocess.Popen(
                [str(path), "-t", "127.0.0.1"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            ) for path in (target, target, control)]
            try:
                prefix = helper.read_text(encoding="utf-8").split("$activated = $false", 1)[0]
                helper.write_text(prefix + """
$candidate = Get-Process -Id TARGETPID
$wrongIdentity = Get-OwnedTargetProcess $candidate ($candidate.StartTime.ToUniversalTime().Ticks + 1)
if ($null -ne $wrongIdentity) { throw 'A changed process identity was accepted' }
$savedOwner = $helperOwner
$helperOwner = 'wrong-owner'
if ($null -ne (Get-OwnedTargetProcess $candidate)) { throw 'A different owner was accepted' }
$helperOwner = $savedOwner
$savedSession = $helperSession
$helperSession = -1
if ($null -ne (Get-OwnedTargetProcess $candidate)) { throw 'A different session was accepted' }
$helperSession = $savedSession
$candidate.Dispose()
Wait-CompanionExit -GraceSeconds 0.1
""".replace("TARGETPID", str(processes[0].pid)), encoding="utf-8")
                result = subprocess.run([
                    ad.system32_command("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(helper), "-ProcessId", str(processes[0].pid),
                    "-TargetPath", str(target),
                ], capture_output=True, text=True, timeout=25, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for process in processes[:2]:
                    process.wait(timeout=5)
                self.assertIsNone(processes[2].poll(), "An unrelated executable was stopped")
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "Windows installer lock")
    def test_helper_lock_interoperates_with_python_installer_lock(self):
        import msvcrt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper, _, target = self._helper(root)
            prefix = helper.read_text(encoding="utf-8").split("$activated = $false", 1)[0]
            helper.write_text(prefix + """
$lock = Enter-InstallLock -TimeoutSeconds 0.25
try { [IO.File]::WriteAllText("$TargetPath.lock-acquired", 'yes') }
finally { try { $lock.Unlock(0, 1) } finally { $lock.Dispose() } }
""", encoding="utf-8")
            args = [ad.system32_command("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(helper), "-TargetPath", str(target)]
            with (root / ".AstraDownloader.install.lock").open("w+b") as lock:
                lock.write(b"\0")
                lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    blocked = subprocess.run(args, capture_output=True, text=True, timeout=10,
                                             check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertNotEqual(blocked.returncode, 0)
                    self.assertIn("installation is still running", blocked.stderr)
                    self.assertFalse(target.with_name(target.name + ".lock-acquired").exists())
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            released = subprocess.run(args, capture_output=True, text=True, timeout=10,
                                      check=False, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(released.returncode, 0, released.stderr)
            self.assertTrue(target.with_name(target.name + ".lock-acquired").exists())

    @unittest.skipUnless(os.name == "nt", "Windows descendant identity")
    def test_shutdown_retains_runtime_children_and_preserves_browser_children(self):
        for orphan in (False, True):
            with self.subTest(parent_exits_during_grace=orphan), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                helper, _, target = self._helper(root)
                system = Path(os.environ["SystemRoot"]) / "System32"
                worker = root / "ffmpeg.exe"
                browser = root / "chrome.exe"
                shutil.copyfile(system / "cmd.exe", target)
                shutil.copyfile(system / "ping.exe", worker)
                shutil.copyfile(system / "ping.exe", browser)
                (root / "launch.cmd").write_text(
                    f'@echo off\nstart "" /b "{browser}" -t 127.0.0.1\n"{worker}" -t 127.0.0.1\n',
                    encoding="ascii")
                prefix = helper.read_text(encoding="utf-8").split("$activated = $false", 1)[0]
                exercise = r'''
$workerPath = Join-Path ([IO.Path]::GetDirectoryName($TargetPath)) 'ffmpeg.exe'
$browserPath = Join-Path ([IO.Path]::GetDirectoryName($TargetPath)) 'chrome.exe'
$batch = Join-Path ([IO.Path]::GetDirectoryName($TargetPath)) 'launch.cmd'
$parent = $null
try {
    $parent = Start-Process -FilePath $TargetPath -ArgumentList ('/d /s /c ""' + $batch + '""') -WindowStyle Hidden -PassThru
    $ProcessId = $parent.Id
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $children = @(Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId = $($parent.Id)")
        if ($children.Count -ge 2) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    $workerId = ($children | Where-Object { $_.Name -eq 'ffmpeg.exe' }).ProcessId
    $browserId = ($children | Where-Object { $_.Name -eq 'chrome.exe' }).ProcessId
    if (-not $workerId -or -not $browserId) { throw 'Private child processes did not start' }
    $workerProcess = Get-Process -Id $workerId
    $browserProcess = Get-Process -Id $browserId
    $null = $workerProcess.Handle
    $null = $browserProcess.Handle
    $script:scan = ${function:Update-CompanionProcesses}
    $script:parentExited = $false
    function Update-CompanionProcesses([hashtable] $Tracked) {
        & $script:scan $Tracked
        if (ORPHAN -and -not $script:parentExited) {
            if (@($Tracked.Values | Where-Object { $_.Process.Id -eq $workerId }).Count -eq 0) {
                throw 'Runtime child was not captured before its parent exited'
            }
            $parent.Kill()
            $null = $parent.WaitForExit(5000)
            $script:parentExited = $true
        }
    }
    Wait-CompanionExit -GraceSeconds 0.2
    if (-not $workerProcess.HasExited) { throw 'A captured runtime child survived' }
    if ($browserProcess.HasExited) { throw 'A browser child was stopped' }
    if (-not $parent.HasExited) { throw 'The private companion process survived' }
} finally {
    # Only the three executables copied into this test's private directory.
    foreach ($candidate in (Get-Process)) {
        try {
            if ($candidate.Path -in @($TargetPath, $workerPath, $browserPath)) {
                $candidate.Kill()
                $null = $candidate.WaitForExit(5000)
            }
        } catch {
            # A test-owned process can exit between enumeration and cleanup.
        } finally { $candidate.Dispose() }
    }
    if ($null -ne $parent) { $parent.Dispose() }
    if ($null -ne $workerProcess) { $workerProcess.Dispose() }
    if ($null -ne $browserProcess) { $browserProcess.Dispose() }
}
'''.replace("ORPHAN", "$true" if orphan else "$false")
                helper.write_text(prefix + exercise, encoding="utf-8")
                result = subprocess.run([
                    ad.system32_command("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(helper), "-TargetPath", str(target),
                ], capture_output=True, text=True, timeout=30, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
