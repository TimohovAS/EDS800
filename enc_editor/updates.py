"""Check GitHub Releases and hand a verified Windows installer to Setup."""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import VERSION

REPOSITORY = "TimohovAS/EDS800"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RUNNING_MUTEX = r"Local\TimohovAS.ENCInverterEditor.Running"
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\{6C92B4C7-DE01-4572-9533-26377D978B21}_is1")
MAX_INSTALLER_SIZE = 1024 ** 3
MAX_METADATA_SIZE = 2 * 1024 ** 2
CHUNK_SIZE = 256 * 1024
logger = logging.getLogger(__name__)


class UpdateError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


def version_tuple(version: str) -> tuple[int, ...]:
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version):
        raise UpdateError("Invalid stable release version")
    return tuple(map(int, version.split(".")))


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    size: int
    sha256: str
    notes: str = ""

    @property
    def filename(self) -> str:
        return f"ENC-Inverter-Editor-{self.version}-Setup.exe"

    @property
    def url(self) -> str:
        return f"{RELEASES_URL}/download/{self.tag}/{self.filename}"

    def validate(self) -> None:
        version_tuple(self.version)
        if self.tag not in (self.version, f"v{self.version}"):
            raise UpdateError("Invalid release tag")
        if type(self.size) is not int or not 0 < self.size <= MAX_INSTALLER_SIZE:
            raise UpdateError("Invalid installer size")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise UpdateError("GitHub has not provided a valid SHA-256 digest for the installer")


class _HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise UpdateError("Refusing an unencrypted redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, accept="application/octet-stream"):
    request = Request(url, headers={"User-Agent": f"ENC-Inverter-Editor/{VERSION}", "Accept": accept})
    return build_opener(_HTTPSRedirects()).open(request, timeout=20)


def parse_release(data, current=VERSION) -> Release | None:
    if not isinstance(data, dict):
        raise UpdateError("Invalid release metadata")
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateError("Invalid release tag")
    version = tag.removeprefix("v")
    if version_tuple(version) <= version_tuple(current):
        return None

    assets = data.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Invalid release assets")
    notes = data.get("body")
    filename = f"ENC-Inverter-Editor-{version}-Setup.exe"
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != filename or asset.get("state") != "uploaded":
            continue
        digest = asset.get("digest")
        sha256 = digest[7:] if isinstance(digest, str) and digest.startswith("sha256:") else ""
        release = Release(version, tag, asset.get("size"), sha256, notes[:20000] if isinstance(notes, str) else "")
        release.validate()
        if asset.get("browser_download_url") != release.url:
            raise UpdateError("Installer URL does not match the official release")
        return release
    raise UpdateError("The new release has no Windows installer")


def check_update(current=VERSION) -> Release | None:
    try:
        with _open(API_URL, "application/vnd.github+json") as response:
            raw = response.read(MAX_METADATA_SIZE + 1)
    except HTTPError as error:
        if error.code == 404:
            error.close()
            return None
        raise
    if len(raw) > MAX_METADATA_SIZE:
        raise UpdateError("Release metadata is too large")
    return parse_release(json.loads(raw), current)


def cache_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "ENC Inverter Editor" / "Updates"


def verify_installer(path: Path, release: Release) -> Path:
    release.validate()
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size != release.size:
            raise UpdateError("Downloaded installer size does not match the release")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    if digest.hexdigest() != release.sha256:
        raise UpdateError("Downloaded installer SHA-256 does not match the release")
    return path


def download_update(release: Release, *, directory=None, cancel=None, progress=None) -> Path:
    release.validate()
    cancel = threading.Event() if cancel is None else cancel
    directory = cache_dir() if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / release.filename
    if cancel.is_set():
        raise DownloadCancelled()
    if target.is_file():
        try:
            verify_installer(target, release)
        except UpdateError:
            pass  # Replace the cache only after verifying the new download.
        else:
            if cancel.is_set():
                raise DownloadCancelled()
            return target

    descriptor, name = tempfile.mkstemp(prefix="download-", suffix=".part", dir=directory)
    partial = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream, _open(release.url) as response:
            received = 0
            digest = hashlib.sha256()
            while not cancel.is_set():
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                received += len(chunk)
                if received > release.size:
                    raise UpdateError("Download exceeds the expected installer size")
                stream.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(received * 100 // release.size)
        if cancel.is_set():
            raise DownloadCancelled()
        if received != release.size or digest.hexdigest() != release.sha256:
            raise UpdateError("Incomplete or damaged installer download")
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def is_packaged_windows() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def installed_scope() -> str | None:
    """Use the Inno Setup registration for this exact executable directory."""
    if not is_packaged_windows():
        return None
    import winreg

    directory = Path(sys.executable).resolve().parent
    for root, scope in ((winreg.HKEY_CURRENT_USER, "/CURRENTUSER"), (winreg.HKEY_LOCAL_MACHINE, "/ALLUSERS")):
        try:
            with winreg.OpenKey(root, UNINSTALL_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                location, _ = winreg.QueryValueEx(key, "InstallLocation")
            if location and Path(location).resolve() == directory:
                return scope
        except (OSError, TypeError, ValueError):
            continue
    return None


def hold_installation_mutex():
    if not is_packaged_windows():
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    # Keep the handle open until the OS terminates the process.
    if not kernel.CreateMutexW(None, False, RUNNING_MUTEX):
        logger.warning("Could not create the installer mutex: %s", ctypes.WinError(ctypes.get_last_error()))


def launch_installer(path: Path, release: Release, *, language: str) -> None:
    """Start a helper outside the installation directory before closing the UI."""
    scope = installed_scope()
    if scope is None:
        raise UpdateError("Installation requires a registered Windows installation")
    release.validate()
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    installer_language = "russian" if language == "ru" else "english"
    arguments = [scope, "/SP-", "/NORESTART", "/NOCLOSEAPPLICATIONS",
                 f"/DIR={Path(sys.executable).resolve().parent}", f"/LANG={installer_language}"]
    descriptor, name = tempfile.mkstemp(prefix="install-", suffix=".json", dir=directory)
    request = Path(name)
    helper = request.with_suffix(".ps1")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"parent_pid": os.getpid(), "installer": str(path.resolve()),
                       "size": release.size, "sha256": release.sha256, "arguments": arguments}, stream)
        shutil.copyfile(Path(__file__).with_name("update_helper.ps1"), helper)
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(powershell), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                   "-ExecutionPolicy", "Bypass", "-File", str(helper), "-RequestPath", str(request)]
        _start_helper(command, directory)
    except Exception:
        helper.unlink(missing_ok=True)
        request.unlink(missing_ok=True)
        raise


def _start_helper(command, directory) -> None:
    # Launch system PowerShell without PyInstaller's bundled DLL search path.
    bundled = Path(sys._MEIPASS).resolve()
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        entry for entry in environment.get("PATH", "").split(os.pathsep)
        if entry and not Path(os.path.abspath(entry.strip('"'))).is_relative_to(bundled)
    )
    set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
    set_dll_directory(None)
    try:
        subprocess.Popen(command, cwd=directory, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        set_dll_directory(str(bundled))
