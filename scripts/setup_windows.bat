@echo off
echo === CAI DAT MOI TRUONG WINDOWS (Python 3.9 Recommended) ===

:: Chuyen ve thu muc goc cua du an (chua main.py va requirements.txt)
cd /d "%~dp0"
cd ..

python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python chua duoc cai dat hoac chua them vao PATH.
    echo Vui long cai dat Python 3.9.11 tu python.org va tich vao "Add Python to PATH".
    pause
    exit /b
)

echo [*] Nang cap pip...
python -m pip install --upgrade pip

echo [*] Cai dat thu vien tu file requirements.txt...
:: Quan trong: urllib3<2.0 de tranh loi 'cert_reqs' voi tidevice
python -m pip install "urllib3<2.0" --force-reinstall

:: Fix loi DLL load failed: Go bo ban cu truoc khi cai dat ban trong requirements.txt
python -m pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-sip
python -m pip install -r requirements.txt

echo.
echo === CAI DAT HOAN TAT ===
echo Ban co the chay he thong bang lenh: python main.py
python main.py
pause