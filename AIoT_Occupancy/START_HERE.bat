@echo off
echo =====================================================
echo  AIoT Occupancy Detection - Serial (COM4) Mode
echo =====================================================
echo.

echo [STEP 1] Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: pip failed & pause & exit /b 1 )

echo.
echo [STEP 2] Training AI model...
cd 2_train_model
python train_occupancy_model.py
cd ..
if errorlevel 1 ( echo ERROR: Training failed & pause & exit /b 1 )

echo.
echo =====================================================
echo  BEFORE CONTINUING:
echo  - Plug in STM32 board via USB
echo  - Flash uart_sender.c firmware (STM32CubeIDE)
echo  - Board should be printing DIST:xxx on COM4
echo  - Check Device Manager for correct COM port
echo  - Edit DEFAULT_COM_PORT in 3_api_server/server.py
echo    if your board is NOT on COM4
echo =====================================================
echo.
pause

echo [STEP 3] Starting API server on COM4 port 8000...
echo  Open a NEW terminal and run:
echo    cd 4_frontend
echo    npm install
echo    npm run dev
echo  Then open: http://localhost:5173
echo.
cd 3_api_server
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
