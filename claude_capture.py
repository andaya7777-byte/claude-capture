# -*- coding: utf-8 -*-
"""
클로드 캡처 도우미 (윈도우용)

  F7 : 캡처할 영역 지정 (처음 한 번만, 바꾸고 싶을 때 다시)
  F9 : 붙여넣을 대화창 지정 (누른 뒤 대화창 글 쓰는 칸을 마우스로 한 번 클릭)
  F8 : 지정한 영역 캡처 -> 폴더에 저장 -> F9로 지정한 칸에 붙여넣기
       (F9로 지정 안 했으면 최근 쓰던 대화창(클로드, 챗GPT, 제미나이 등)에 붙여넣기)
  (보내기 엔터는 직접 누르세요)

화면 오른쪽 아래(작업 표시줄) 주황색 아이콘을 오른쪽 클릭하면 메뉴가 나와요.
"""
import ctypes
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# 화면 배율(125%, 150% 등)에서도 좌표가 정확하도록 설정
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import messagebox

from ctypes import wintypes

try:
    import mss
    import psutil
    import pystray
    import win32clipboard
    import win32con
    import win32gui
    import win32process
    from PIL import Image, ImageDraw
except ImportError as e:
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(
        "클로드 캡처",
        "필요한 부품이 아직 설치되지 않았어요.\n"
        "먼저 install.bat 을 더블클릭해서 설치해 주세요.\n\n"
        f"(자세한 내용: {e})",
    )
    sys.exit(1)

# ---------------------------------------------------------------- 설정
# 실행파일(exe)로 묶였을 때: 설정은 exe 옆에, 그림 파일은 exe 속 임시 폴더에서 찾음
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RES_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent
    RES_DIR = APP_DIR
CONFIG_FILE = APP_DIR / "config.json"
SAVE_DIR = Path.home() / "Pictures" / "클로드캡처"

# 단축키는 윈도우에 정식 등록(RegisterHotKey)해서 받음.
# 예전 keyboard 부품(키보드 엿듣기)은 Ctrl 뗀 걸 놓치거나 윈도우가 몰래 끊어서 F8이 먹통이 됐음.
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x11, 0x10, 0x12, 0x5B, 0x5C
VK_V = 0x56
VK_LBUTTON, VK_ESCAPE = 0x01, 0x1B
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
GA_ROOT = 2
HOTKEYS = {
    1: (0x76, "F7", "region"),   # F7
    2: (0x77, "F8", "capture"),  # F8
    3: (0x78, "F9", "pick"),     # F9
}

# 어떤 프로그램 창을 "대화창"으로 볼지 (프로그램 이름 -> 표시 이름)
TARGETS = {
    "claude.exe": "데스크톱 클로드",
    "code.exe": "VS Code 클로드",
    "chatgpt.exe": "ChatGPT 앱",
    "perplexity.exe": "퍼플렉시티 앱",
    "cursor.exe": "커서",
}

# 인터넷 창은 맨 위 제목에 이 글자가 있을 때만 대화창으로 봄 (제목 글자 -> 표시 이름)
BROWSERS = {"chrome.exe", "msedge.exe", "whale.exe", "firefox.exe", "brave.exe", "opera.exe"}
TITLE_KEYWORDS = {
    "chatgpt": "챗GPT",
    "gemini": "제미나이",
    "claude": "클로드",
    "copilot": "코파일럿",
    "perplexity": "퍼플렉시티",
    "grok": "그록",
    "deepseek": "딥시크",
    "genspark": "젠스파크",
    "wrtn": "뤼튼",
    "뤼튼": "뤼튼",
    "clova x": "클로바X",
    "notebooklm": "노트북LM",
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- 클립보드
def copy_image_to_clipboard(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]  # BMP 파일 머리말 14바이트를 빼야 클립보드 형식이 됨
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_DIB, data)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.1)
    return False


# ---------------------------------------------------------------- 창 다루기
def bring_to_front(hwnd):
    """클로드 창을 맨 앞으로 가져오기"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        my_thread = kernel32.GetCurrentThreadId()
        attached = False
        if fg_thread and fg_thread != my_thread:
            attached = bool(user32.AttachThreadInput(fg_thread, my_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(fg_thread, my_thread, False)
    except Exception:
        pass
    time.sleep(0.3)
    return user32.GetForegroundWindow() == hwnd


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def wait_keys_released(timeout=2.0):
    """단축키(Ctrl, Shift, Alt, 윈도우 키)에서 손을 뗄 때까지 잠깐 기다림"""
    end = time.time() + timeout
    while time.time() < end:
        if not any(key_down(vk) for vk in (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)):
            return
        time.sleep(0.03)


def click_at(x, y):
    """그 자리를 마우스로 한 번 클릭하고 마우스 위치는 원래대로"""
    old = win32gui.GetCursorPos()
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.15)
    user32.SetCursorPos(*old)


def send_ctrl_v():
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ---------------------------------------------------------------- 본체
class App:
    def __init__(self):
        self.cfg = load_config()
        self.target = None  # (창 번호, 표시 이름)  최근 쓴 대화창 (자동)
        self.pinned = None  # (창 번호, 가로 비율, 아래에서 높이)  F9로 지정한 칸
        self.use_pinned = False  # 마지막으로 클릭한 대화창이 F9로 지정한 창이면 True
        self.picking = False
        self.running = True
        self.jobs = queue.Queue()
        self.selecting = False

        self.root = tk.Tk()
        self.root.withdraw()

        threading.Thread(target=self.track_claude_window, daemon=True).start()

        self.hotkey_thread_id = None
        threading.Thread(target=self.hotkey_loop, daemon=True).start()

        self.icon = pystray.Icon(
            "claude_capture",
            self.make_icon(),
            "클로드 캡처 (F8)",
            menu=pystray.Menu(
                pystray.MenuItem("캡처해서 대화창으로 보내기  (F8)",
                                 lambda: self.jobs.put("capture"), default=True),
                pystray.MenuItem("캡처 영역 다시 지정  (F7)",
                                 lambda: self.jobs.put("region")),
                pystray.MenuItem("붙여넣을 대화창 지정  (F9)",
                                 lambda: self.jobs.put("pick")),
                pystray.MenuItem("저장 폴더 열기", lambda: self.jobs.put("folder")),
                pystray.MenuItem("끝내기", lambda: self.jobs.put("quit")),
            ),
        )
        self.icon.run_detached()

        self.root.after(100, self.poll_jobs)

        if not self.cfg.get("region"):
            self.toast("클로드 캡처가 켜졌어요!\nF7 으로 캡처할 영역을 먼저 정해 주세요.", 4000)
        else:
            self.toast("클로드 캡처가 켜졌어요!\nF9 로 대화창을 지정하고 F8 로 캡처하세요.", 3500)

    # ---- 트레이 아이콘 그림 (주황 동그라미)
    @staticmethod
    def make_icon():
        try:
            return Image.open(RES_DIR / "icon.png").convert("RGBA").resize((64, 64), Image.LANCZOS)
        except Exception:
            pass
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, 62, 62), fill=(238, 96, 40))
        d.rectangle((18, 22, 46, 44), outline="white", width=4)
        d.ellipse((28, 29, 36, 37), fill="white")
        return img

    # ---- F7, F8 단축키 받기 (윈도우가 직접 알려 주므로 중간에 풀리지 않음)
    def hotkey_loop(self):
        self.hotkey_thread_id = kernel32.GetCurrentThreadId()
        failed = [name for hid, (vk, name, _) in HOTKEYS.items()
                  if not user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk)]
        if failed:
            self.jobs.put(("toast",
                           f"{', '.join(failed)} 키를 다른 프로그램이 쓰고 있어요.\n"
                           "주황 아이콘 오른쪽 클릭 메뉴로 캡처하세요.", 5000))
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in HOTKEYS:
                self.jobs.put(HOTKEYS[msg.wParam][2])
        for hid in HOTKEYS:
            user32.UnregisterHotKey(None, hid)

    # ---- 이 창이 대화창인지 알아보기 (대화창이면 표시 이름, 아니면 None)
    @staticmethod
    def chat_label(hwnd):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid or pid == os.getpid():
                return None
            name = psutil.Process(pid).name().lower()
            if name in TARGETS:
                return TARGETS[name]
            if name in BROWSERS:
                title = win32gui.GetWindowText(hwnd).lower()
                for word, label in TITLE_KEYWORDS.items():
                    if word in title:
                        return label
        except Exception:
            pass
        return None

    # ---- 최근에 쓴 대화창 기억하기
    def track_claude_window(self):
        while self.running:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                if self.pinned and hwnd == self.pinned[0]:
                    self.use_pinned = True
                else:
                    label = self.chat_label(hwnd)
                    if label:
                        self.target = (hwnd, label)
                        self.use_pinned = False
            time.sleep(0.3)

    # ---- 할 일 처리 (단축키는 다른 줄에서 들어오므로 여기서 차례로 처리)
    def poll_jobs(self):
        try:
            while True:
                job = self.jobs.get_nowait()
                if isinstance(job, tuple) and job[0] == "toast":
                    self.toast(*job[1:])
                elif isinstance(job, tuple) and job[0] == "picked":
                    self.pinned = job[1:]
                    self.use_pinned = True
                    name = win32gui.GetWindowText(job[1])[:30] or "그 창"
                    self.toast(f"이제 F8 을 누르면 여기로 보내요!\n[{name}]", 3000)
                elif job == "region":
                    self.select_region()
                elif job == "pick":
                    self.pick_target()
                elif job == "capture":
                    self.capture_and_send()
                elif job == "folder":
                    SAVE_DIR.mkdir(parents=True, exist_ok=True)
                    subprocess.Popen(["explorer", str(SAVE_DIR)])
                elif job == "quit":
                    self.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.poll_jobs)

    # ---- 영역 지정 화면
    def select_region(self):
        if self.selecting:
            return
        self.selecting = True
        wait_keys_released()

        vx = user32.GetSystemMetrics(76)  # 모니터 전체(듀얼 모니터 포함)의 왼쪽
        vy = user32.GetSystemMetrics(77)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        sw = user32.GetSystemMetrics(0)  # 주 모니터 폭

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.35)
        top.geometry(f"{vw}x{vh}{vx:+d}{vy:+d}")

        c = tk.Canvas(top, bg="black", highlightthickness=0, cursor="cross")
        c.pack(fill="both", expand=True)
        c.create_text(-vx + sw // 2, -vy + 70,
                      text="캡처할 영역을 마우스로 드래그하세요   (취소: Esc)",
                      fill="white", font=("맑은 고딕", 22, "bold"))

        st = {"x": 0, "y": 0, "rect": None}

        def on_press(e):
            st["x"], st["y"] = e.x, e.y
            if st["rect"]:
                c.delete(st["rect"])
            st["rect"] = c.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff6a1a", width=3)

        def on_drag(e):
            if st["rect"]:
                c.coords(st["rect"], st["x"], st["y"], e.x, e.y)

        def finish(region):
            self.selecting = False
            try:
                top.grab_release()
            except Exception:
                pass
            top.destroy()
            if region:
                self.cfg["region"] = region
                save_config(self.cfg)
                self.toast("영역을 저장했어요!\n이제 F8 으로 캡처하세요.")

        def on_release(e):
            x1, x2 = sorted((st["x"], e.x))
            y1, y2 = sorted((st["y"], e.y))
            if x2 - x1 < 10 or y2 - y1 < 10:
                return  # 너무 작으면 다시 드래그
            finish({"left": vx + x1, "top": vy + y1, "width": x2 - x1, "height": y2 - y1})

        c.bind("<ButtonPress-1>", on_press)
        c.bind("<B1-Motion>", on_drag)
        c.bind("<ButtonRelease-1>", on_release)
        top.bind("<Escape>", lambda e: finish(None))
        top.focus_force()
        try:
            top.grab_set()
        except Exception:
            pass

    # ---- 붙여넣을 대화창 지정 (다음 마우스 클릭 자리를 기억)
    def pick_target(self):
        if self.picking:
            return
        self.picking = True
        self.toast("붙여넣을 대화창의 글 쓰는 칸을\n마우스로 한 번 클릭하세요.  (취소: Esc)", 4000)
        threading.Thread(target=self.wait_pick_click, daemon=True).start()

    def wait_pick_click(self):
        try:
            end = time.time() + 20
            while key_down(VK_LBUTTON) and time.time() < end:
                time.sleep(0.02)
            while time.time() < end:
                if key_down(VK_ESCAPE):
                    self.jobs.put(("toast", "대화창 지정을 취소했어요."))
                    return
                if key_down(VK_LBUTTON):
                    x, y = win32gui.GetCursorPos()
                    hwnd = user32.GetAncestor(win32gui.WindowFromPoint((x, y)), GA_ROOT)
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if hwnd and pid != os.getpid():
                        l, t, r, b = win32gui.GetWindowRect(hwnd)
                        # 창 크기가 바뀌어도 맞도록: 가로는 비율, 세로는 창 아래쪽에서 얼마나 위인지
                        self.jobs.put(("picked", hwnd, (x - l) / max(r - l, 1), b - y))
                        return
                    while key_down(VK_LBUTTON):
                        time.sleep(0.02)
                time.sleep(0.02)
            self.jobs.put(("toast", "시간이 지나서 대화창 지정을 취소했어요.\nF9 를 다시 눌러 주세요.", 3000))
        finally:
            self.picking = False

    # ---- 캡처해서 보내기
    def capture_and_send(self):
        region = self.cfg.get("region")
        if not region:
            self.toast("아직 영역을 안 정했어요.\n먼저 영역을 드래그해 주세요.")
            self.select_region()
            return

        try:
            with mss.mss() as sct:
                shot = sct.grab(region)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as e:
            self.toast(f"캡처에 실패했어요.\n영역을 다시 지정해 보세요.\n({e})", 4000)
            return

        # 1) 폴더에 저장
        try:
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            img.save(SAVE_DIR / f"캡처_{datetime.now():%Y%m%d_%H%M%S}.png")
        except Exception:
            pass

        # 2) 클립보드에 복사
        if not copy_image_to_clipboard(img):
            self.toast("클립보드 복사에 실패했어요. 한 번 더 눌러 주세요.")
            return

        # 3-1) 마지막으로 쓴 대화창이 F9로 지정한 창이면 그 칸을 클릭하고 붙여넣기
        if self.pinned and self.use_pinned and win32gui.IsWindow(self.pinned[0]):
            hwnd, fx, from_bottom = self.pinned
            wait_keys_released()
            if not bring_to_front(hwnd):
                self.toast("지정한 대화창을 못 불러왔어요.\n입력칸을 클릭하고 Ctrl+V 하세요.", 3500)
                return
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            x = min(max(l + fx * (r - l), l + 5), r - 5)
            y = min(max(b - from_bottom, t + 5), b - 5)
            click_at(x, y)
            send_ctrl_v()
            self.toast("지정한 대화창에 붙여넣었어요! 엔터로 보내세요.", 1800)
            return
        if self.pinned and not win32gui.IsWindow(self.pinned[0]):  # 지정했던 창이 닫힘
            self.pinned = None
            self.toast("지정했던 대화창이 닫혔어요.\nF9 로 다시 지정해 주세요.", 3500)

        # 3-2) 지정한 칸이 없으면 최근 대화창으로 가서 붙여넣기
        #    (인터넷 창은 그사이 다른 탭으로 바뀌었을 수 있으니, 지금도 대화창인지 다시 확인)
        hwnd = self.target[0] if self.target else None
        label = self.chat_label(hwnd) if hwnd and win32gui.IsWindow(hwnd) else None
        if not label:
            self.toast("캡처는 복사해 뒀어요.\n대화창 입력칸을 클릭한 뒤 Ctrl+V 하세요.", 3500)
            return

        wait_keys_released()
        if not bring_to_front(hwnd):
            self.toast(f"{label} 창을 못 불러왔어요.\n클로드 창에서 직접 Ctrl+V 하세요.", 3500)
            return
        send_ctrl_v()
        self.toast(f"{label}에 붙여넣었어요! 엔터로 보내세요.", 1800)

    # ---- 화면 오른쪽 아래 작은 알림
    def toast(self, text, ms=2000):
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            t.configure(bg="#ee6028")
            tk.Label(t, text=text, bg="#ee6028", fg="white",
                     font=("맑은 고딕", 11, "bold"), justify="left",
                     padx=16, pady=10).pack()
            t.update_idletasks()
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            w, h = t.winfo_width(), t.winfo_height()
            t.geometry(f"+{sw - w - 20}+{sh - h - 70}")
            t.after(ms, t.destroy)
        except Exception:
            pass

    def quit(self):
        self.running = False
        if self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, WM_QUIT, 0, 0)
        try:
            self.icon.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # 두 번 켜지지 않게 막기 (두 개가 켜지면 단축키가 서로 엉킴)
    _mutex = kernel32.CreateMutexW(None, False, "ClaudeCapture_SingleInstance")
    if kernel32.GetLastError() == 183:  # 이미 켜져 있음
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showinfo("클로드 캡처",
                            "클로드 캡처는 이미 켜져 있어요.\n"
                            "화면 오른쪽 아래 ^ 안의 주황 아이콘을 확인하세요.")
        sys.exit(0)
    App().run()
