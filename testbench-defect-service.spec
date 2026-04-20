# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for testbench-defect-service
#
# Build with:
#   pyinstaller testbench-defect-service.spec --clean --noconfirm
#
# Or use the helper script which handles environment setup first:
#   python build_exe.py
#
# Output: dist/testbench-defect-service/  (onedir)

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

# Collect everything from packages that use dynamic internal imports.
# collect_all() = collect_data_files + collect_binaries + collect_submodules,
sanic_datas, sanic_binaries, sanic_hiddenimports = collect_all("sanic")
sanic_ext_datas, sanic_ext_binaries, sanic_ext_hiddenimports = collect_all("sanic_ext")
questionary_datas, questionary_binaries, questionary_hiddenimports = collect_all("questionary")

# Package data files (openapi.yaml, static/swagger-ui, readers/jsonl/schemas, …)
pkg_datas = collect_data_files("testbench_defect_service")
# tracerite: Sanic uses it for HTML error-page rendering
tracerite_datas = collect_data_files("tracerite")

datas = (
    pkg_datas
    + tracerite_datas
    + sanic_datas
    + sanic_ext_datas
    + questionary_datas
    # Bundle dist-info for packages whose pip name differs from the importable module
    # name (e.g. beautifulsoup4 → bs4). Without this, importlib.metadata.distribution()
    # fails in the frozen exe and dependencies.py wrongly reports them as missing.
    + copy_metadata("beautifulsoup4")
)
binaries = sanic_binaries + sanic_ext_binaries + questionary_binaries
hiddenimports = (
    sanic_hiddenimports
    + sanic_ext_hiddenimports
    + questionary_hiddenimports
    + collect_submodules("testbench_defect_service")
    + [
        # clients wrapped in try/except ImportError
        "testbench_defect_service.clients.jira.client",
        # optional third-party deps guarded by try/except in utils/config.py and app.py
        "javaproperties",
        "jira",
        "jira.resilientsession",
        # sanic worker modules loaded by module-string in the process manager
        "sanic.worker.loader",
        "sanic.worker.multiplexer",
        "sanic.worker.reloader",
        "sanic.worker.inspector",
        # multiprocessing spawn support (needed for freeze_support on all platforms)
        "multiprocessing.resource_tracker",
        "multiprocessing.spawn",
    ]
)

a = Analysis(
    ["src/testbench_defect_service/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Dev / test tooling
        "pytest",
        "mypy",
        "ruff",
        "robotframework",
        "IPython",
        "ipykernel",
        "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: binaries live in COLLECT
    name="testbench-defect-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can cause false-positive AV alerts; disable by default
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="lib",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="testbench-defect-service",
    contents_directory="lib",
)
