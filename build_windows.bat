@echo off
chcp 65001 >nul
echo ========================================================
echo  Momo Rescribd - Windows Executable (.exe) Builder
echo ========================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python tidak ditemukan di sistem Anda!
    echo Silakan install Python 3.10+ dari https://www.python.org/
    echo Pastikan centang "Add python.exe to PATH" saat instalasi.
    echo.
    pause
    exit /b 1
)

echo [1/4] Menyiapkan virtual environment...
if not exist ".venv" (
    python -m venv .venv
)

echo [2/4] Mengaktifkan virtual environment & install dependensi...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pillow

echo [3/4] Mengompilasi Momo Rescribd menjadi file EXE mandiri...
REM Konfigurasi build ada di Momo_Rescribd.spec agar build lokal dan build CI
REM (.github/workflows/build-windows.yml) selalu menghasilkan hal yang sama.
pyinstaller --noconfirm --clean Momo_Rescribd.spec

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo  ✅ Berhasil! File EXE telah selesai dibuat.
    echo  Lokasi: dist\Momo Rescribd\Momo Rescribd.exe
    echo ========================================================
    echo.
    if exist "dist\Momo Rescribd" (
        explorer.exe "dist\Momo Rescribd"
    )
) else (
    echo.
    echo [ERROR] Terjadi kesalahan saat proses build EXE.
)

pause
