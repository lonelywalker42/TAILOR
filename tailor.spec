# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for TAILOR

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['tailor/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('tailor/ui/*.py', 'tailor/ui'),
    ],
    hiddenimports=[
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'pyqtgraph',
        'OpenGL',
        'sqlalchemy.dialects.sqlite',
        'scipy.signal',
        'scipy.optimize',
        'scipy.interpolate',
        'numpy',
        'pandas',
        'jinja2',
        'pyulog',
        'control',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',  # Use pyqtgraph instead
        'tkinter',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TAILOR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here if available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TAILOR',
)
