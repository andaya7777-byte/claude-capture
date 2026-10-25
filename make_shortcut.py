# -*- coding: utf-8 -*-
"""바탕화면에 '클로드 캡처' 아이콘(바로가기)을 만들어 줍니다."""
import os
import sys
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

root = tk.Tk()
root.withdraw()

try:
    import win32com.client
except ImportError:
    messagebox.showerror("클로드 캡처", "부품이 없어요. install.bat 을 먼저 실행해 주세요.")
    sys.exit(1)

here = Path(__file__).resolve().parent
script = here / "claude_capture.py"
icon = here / "icon.ico"

pyw = Path(sys.executable).with_name("pythonw.exe")
if not pyw.exists():
    pyw = Path(sys.executable)

shell = win32com.client.Dispatch("WScript.Shell")
desktop = Path(shell.SpecialFolders("Desktop"))
lnk_path = desktop / "클로드 캡처.lnk"

lnk = shell.CreateShortCut(str(lnk_path))
lnk.TargetPath = str(pyw)
lnk.Arguments = f'"{script}"'
lnk.WorkingDirectory = str(here)
if icon.exists():
    lnk.IconLocation = str(icon)
lnk.Description = "클로드 캡처 도우미 (F7 영역 지정, F8 캡처)"
lnk.save()

messagebox.showinfo(
    "클로드 캡처",
    "바탕화면에 '클로드 캡처' 아이콘을 만들었어요!\n\n"
    "이제 이 아이콘을 더블클릭하면 켜져요.\n"
    "※ 이 폴더(ClaudeCapture)는 지우지 말고 그대로 두세요.",
)
