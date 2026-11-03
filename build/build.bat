@echo off
rem Builds dist\FNIRSI-2C53T-Decoder\FNIRSI-2C53T-Decoder.exe and a zip of it.
setlocal
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt pyinstaller
)
.venv\Scripts\python -m pytest -q tests || goto :fail
.venv\Scripts\pyinstaller --noconfirm --clean --distpath dist --workpath build\work build\FNIRSI-2C53T-Decoder.spec || goto :fail
rem build\work holds an intermediate exe without its DLLs - remove it so it is never started by mistake
rmdir /s /q build\work
xcopy /y /i /e samples dist\FNIRSI-2C53T-Decoder\samples\ >nul
copy /y README.md dist\FNIRSI-2C53T-Decoder\ >nul
xcopy /y /i /e docs dist\FNIRSI-2C53T-Decoder\docs\ >nul
dist\FNIRSI-2C53T-Decoder\FNIRSI-2C53T-Decoder.exe --selftest dist\selftest.txt
type dist\selftest.txt
powershell -NoProfile -Command "Compress-Archive -Force dist\FNIRSI-2C53T-Decoder dist\FNIRSI-2C53T-Decoder-win64.zip"
echo Done: dist\FNIRSI-2C53T-Decoder
exit /b 0
:fail
echo BUILD FAILED
exit /b 1
