@echo off
echo.
echo  ==== Claude Capture - installing parts ====
echo.
set PY=python
where py >nul 2>nul && set PY=py
%PY% --version
if errorlevel 1 (
  echo  [!] Python not found. See HOW_TO_USE.txt step 1.
  pause
  exit /b
)
%PY% -m pip install mss psutil pystray pillow pywin32
echo.
echo  ==== DONE! Now double-click run.bat ====
pause
