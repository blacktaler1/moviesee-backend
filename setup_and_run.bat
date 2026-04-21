@echo off
echo ========================================
echo    MovieSee Backend - Ishga tushirish
echo ========================================

REM Virtual muhit bor-yo'qligini tekshirish
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Virtual muhit yaratilmoqda...
    python -m venv venv
    echo     OK
) else (
    echo [1/3] Virtual muhit mavjud
)

REM Virtual muhitni yoqish
call venv\Scripts\activate.bat

REM Paketlarni o'rnatish
echo [2/3] Paketlar o'rnatilmoqda...
pip install -r requirements.txt -q
echo     OK

REM Serverni ishga tushirish
echo [3/3] Server ishga tushirilmoqda...
echo.
echo ----------------------------------------
echo  API docs:  http://localhost:8000/docs
echo  Health:    http://localhost:8000/health
echo  WebSocket: ws://localhost:8000/ws/XONA_KODI?token=TOKEN
echo ----------------------------------------
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
