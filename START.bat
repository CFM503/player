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

:: Verify Python version >= 3.13
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
    python -c "import sys; v=sys.version_info; print(f'[ERROR] Python 3.13+ required, got {v.major}.{v.minor}.{v.micro}. Please upgrade.')"
    pause
    exit /b 1
)

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
call :check paddle paddlepaddle
call :check scipy scipy
call :check skimage scikit-image

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
    pip install !MISSING_LIST! -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
    if errorlevel 1 (
        echo.
        python -c "print('[ERROR] Install failed. Run manually:'); print('  pip install !MISSING_LIST! -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn')"
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

python -c "import sys; sys.exit(0 if __import__('os').path.isdir(__import__('os').path.expanduser(r'~\.paddlex\official_models\PP-OCRv6_medium_det')) else 1)" >nul 2>&1
if errorlevel 1 (
    python -c "print('  PaddleOCR models not cached. Downloading...')"
    python -c "import os; os.environ['FLAGS_download_tool']='wget'; os.environ['PADDLE_PDX_SOURCE_HOME']='https://paddle-model-ecology.bj.bcebos.com'; os.environ['PADDLEX_PDX_MODEL_SOURCE']='https://paddle-model-ecology.bj.bcebos.com'; import paddle.inference as pi; orig=pi.Config.enable_new_ir; pi.Config.enable_new_ir=lambda s,v=True:orig(s,False); orig2=pi.Config.set_optimization_level; pi.Config.set_optimization_level=lambda s,l:orig2(s,0); from paddleocr import PaddleOCR; PaddleOCR(lang='ch')" >nul 2>&1
    if errorlevel 1 (
        python -c "print('[ERROR] Model download failed. Check network and retry.')"
        pause
        exit /b 1
    )
    python -c "print('  PaddleOCR models downloaded.')"
) else (
    python -c "print('  [OK] PaddleOCR models cached.')"
)


echo.
python -c "print('=' * 46); print('  Starting...'); print('=' * 46); print()"
python run.py
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
