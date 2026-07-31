# PyInstaller build of the editor.  Run it through packaging/build.ps1 rather
# than by hand, so the executable and the installer carry the same version.
#
# One-folder build: the profiles ship as plain JSON inside the install
# directory, so a new inverter model can still be dropped in afterwards.

import sys
from pathlib import Path

SPEC_DIRECTORY = Path(SPECPATH).resolve()
ROOT = SPEC_DIRECTORY.parent
sys.path.insert(0, str(ROOT))

from enc_editor import VERSION  # noqa: E402  (needs ROOT on the path)

NAME = "ENC Inverter Editor"
VERSION_RESOURCE = SPEC_DIRECTORY / "version_info.txt"


def write_version_resource() -> Path:
    """Stamp the Windows file-properties resource from ``enc_editor.VERSION``."""
    numbers = tuple((tuple(int(part) for part in VERSION.split(".")) + (0, 0, 0, 0))[:4])
    VERSION_RESOURCE.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'ENC'),
        StringStruct('FileDescription', '{NAME}'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', 'enc_editor'),
        StringStruct('OriginalFilename', '{NAME}.exe'),
        StringStruct('ProductName', '{NAME}'),
        StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return VERSION_RESOURCE


analysis = Analysis(
    [str(ROOT / "inverter_parameter_editor.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "profiles"), "profiles"),
        (str(ROOT / "README.md"), "."),
    ],
    hiddenimports=["serial.tools.list_ports"],
    hookspath=[],
    runtime_hooks=[],
    # pdfplumber and Pillow only serve the tools/ scripts that build the
    # parameter tables; they have no place in a drive-side install.
    excludes=["pdfplumber", "pypdfium2", "PIL", "pytest", "numpy"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=str(SPEC_DIRECTORY / "enc_editor.ico"),
    version=str(write_version_resource()),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=NAME,
)
