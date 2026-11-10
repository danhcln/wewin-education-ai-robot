"""Single-host OS lock with crash recovery. Status never edits lock files.

The guard inode must NEVER be unlinked/replaced. Windows byte-range locks and
POSIX flock release automatically on process death. JSON is diagnostic metadata.
"""
import atexit
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import uuid

from src.config import settings


class SyncAlreadyRunningError(RuntimeError):
    pass


def is_pid_active(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Invalid PID only; denied/unknown => alive.
        try:
            code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True


def _lock(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_UN)


class SyncLock:
    def __init__(self, lock_path=None, timeout_minutes=None):
        self.lock_path = Path(lock_path or settings.DATABASE_PATH.parent / "sync.lock").resolve()
        self.guard_path = self.lock_path.with_name(self.lock_path.name + ".guard")
        self._handle = None
        self._run_id = None
        # Accepted for older callers, but time never invalidates a live lock.
        self.timeout_seconds = (timeout_minutes if timeout_minutes is not None else settings.SYNC_LOCK_TIMEOUT_MINUTES) * 60
        self._acquired = False

    def get_lock_info(self):
        try:
            value = json.loads(self.lock_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and isinstance(value.get("pid"), int) and value["pid"] > 0 else None
        except (OSError, ValueError):
            return None

    def is_locked(self):
        """Probe an existing guard only. Never create, rewrite or unlink anything."""
        if self._handle is not None:
            return True
        try:
            handle = self.guard_path.open("r+b")
        except FileNotFoundError:
            handle = None
        except OSError:
            return True
        if handle:
            try:
                try:
                    _lock(handle)
                except OSError:
                    return True
                _unlock(handle)
            finally:
                handle.close()
        if not self.lock_path.exists():
            return False
        info = self.get_lock_info()
        # Corrupt/foreign metadata is conservatively held until explicit recovery.
        return info is None or is_pid_active(info.get("pid"))

    def _acquire_guard(self):
        self.guard_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.guard_path.open("a+b")
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            _lock(handle)
            return handle
        except OSError:
            handle.close()
            raise SyncAlreadyRunningError("A sync job owns the OS lock; operation refused.") from None

    def acquire(self, trigger_type="manual"):
        if self._handle is not None:
            raise SyncAlreadyRunningError("This lock instance already owns a job.")
        handle = self._acquire_guard()
        try:
            info = self.get_lock_info()
            if info is None and self.lock_path.exists():
                raise SyncAlreadyRunningError("Corrupt lock metadata requires explicit stale recovery.")
            if info and is_pid_active(info.get("pid")):
                raise SyncAlreadyRunningError("Live legacy/metadata owner found; operation refused.")
            run_id = uuid.uuid4().hex
            data = {"version": 2, "pid": os.getpid(), "run_id": run_id,
                    "started_at": datetime.now(timezone.utc).isoformat(), "trigger_type": trigger_type}
            fd, temporary = tempfile.mkstemp(prefix=".sync-owner-", dir=self.lock_path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(data, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.lock_path)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            self._handle, self._run_id, self._acquired = handle, run_id, True
            atexit.register(self._cleanup_on_exit)
        except BaseException:
            _unlock(handle)
            handle.close()
            raise

    def recover_stale(self, allow_corrupt=False):
        """Explicit cleanup serialized by the guard; never remove a live owner's metadata."""
        if self._handle is not None:
            raise SyncAlreadyRunningError("Cannot unlock a running job.")
        handle = self._acquire_guard()
        try:
            info = self.get_lock_info()
            if info is None and self.lock_path.exists() and not allow_corrupt:
                raise SyncAlreadyRunningError("Unknown/corrupt metadata cannot be proved stale; recovery refused.")
            if info and is_pid_active(info.get("pid")):
                raise SyncAlreadyRunningError("Cannot unlock a live process.")
            self.lock_path.unlink(missing_ok=True)
            return True
        finally:
            _unlock(handle)
            handle.close()

    def release(self, force=False):
        if self._handle is None:
            return self.recover_stale() if force else False
        handle = self._handle
        try:
            info = self.get_lock_info()
            if info and info.get("run_id") == self._run_id:
                self.lock_path.unlink(missing_ok=True)
        finally:
            self._handle, self._run_id, self._acquired = None, None, False
            _unlock(handle)
            handle.close()
            atexit.unregister(self._cleanup_on_exit)
        return True

    def _cleanup_on_exit(self):
        if self._handle is not None: self.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
