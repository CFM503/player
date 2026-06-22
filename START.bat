@echo off
echo Checking dependencies...
python -c "import pydantic" 2>nul || pip install pydantic
python -c "import cv2" 2>nul || pip install opencv-python
python -c "import numpy" 2>nul || pip install numpy
python -c "import streamlit" 2>nul || pip install streamlit
python -c "import requests" 2>nul || pip install requests
python -c "import paddleocr" 2>nul || pip install paddleocr
python -c "import openai" 2>nul || pip install openai
echo All dependencies ready.
python -m streamlit run frontend.py
pause
