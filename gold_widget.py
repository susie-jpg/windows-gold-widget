import datetime as dt
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
import urllib.request


# 国际黄金现货与每日汇率；人民币价格是换算值，不是银行积存金报价。
GOLD_URL = "https://api.gold-api.com/price/XAU"
FX_URL = "https://open.er-api.com/v6/latest/USD"
OUNCE_GRAMS = 31.1034768
REFRESH_SECONDS = 1
THEMES = {
    "dark": {"bg": "#161918", "text": "#dce5df", "muted": "#9aa99f", "price": "#efce75", "ok": "#8eaa9a", "warning": "#dba26d", "hover": "#313a35"},
    "light": {"bg": "#f5f7f6", "text": "#202923", "muted": "#5d6c62", "price": "#956b08", "ok": "#397055", "warning": "#a34817", "hover": "#dce5df"},
    "forest": {"bg": "#163b32", "text": "#edf6f1", "muted": "#b1cec1", "price": "#f4d37c", "ok": "#a4d9bd", "warning": "#ffb684", "hover": "#285448"},
}
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GoldWidget"
STATE_FILE = STATE_DIR / "settings.json"


def fetch_json(url):
    """读取 JSON 接口，设置超时以免网络故障阻塞后台线程。"""
    request = urllib.request.Request(url, headers={"User-Agent": "GoldWidget/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def load_settings():
    """配置不存在或损坏时使用默认值，不影响启动。"""
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class GoldWidget:
    """使用 Tkinter 实现无边框、可置顶的 Windows 金价组件。"""
    def __init__(self):
        self.settings = load_settings()
        self.theme = self.settings.get("theme", "dark")
        if self.theme not in THEMES:
            self.theme = "dark"
        self.scalable = []
        self.mini = False
        self.root = tk.Tk()
        self.root.title("Gold Price")
        self.root.overrideredirect(True)
        self.root.configure(bg="#161918")
        width, height = self.settings.get("size", [240, 160])
        if not self.settings.get("compact_footer"):
            # 兼容旧版配置：去掉说明行后按比例收紧窗口高度。
            height = round(int(height) * 160 / 184)
        self.root.geometry(f"{max(220, int(width))}x{max(146, int(height))}")
        self.root.minsize(220, 146)
        self.root.geometry(self.settings.get("position", "+80+80"))
        self.pinned = bool(self.settings.get("pinned", True))
        self.root.attributes("-topmost", self.pinned)
        # 后台线程只写队列；界面更新统一由 Tk 主线程处理。
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.price = None
        self.fx = None
        self.fx_time = 0
        self.updated = None
        self.last_received = 0
        self.error = False
        self.unit = self.settings.get("unit", "USD")
        self.next_refresh = 0
        self.build_ui()
        self.apply_theme()
        self.root.bind("<Configure>", self.resize_content)
        self.normal_size = (max(220, int(width)), max(146, int(height)))
        if self.settings.get("mini", False):
            self.set_mini(True, persist=False)
        self.root.bind("<Escape>", lambda event: self.close())
        self.root.bind("<Button-3>", self.show_menu)
        self.refresh()
        self.tick()

    def label(self, parent, text, size, color, **kwargs):
        widget = tk.Label(parent, text=text, font=("Microsoft YaHei UI", size),
                          fg=color, bg="#161918", **kwargs)
        role = {"#efce75": "price", "#dce5df": "text", "#8eaa9a": "ok"}.get(color, "muted")
        self.scalable.append((widget, "Microsoft YaHei UI", size, role))
        return widget

    def button(self, parent, text, command):
        widget = tk.Button(parent, text=text, command=command, font=("Segoe UI", 11),
                         fg="#c5cec9", bg="#161918", activebackground="#313a35",
                         activeforeground="white", relief="flat", bd=0, cursor="hand2",
                         padx=5, pady=0, takefocus=True)
        self.scalable.append((widget, "Segoe UI", 11, "text"))
        return widget

    def build_ui(self):
        """创建普通窗口和右键菜单，使用相对布局适应不同尺寸。"""
        header = tk.Frame(self.root, bg="#161918")
        header.place(relx=.033, rely=.025, relwidth=.934, relheight=.188)
        self.header = header
        title = self.label(header, "\u56fd\u9645\u91d1\u4ef7", 9, "#dce5df")
        title.pack(side="left")
        self.button(header, "\u00d7", self.close).pack(side="right")
        self.pin_button = self.button(header, "\u25c6" if self.pinned else "\u25c7", self.toggle_pin)
        self.pin_button.pack(side="right")
        self.button(header, "\u21bb", self.refresh).pack(side="right")
        for item in (header, title):
            item.bind("<ButtonPress-1>", self.start_drag)
            item.bind("<B1-Motion>", self.drag)
            item.bind("<ButtonRelease-1>", lambda event: self.save())
        self.value_label = self.label(self.root, "--", 23, "#efce75", anchor="w")
        self.value_label.place(relx=.05, rely=.213, relwidth=.9, relheight=.276)
        self.unit_label = self.label(self.root, "USD / troy oz", 8, "#9aa99f", anchor="w")
        self.unit_label.place(relx=.058, rely=.489, relwidth=.884, relheight=.138)
        self.value_label.bind("<Button-1>", self.press_value)
        self.value_label.bind("<B1-Motion>", self.drag_value)
        self.value_label.bind("<ButtonRelease-1>", self.release_value)
        self.unit_label.bind("<Button-1>", lambda event: self.toggle_unit())
        self.secondary = self.label(self.root, "\u6b63\u5728\u8fde\u63a5\u884c\u60c5...", 9, "#dce5df", anchor="w")
        self.secondary.place(relx=.058, rely=.633, relwidth=.884, relheight=.149)
        self.status = self.label(self.root, "", 8, "#8eaa9a", anchor="w")
        self.status.place(relx=.058, rely=.794, relwidth=.85, relheight=.138)
        self.grip = self.label(self.root, "\u25e2", 9, "#77847c", cursor="size_nw_se")
        self.grip.place(relx=1, rely=1, anchor="se")
        self.grip.bind("<ButtonPress-1>", self.start_resize)
        self.grip.bind("<B1-Motion>", self.drag_resize)
        self.grip.bind("<ButtonRelease-1>", lambda event: self.save())
        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="\u5237\u65b0\u884c\u60c5", command=self.refresh)
        self.menu.add_command(label="\u5207\u6362\u8ba1\u4ef7\u5355\u4f4d", command=self.toggle_unit)
        self.menu.add_command(label="\u5207\u6362\u7f6e\u9876", command=self.toggle_pin)
        self.theme_choice = tk.StringVar(value=self.theme)
        theme_menu = tk.Menu(self.menu, tearoff=False)
        for key, name in (("dark", "\u6df1\u8272"), ("light", "\u6d45\u8272"), ("forest", "\u68ee\u6797\u7eff")):
            theme_menu.add_radiobutton(label=name, variable=self.theme_choice, value=key,
                                       command=lambda selected=key: self.set_theme(selected))
        self.menu.add_cascade(label="\u4e3b\u9898", menu=theme_menu)
        size_menu = tk.Menu(self.menu, tearoff=False)
        self.mini_choice = tk.BooleanVar(value=False)
        size_menu.add_checkbutton(label="\u8d85\u8ff7\u4f60\uff08\u4ec5\u6570\u5b57\uff09", variable=self.mini_choice,
                                  command=lambda: self.set_mini(self.mini_choice.get()))
        size_menu.add_separator()
        for name, width, height in (("\u5c0f", 220, 146), ("\u6807\u51c6", 240, 160), ("\u5927", 360, 240)):
            size_menu.add_command(label=name, command=lambda w=width, h=height: self.set_size(w, h))
        self.menu.add_cascade(label="\u7a97\u53e3\u5927\u5c0f", menu=size_menu)
        self.menu.add_separator()
        self.menu.add_command(label="\u9000\u51fa", command=self.close)

    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def set_theme(self, theme):
        self.theme = theme
        self.theme_choice.set(theme)
        self.apply_theme()
        self.render()
        self.save()

    def apply_theme(self):
        colors = THEMES[self.theme]
        self.root.configure(bg=colors["bg"])
        self.header.configure(bg=colors["bg"])
        for widget, family, size, role in self.scalable:
            widget.configure(bg=colors["bg"], fg=colors[role])
            if isinstance(widget, tk.Button):
                widget.configure(activebackground=colors["hover"], activeforeground=colors["text"])

    def resize_content(self, event):
        # 忽略子控件的尺寸事件，防止字体调整引发重复缩放。
        if event.widget != self.root:
            return
        if self.mini:
            self.fit_mini_text()
            return
        scale = min(event.width / 240, event.height / 160)
        for widget, family, size, role in self.scalable:
            widget.configure(font=(family, max(7, round(size * scale))))

    def start_resize(self, event):
        self.resize_origin = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())

    def drag_resize(self, event):
        x, y, width, height = self.resize_origin
        self.root.geometry(f"{max(220, width + event.x_root - x)}x{max(146, height + event.y_root - y)}")

    def set_size(self, width, height):
        if self.mini:
            self.set_mini(False, persist=False)
        self.root.geometry(f"{width}x{height}")
        self.root.update_idletasks()
        self.normal_size = (width, height)
        self.save()

    def set_mini(self, enabled, persist=True):
        """切换仅显示数字的模式，并保留普通模式的窗口尺寸。"""
        if enabled == self.mini:
            return
        if enabled:
            self.root.update_idletasks()
            self.normal_size = (self.root.winfo_width(), self.root.winfo_height())
        self.mini = enabled
        self.mini_choice.set(enabled)
        if enabled:
            for widget in (self.header, self.unit_label, self.secondary, self.status, self.grip):
                widget.place_forget()
            self.root.minsize(100, 36)
            self.root.geometry("132x44")
            self.value_label.configure(anchor="center", cursor="fleur")
            self.value_label.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.root.minsize(220, 146)
            self.root.geometry(f"{self.normal_size[0]}x{self.normal_size[1]}")
            self.header.place(relx=.033, rely=.025, relwidth=.934, relheight=.188)
            self.value_label.configure(anchor="w", cursor="")
            self.value_label.place(relx=.05, rely=.213, relwidth=.9, relheight=.276)
            self.unit_label.place(relx=.058, rely=.489, relwidth=.884, relheight=.138)
            self.secondary.place(relx=.058, rely=.633, relwidth=.884, relheight=.149)
            self.status.place(relx=.058, rely=.794, relwidth=.85, relheight=.138)
            self.grip.place(relx=1, rely=1, anchor="se")
        self.root.update_idletasks()
        self.render()
        if persist:
            self.save()

    def fit_mini_text(self):
        # 根据实际文本宽度缩小字体，美元报价较长时也不会被截断。
        width = max(1, self.root.winfo_width() - 12)
        height = max(1, self.root.winfo_height() - 8)
        size = min(23, max(7, int(height * .55)))
        font = tkfont.Font(family="Microsoft YaHei UI", size=size)
        while size > 7 and (font.measure(self.value_label.cget("text")) > width or font.metrics("linespace") > height):
            size -= 1
            font.configure(size=size)
        self.value_label.configure(font=("Microsoft YaHei UI", size))

    def press_value(self, event):
        if self.mini:
            self.start_drag(event)
        else:
            self.toggle_unit()

    def drag_value(self, event):
        if self.mini:
            self.drag(event)

    def release_value(self, event):
        if self.mini:
            self.save()

    def start_drag(self, event):
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag(self, event):
        x = max(0, event.x_root - self.drag_offset[0])
        y = max(0, event.y_root - self.drag_offset[1])
        self.root.geometry(f"+{x}+{y}")

    def save(self):
        """将个人偏好保存在本机 AppData，不写入项目目录。"""
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({"position": f"+{max(0, self.root.winfo_x())}+{max(0, self.root.winfo_y())}",
                                             "unit": self.unit, "pinned": self.pinned,
                                             "theme": self.theme,
                                             "compact_footer": True,
                                             "mini": self.mini,
                                             "size": list(self.normal_size) if self.mini else [self.root.winfo_width(), self.root.winfo_height()]}), encoding="utf-8")
        except OSError:
            pass

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.pin_button.configure(text="\u25c6" if self.pinned else "\u25c7")
        self.save()

    def toggle_unit(self):
        self.unit = "CNY" if self.unit == "USD" else "USD"
        self.render()
        self.save()

    def refresh(self):
        # 请求未结束时不再发起新请求；用单调时钟避免系统校时干扰。
        if self.busy or self.closed:
            return
        self.busy = True
        self.next_refresh = time.monotonic() + REFRESH_SECONDS
        self.status.configure(text="\u6b63\u5728\u5237\u65b0...", fg=THEMES[self.theme]["ok"])
        threading.Thread(target=self.fetch, daemon=True).start()

    def fetch(self):
        """获取金价和汇率，把成功或失败事件送回主线程。"""
        try:
            data = fetch_json(GOLD_URL)
            price = float(data["price"])
            if price <= 0:
                raise ValueError("Invalid price")
            updated = dt.datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00"))
            self.events.put(("gold", price, updated))
        except Exception:
            self.events.put(("error",))
        # 汇率源每日更新，无需随金价每秒重复获取。
        if time.time() - self.fx_time > 3600:
            try:
                data = fetch_json(FX_URL)
                fx = float(data["rates"]["CNY"])
                if data["result"] != "success" or fx <= 0:
                    raise ValueError("Invalid exchange rate")
                self.events.put(("fx", fx, data["time_last_update_utc"]))
            except Exception:
                self.events.put(("fx_error",))
        self.events.put(("done",))

    def render(self):
        # 一金衡盎司等于 31.1034768 克。
        cny = self.price * self.fx / OUNCE_GRAMS if self.price and self.fx else None
        if self.unit == "CNY":
            self.value_label.configure(text=f"{cny:,.2f}" if cny else "--")
            self.unit_label.configure(text="CNY / g  (\u6c47\u7387\u6362\u7b97)")
            other = f"$ {self.price:,.2f} / oz" if self.price else "--"
        else:
            self.value_label.configure(text=f"{self.price:,.2f}" if self.price else "--")
            self.unit_label.configure(text="USD / troy oz")
            other = f"\u00a5 {cny:,.2f} / \u514b  (\u6362\u7b97)" if cny else "\u6c47\u7387\u6682\u4e0d\u53ef\u7528"
        self.secondary.configure(text=other)
        # 请求成功不代表源数据刚更新，单独检查行情源时间。
        stale = self.updated and (dt.datetime.now(dt.timezone.utc) - self.updated).total_seconds() > 180
        remaining = max(0, int(self.next_refresh - time.monotonic()) + 1)
        if self.busy:
            status = "\u6b63\u5728\u5237\u65b0..."
        elif self.error:
            status = f"\u8fde\u63a5\u5931\u8d25 \u00b7 {remaining}s\u540e\u91cd\u8bd5"
        elif self.last_received:
            stamp = dt.datetime.fromtimestamp(self.last_received).strftime("%H:%M:%S")
            prefix = "\u6e90\u5ef6\u8fdf" if stale else "\u5df2\u5237\u65b0"
            status = f"{prefix} {stamp} \u00b7 {remaining}s"
        else:
            status = "\u7b49\u5f85\u884c\u60c5"
        self.status.configure(text=status, fg=THEMES[self.theme]["warning" if self.error or stale else "ok"])
        self.value_label.configure(fg=THEMES[self.theme]["warning" if self.mini and (self.error or stale) else "price"])
        if self.mini:
            self.fit_mini_text()

    def tick(self):
        """每 250 毫秒处理消息；按每秒一次的目标频率发起行情请求。"""
        if self.closed:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "gold":
                self.price, self.updated = event[1:]
                self.error = False
                self.last_received = time.time()
            elif event[0] == "fx":
                self.fx = event[1]
                self.fx_time = time.time()
            elif event[0] == "error":
                self.error = True
            elif event[0] == "done":
                self.busy = False
        if not self.busy and time.monotonic() >= self.next_refresh:
            self.refresh()
        self.render()
        self.tick_timer = self.root.after(250, self.tick)

    def close(self):
        # 退出前取消定时回调，避免窗口销毁后仍执行界面操作。
        self.closed = True
        if hasattr(self, "tick_timer"):
            self.root.after_cancel(self.tick_timer)
        self.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    GoldWidget().run()
