# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

hidden_imports = [
    "cantools",
    "matplotlib",
    "matplotlib.colors",
    "matplotlib.lines",
    "matplotlib.patches",
    "matplotlib.pyplot",
    "matplotlib.backends.backend_agg",
]

analysis = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (
            str(SRC / "canfd_offset_optimizer" / "gui" / "default_project.yaml"),
            "canfd_offset_optimizer/gui",
        ),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "packaging" / "README_运行说明.txt"), "."),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=[
        "mypy",
        "ortools",
        "pytest",
        "pytest_cov",
        "pytestqt",
        "ruff",
        "canfd_offset_optimizer.gui.fixture_backend",
        "canfd_offset_optimizer.gui.mock_backend",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="CANFDOffsetOptimizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CANFDOffsetOptimizer",
)
