"""Windows 隐私便签：可粘贴文章，并请求 Windows 会议捕获排除。"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

STATE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PrivateNote"
CONFIG = STATE / "settings.json"
WDA_EXCLUDEFROMCAPTURE = 0x11


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(data):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class PrivateNote:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("隐私便签")
        self.root.overrideredirect(True)
        self.root.configure(bg="#151918")
        self.root.geometry(self.config.get("geometry", "520x360+120+120"))
        self.root.attributes("-topmost", True)
        self.excluded = False
        self.hidden = False
        self.hotkey_down = False
        self.build_ui()
        self.apply_capture_exclusion()
        self.root.bind("<Control-s>", lambda e: self.save_note())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.hotkey_timer = self.root.after(80, self.poll_hotkey)

    def build_ui(self):
        header = tk.Frame(self.root, bg="#151918")
        header.pack(fill="x", padx=12, pady=(8, 2))
        title = tk.Label(header, text="隐私便签", bg="#151918", fg="#e9d28b", font=("Microsoft YaHei UI", 10))
        title.pack(side="left")
        status = tk.Label(header, text="捕获排除：检测中", bg="#151918", fg="#9bb9aa", font=("Microsoft YaHei UI", 8))
        status.pack(side="left", padx=12)
        self.status = status
        tk.Button(header, text="×", command=self.close, bg="#151918", fg="#cbd4ce", relief="flat", bd=0).pack(side="right")
        for item in (header, title, status):
            item.bind("<ButtonPress-1>", self.start_drag)
            item.bind("<B1-Motion>", self.drag)
        self.text = tk.Text(self.root, wrap="word", undo=True, bg="#202522", fg="#edf3ee", insertbackground="#efce75",
                            selectbackground="#806d31", relief="flat", bd=0, padx=14, pady=12,
                            font=("Microsoft YaHei UI", 12))
        self.text.pack(fill="both", expand=True, padx=10, pady=(4, 8))
        self.text.insert("1.0", self.config.get("text", "把文章粘贴到这里…\n\n这个窗口请求 Windows 将其从屏幕捕获中排除。"))
        self.text.bind("<ButtonPress-1>", self.start_drag)
        self.text.bind("<B1-Motion>", self.drag)
        self.text.bind("<KeyRelease>", lambda e: self.save_config())
        footer = tk.Frame(self.root, bg="#151918")
        footer.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(footer, text="Ctrl+S 保存 · Esc 退出 · 可直接 Ctrl+V 粘贴", bg="#151918", fg="#829088", font=("Microsoft YaHei UI", 8)).pack(side="left")
        tk.Button(footer, text="重新检测", command=self.apply_capture_exclusion, bg="#151918", fg="#cbd4ce", relief="flat", bd=0).pack(side="right")
        self.grip = tk.Label(self.root, text="◢", bg="#151918", fg="#829088", cursor="size_nw_se", font=("Segoe UI", 9))
        self.grip.place(relx=1, rely=1, anchor="se")
        self.grip.bind("<ButtonPress-1>", self.start_resize)
        self.grip.bind("<B1-Motion>", self.drag_resize)
        self.grip.bind("<ButtonRelease-1>", lambda e: self.save_config())

    def apply_capture_exclusion(self):
        self.root.update_idletasks()
        # Tk 返回的是客户区句柄；Windows 捕获属性必须设置在顶层窗口句柄上。
        hwnd = wintypes.HWND(ctypes.windll.user32.GetParent(self.root.winfo_id()))
        self.excluded = bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
        self.status.configure(text="捕获排除：已启用" if self.excluded else "捕获排除：系统不支持",
                              fg="#9bd4ad" if self.excluded else "#e3a477")

    def start_drag(self, event):
        self.offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag(self, event):
        self.root.geometry(f"+{event.x_root-self.offset[0]}+{event.y_root-self.offset[1]}")

    def start_resize(self, event):
        self.resize_origin = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())

    def drag_resize(self, event):
        x, y, width, height = self.resize_origin
        self.root.geometry(f"{max(300, width + event.x_root - x)}x{max(220, height + event.y_root - y)}")

    def poll_hotkey(self):
        """轮询全局按键状态，隐藏后仍可用 Ctrl+Shift+H 恢复。"""
        try:
            ctrl = ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000
            shift = ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000
            h = ctypes.windll.user32.GetAsyncKeyState(0x48) & 0x8000
            pressed = bool(ctrl and shift and h)
            if pressed and not self.hotkey_down:
                self.toggle_visibility()
            self.hotkey_down = pressed
        finally:
            if not self.root.winfo_exists():
                return
            self.hotkey_timer = self.root.after(80, self.poll_hotkey)

    def toggle_visibility(self):
        self.hidden = not self.hidden
        if self.hidden:
            self.save_config()
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.apply_capture_exclusion()

    def save_config(self):
        save_config({"geometry": f"{self.root.winfo_width()}x{self.root.winfo_height()}+{self.root.winfo_x()}+{self.root.winfo_y()}", "text": self.text.get("1.0", "end-1c")})

    def save_note(self):
        self.save_config()
        self.status.configure(text="已保存", fg="#9bd4ad")

    def close(self):
        if hasattr(self, "hotkey_timer"):
            self.root.after_cancel(self.hotkey_timer)
        self.save_config()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    PrivateNote().run()
