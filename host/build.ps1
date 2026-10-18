$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3.12 -m venv .venv
if ($LASTEXITCODE) { throw 'Python 3.12 is required' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name FarPlayHost --collect-all aiortc --collect-all av --collect-all soundcard --collect-all mss main.py
if ($LASTEXITCODE) { throw 'Windows build failed' }
Write-Host 'Built dist\FarPlayHost.exe'
