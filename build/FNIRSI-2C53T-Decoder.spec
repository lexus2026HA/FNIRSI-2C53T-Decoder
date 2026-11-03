# PyInstaller spec. Build:  build\build.bat   (or: .venv\Scripts\pyinstaller build\FNIRSI-2C53T-Decoder.spec)
from pathlib import Path

ROOT = Path(SPECPATH).parent

EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtNetwork",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtSensors",
    "PySide6.QtTextToSpeech", "PySide6.QtGraphs", "PySide6.QtSpatialAudio", "PySide6.QtHttpServer",
    "PySide6.QtWebSockets", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PyQt5", "PyQt6", "tkinter", "IPython", "pytest", "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_tkagg", "pyqtgraph.opengl", "pyqtgraph.examples", "pandas",
]

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT / "src")],
    datas=[],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "scipy.signal", "openpyxl", "matplotlib.backends.backend_agg", "matplotlib.backends.backend_svg", "matplotlib.backends.backend_pdf"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FNIRSI-2C53T-Decoder",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FNIRSI-2C53T-Decoder")
