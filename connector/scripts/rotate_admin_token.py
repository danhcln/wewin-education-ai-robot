"""Generate/rotate a private admin token file without printing the credential.

Initial setup: python -B scripts/rotate_admin_token.py
Rotation:      python -B scripts/rotate_admin_token.py --force
Configure ADMIN_SYNC_TOKEN_FILE to this file and leave ADMIN_SYNC_TOKEN empty.
Restart the backend after rotation. XiaoZhi credentials are never touched.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def restrict_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        # Replace the ACL rather than retaining pre-existing explicit grants.
        command = """
$ErrorActionPreference = 'Stop'
$acl = [System.Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
$sids = @([System.Security.Principal.WindowsIdentity]::GetCurrent().User,
    [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
    [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach ($sid in $sids) {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $sid, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
[System.IO.Directory]::SetAccessControl($env:WEWIN_TOKEN_DIRECTORY, $acl)
"""
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            check=True, capture_output=True, env={**os.environ, "WEWIN_TOKEN_DIRECTORY": str(path)},
        )
    else:
        path.chmod(0o700)


def rotate_token(output: Path, force: bool = False):
    output = output.absolute()
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError("Secret files must not use symbolic links.")
    output = output.resolve()
    if output.parent.name != ".secrets":
        raise ValueError("Use a dedicated .secrets directory for private token files.")
    if any(output.is_relative_to(PROJECT_ROOT / "frontend" / part) for part in ("dist", "public", "src")):
        raise ValueError("Secret files must not be stored in frontend directories.")
    if output.exists() and not force:
        raise FileExistsError("A token file already exists; use --force for an intentional rotation.")
    # Only dedicated directories should be used: permissions on the parent are restricted.
    restrict_directory(output.parent)
    fd, temporary = tempfile.mkstemp(prefix=".admin-token-", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        if force:
            os.replace(temporary, output)
        else:
            # Link/create without replacing a credential another process just wrote.
            os.link(temporary, output)
            os.unlink(temporary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / ".secrets" / "admin_sync_token")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        rotate_token(args.output, args.force)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Do not echo process arguments, environment, or file contents on failure.
        parser.exit(1, "Token setup failed. Check the private output directory and --force option.\n")
    print("Private admin token file created. Restart the backend to load it. Secret not displayed.")


if __name__ == "__main__":
    main()
