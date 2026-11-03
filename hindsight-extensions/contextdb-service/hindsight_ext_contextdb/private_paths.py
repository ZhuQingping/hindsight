"""Private persisted state on POSIX hosts and native Windows NTFS."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


def windows_acl(path: Path, *, protect: bool = False) -> None:
    # Pass the path through stdin, never interpolate it into PowerShell code.
    # Mode bits on Windows do not express access control; validate the real DACL.
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$p = [Console]::In.ReadToEnd()
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$item = Get-Item -LiteralPath $p -Force
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point' }
if ($env:CONTEXTBASE_SET_PRIVATE_ACL -eq '1') {
    $acl = if ($item.PSIsContainer) {
        [System.Security.AccessControl.DirectorySecurity]::new()
    } else { [System.Security.AccessControl.FileSecurity]::new() }
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = if ($item.PSIsContainer) { 'ContainerInherit, ObjectInherit' } else { 'None' }
    foreach ($identity in @($sid.Value, 'S-1-5-18')) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]::new($identity),
            'FullControl', $inherit, 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $p -AclObject $acl
}
$acl = Get-Acl -LiteralPath $p
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'Owner' }
$allowed = @($sid.Value, 'S-1-5-18', 'S-1-5-32-544')
foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
    if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $allowed) {
        throw 'Public access'
    }
}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        input=str(path.resolve()),
        text=True,
        encoding="utf-8",
        env={**os.environ, "CONTEXTBASE_SET_PRIVATE_ACL": "1" if protect else "0"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise ValueError("Windows state must be owned by the current user with a private NTFS ACL")


def private_directory(path: Path) -> None:
    created = not path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = path.lstat()
    if not stat.S_ISDIR(mode.st_mode) or path.is_symlink():
        raise ValueError("Local state directories must be private (0700 or private NTFS ACL)")
    if sys.platform == "win32":
        windows_acl(path, protect=created)
    elif mode.st_mode & 0o077:
        raise ValueError("Local state directories must be private (0700)")


def private_file(path: Path) -> None:
    mode = path.lstat()
    if not stat.S_ISREG(mode.st_mode):
        raise ValueError("Persisted state must be a private regular file")
    if sys.platform == "win32":
        windows_acl(path)
    elif mode.st_mode & 0o077:
        raise ValueError("Persisted state must be a private regular file (0600)")


def protect_file(path: Path) -> None:
    if sys.platform == "win32":
        windows_acl(path, protect=True)
    else:
        path.chmod(0o600)
