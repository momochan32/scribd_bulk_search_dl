# -*- mode: python ; coding: utf-8 -*-
"""
Unified PyInstaller specification for Momo Rescribd.
Cross-platform: builds .app on macOS and .exe on Windows.
"""
import sys
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# The Solcoat research feature lives in research/solcoat_research; its keyword
# lexicon is a data file loaded next to lexicon.py, so ship it in the same folder.
datas = [('assets', 'assets'), ('research/solcoat_research/lexicon.yaml', 'solcoat_research')]
binaries = []
hiddenimports = [
    '.'.join(module.relative_to('research').with_suffix('').parts).removesuffix('.__init__')
    for module in Path('research/solcoat_research').rglob('*.py')
] + [
    # Analyst-tool windows are imported by name from research_panel, which static analysis cannot see.
    'calc_dialog', 'verify_dialog', 'pltu_dialog', 'analysis_dialogs', 'analysis_panel',
]

# Collect all selenium, pypdf, customtkinter, and PIL modules and assets
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('pypdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

for package in ('pymupdf', 'reportlab', 'openpyxl', 'certifi'):
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

icon_file = 'assets/momo_rescribd.ico' if sys.platform == 'win32' else 'assets/momo_rescribd.icns'

# UPX mangles Mach-O headers and invalidates the ad-hoc code signature that
# Apple Silicon requires, producing bundles that crash or misbehave at runtime.
# Keep it off on macOS.
use_upx = sys.platform != 'darwin'

a = Analysis(
    ['momo_rescribd_gui.py'],
    pathex=['research'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Momo Rescribd',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=use_upx,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=use_upx,
    upx_exclude=[],
    name='Momo Rescribd',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Momo Rescribd.app',
        icon='assets/momo_rescribd.icns',
        bundle_identifier='com.momochan32.momorescribd',
        info_plist={
            # Without this the bundle runs in 1x scaled mode on Retina displays,
            # which renders the Tk window blurry and can offset hit testing.
            'NSHighResolutionCapable': True,
            'CFBundleName': 'Momo Rescribd',
            'CFBundleDisplayName': 'Momo Rescribd',
            'CFBundleShortVersionString': '1.2.0',
            'CFBundleVersion': '1.2.0',
            'LSMinimumSystemVersion': '11.0',
            'NSHumanReadableCopyright': 'Copyright (c) momochan32',
        },
    )
