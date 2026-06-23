@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: Use Python for all display (UTF-8 safe)
python -c "print(); print('=' * 46); print('  Security Supervisor - Dependency Check'); print('=' * 46); print()"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    python -c "print('[ERROR] Python not found. Please install Python 3.10+')"
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do python -c "print('Python: %%v')"
echo.

:: Check each dependency via Python
set MISSING=0
set MISSING_LIST=

call :check pydantic pydantic
call :check cv2 opencv-python
call :check numpy numpy
call :check streamlit streamlit
call :check requests requests
call :check paddleocr paddleocr
call :check openai openai
call :check pandas pandas
call :check onnxruntime onnxruntime

echo.
if !MISSING! GTR 0 (
    python -c "print('=' * 46); print('  Missing !MISSING! package(s):'); print('  !MISSING_LIST!'); print('=' * 46); print()"
    set /p INSTALL=Install now? [Y/n]:
    if /i "!INSTALL!"=="n" (
        python -c "print('Cancelled. Please install manually.')"
        pause
        exit /b 1
    )
    echo.
    pip install !MISSING_LIST!
    if errorlevel 1 (
        echo.
        python -c "print('[ERROR] Install failed. Run manually:'); print('  pip install !MISSING_LIST!')"
        pause
        exit /b 1
    )
    echo.
    python -c "print('Done.')"
) else (
    python -c "print('All dependencies ready.')"
)

echo.
python -c "print('=' * 46); print('  Model Check'); print('=' * 46); print()"
python -c "import sys; sys.exit(0 if __import__('os').path.isdir(__import__('os').path.expanduser(r'~\.paddlex\official_models\PP-OCRv6_medium_det_onnx')) else 1)" >nul 2>&1
if errorlevel 1 (
    python -c "print('  PaddleOCR models not cached. Downloading...')"
    python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='ch', engine='onnxruntime')" >nul 2>&1
    if errorlevel 1 (
        python -c "print('[ERROR] Model download failed. Check network and retry.')"
        pause
        exit /b 1
    )
    python -c "print('  Models downloaded and cached.')"
) else (
    python -c "print('  [OK] PaddleOCR models cached.')"
)

echo.
python -c "print('=' * 46); print('  Starting...'); print('=' * 46); print()"
python -m streamlit run frontend.py
pause
exit /b 0

:check
python -c "import %1" >nul 2>&1
if errorlevel 1 (
    python -c "print('  [X] %2')"
    set /a MISSING+=1
    set MISSING_LIST=!MISSING_LIST! %2
) else (
    python -c "print('  [OK] %2')"
)
goto :eof
