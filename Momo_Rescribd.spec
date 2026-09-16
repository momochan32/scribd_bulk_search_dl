# -*- mode: python ; coding: utf-8 -*-
"""
Unified PyInstaller specification for Momo Rescribd.
Cross-platform: builds .app on macOS and .exe on Windows.
"""
import sys
import os
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []

# Collect all selenium, pypdf, customtkinter, and PIL modules and assets
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('pypdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

icon_file = 'assets/momo_rescribd.ico' if sys.platform == 'win32' else 'assets/momo_rescribd.icns'

a = Analysis(
    ['momo_rescribd_gui.py'],
    pathex=[],
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='Momo Rescribd',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Momo Rescribd.app',
        icon='assets/momo_rescribd.icns',
        bundle_identifier='com.momochan32.momorescribd',
    )
