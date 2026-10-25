@echo off
where pyw >nul 2>nul && (
  start "" pyw "%~dp0claude_capture.py"
) || (
  start "" pythonw "%~dp0claude_capture.py"
)
