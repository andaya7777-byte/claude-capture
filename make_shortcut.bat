@echo off
where py >nul 2>nul && (
  py "%~dp0make_shortcut.py"
) || (
  python "%~dp0make_shortcut.py"
)
