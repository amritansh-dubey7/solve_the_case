@echo off
setlocal
set ROOT_DIR=%~dp0
set BACKEND_DIR=%ROOT_DIR%backend
set FRONTEND_DIR=%ROOT_DIR%frontend

echo ==^> Solve the Case — starting backend + frontend

REM ---------- Backend ----------
cd /d "%BACKEND_DIR%"

if not exist venv (
    echo ==^> Creating backend virtualenv...
    python -m venv venv
)
call venv\Scripts\activate.bat

echo ==^> Installing backend dependencies (first run downloads PyTorch for
echo     sentence-transformers — can take 3-10+ min; this is NOT stuck.
pip install -r requirements.txt

if not exist .env (
    (
        echo LLM_PROVIDER=groq
        echo ANTHROPIC_API_KEY=
        echo GROQ_API_KEY=
    ) > .env
    echo ==^> Created backend\.env — set LLM_PROVIDER and the matching key, then re-run.
)

echo ==^> Starting backend on http://localhost:8000 ...
start "Solve the Case - Backend" cmd /k "cd /d %BACKEND_DIR% && call venv\Scripts\activate.bat && uvicorn main:app --reload --port 8000"

timeout /t 3 /nobreak > nul
curl -s -X POST http://localhost:8000/ingest > nul

REM ---------- Frontend ----------
cd /d "%FRONTEND_DIR%"

if not exist .env (
    copy .env.example .env > nul
)

if not exist node_modules (
    echo ==^> Installing frontend dependencies...
    call npm install
)

echo ==^> Starting frontend on http://localhost:5173 ...
start "Solve the Case - Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo.
echo ==================================================
echo  Backend:  http://localhost:8000  (docs at /docs)
echo  Frontend: http://localhost:5173
echo  Close the two new windows to stop each one.
echo ==================================================
