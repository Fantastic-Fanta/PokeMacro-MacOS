import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "configs.yaml"
_venv_python = PROJECT_ROOT / "ENV" / "bin" / "python"
VENV_PYTHON = _venv_python if _venv_python.exists() else Path(sys.executable)

POSITION_KEYS = [
    ("EggManPosition", "Egg Man Position"),
    ("EventButton", "Event Button"),
    ("DialogueYES", "Dialogue YES"),
    ("QuickRejoinSprite", "Quick Rejoin Sprite"),
    ("QuickRejoinButton", "Quick Rejoin Button"),
    ("MenuButton", "Menu Button"),
    ("SaveButton", "Save Button"),
    ("LoadingScreenYellow", "Loading Screen Yellow"),
    ("SaveFileCard", "Save File Card"),
    ("RunButton", "Run Button"),
    ("Pokeball", "Pokeball"),
]


class ConfigManager:
    def load(self) -> dict:
        try:
            with open(CONFIG_PATH, "r") as f:
                data = yaml.safe_load(f) or {}
            return data
        except FileNotFoundError:
            return self._default_config()

    def save(self, data: dict) -> None:
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _default_config(self) -> dict:
        return {
            "HuntingMode": "egg",
            "Username": "",
            "Mode": "Default",
            "IsReskin": False,
            "IsShiny": False,
            "IsGradient": False,
            "IsAny": True,
            "IsGood": False,
            "Wishlist": {"Reskins": [], "Gradients": [], "Roamings": [], "Special": []},
            "Positions": {k: [0, 0] for k, _ in POSITION_KEYS},
            "ChatWindow": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "EncounterNameRegion": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "SpriteRegion": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "DiscordBotToken": "",
            "ServerID": 0,
        }


class SubprocessManager:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._log_thread: threading.Thread | None = None

    def start(self, log_queue: queue.Queue, on_exit) -> None:
        self._proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "src.main"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._log_thread = threading.Thread(
            target=self._stream_logs,
            args=(log_queue, on_exit),
            daemon=True,
        )
        self._log_thread.start()

    def _stream_logs(self, log_queue: queue.Queue, on_exit) -> None:
        for line in self._proc.stdout:
            log_queue.put(line.rstrip("\n"))
        self._proc.wait()
        on_exit(self._proc.returncode)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

            def _wait_kill():
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()

            threading.Thread(target=_wait_kill, daemon=True).start()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class PokeMacroApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PokeMacro")
        self.minsize(920, 680)
        self.resizable(True, True)

        self._config_manager = ConfigManager()
        self._subprocess_manager = SubprocessManager()
        self._config = self._config_manager.load()
        self._is_running = False
        self._log_queue: queue.Queue = queue.Queue()
        self._all_config_widgets: list = []

        self._build_ui()
        self._load_all_fields()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.createcommand("tk::mac::Quit", self._on_close)
        except Exception:
            pass
        self.after(100, self._poll_log_queue)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_status_bar()
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._build_general_tab(self._notebook)
        self._build_wishlist_tab(self._notebook)
        self._build_positions_tab(self._notebook)
        self._build_discord_tab(self._notebook)
        self._build_logs_tab(self._notebook)

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        self._status_label = ttk.Label(bar, text="Idle")
        self._status_label.pack(side="left")
        self._start_stop_btn = ttk.Button(bar, text="Start", width=10, command=self._toggle_run)
        self._start_stop_btn.pack(side="right")

    def _build_general_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="General")

        def row(r, label, widget):
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            widget.grid(row=r, column=1, sticky="ew", pady=4)
            frame.columnconfigure(1, weight=1)

        self._gen_hunting_mode = ttk.Combobox(frame, values=["egg", "roam"], state="readonly", width=14)
        row(0, "Hunting Mode", self._gen_hunting_mode)

        self._gen_username_var = tk.StringVar()
        username_entry = ttk.Entry(frame, textvariable=self._gen_username_var)
        row(1, "Username", username_entry)

        self._gen_mode = ttk.Combobox(frame, values=["Default", "Fast"], state="readonly", width=14)
        row(2, "Mode", self._gen_mode)

        bool_fields = [
            ("IsReskin", "Is Reskin"),
            ("IsShiny", "Is Shiny"),
            ("IsGradient", "Is Gradient"),
            ("IsAny", "Is Any"),
            ("IsGood", "Is Good"),
        ]
        self._gen_bool_vars: dict[str, tk.BooleanVar] = {}
        for i, (key, label) in enumerate(bool_fields):
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(frame, text=label, variable=var)
            cb.grid(row=3 + i, column=0, columnspan=2, sticky="w", pady=2)
            self._gen_bool_vars[key] = var
            self._all_config_widgets.append(cb)

        save_btn = ttk.Button(frame, text="Save Config", command=self._save_config)
        save_btn.grid(row=3 + len(bool_fields) + 1, column=0, columnspan=2, pady=(16, 0))

        self._all_config_widgets += [self._gen_hunting_mode, username_entry, self._gen_mode]

    def _build_wishlist_tab(self, notebook: ttk.Notebook) -> None:
        outer = ttk.Frame(notebook, padding=8)
        notebook.add(outer, text="Wishlist")
        ttk.Label(outer, text="Enter each item on its own line (or comma-separated).").pack(anchor="w", pady=(0, 6))

        self._wish_texts: dict[str, tk.Text] = {}
        for list_name, height in [("Reskins", 4), ("Gradients", 4), ("Roamings", 7), ("Special", 7)]:
            lf = ttk.LabelFrame(outer, text=list_name, padding=6)
            lf.pack(fill="x", pady=4)
            txt = tk.Text(lf, height=height, wrap="word")
            sb = ttk.Scrollbar(lf, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            txt.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self._wish_texts[list_name] = txt
            self._all_config_widgets.append(txt)

    def _build_positions_tab(self, notebook: ttk.Notebook) -> None:
        outer = ttk.Frame(notebook)
        notebook.add(outer, text="Positions")

        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = ttk.Frame(canvas, padding=10)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_resize(event):
            canvas.itemconfig(window_id, width=event.width)

        content.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        vcmd = (self.register(lambda s: s == "" or (s.lstrip("-").isdigit())), "%P")

        def coord_pair(parent, row, label, ref_dict, key):
            ttk.Label(parent, text=label, width=22, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            x_entry = ttk.Entry(parent, width=7, validate="key", validatecommand=vcmd)
            y_entry = ttk.Entry(parent, width=7, validate="key", validatecommand=vcmd)
            ttk.Label(parent, text="X").grid(row=row, column=1, padx=(8, 2))
            x_entry.grid(row=row, column=2)
            ttk.Label(parent, text="Y").grid(row=row, column=3, padx=(8, 2))
            y_entry.grid(row=row, column=4)
            ref_dict[key] = (x_entry, y_entry)
            self._all_config_widgets += [x_entry, y_entry]

        # Positions section
        pos_lf = ttk.LabelFrame(content, text="Positions", padding=8)
        pos_lf.pack(fill="x", pady=(0, 8))
        self._pos_entries: dict[str, tuple] = {}
        for i, (key, label) in enumerate(POSITION_KEYS):
            coord_pair(pos_lf, i, label, self._pos_entries, key)

        # Region sections
        regions = [
            ("Chat Window", "ChatWindow"),
            ("Encounter Name Region", "EncounterNameRegion"),
            ("Sprite Region", "SpriteRegion"),
        ]
        self._region_entries: dict[str, dict] = {}
        for title, key in regions:
            lf = ttk.LabelFrame(content, text=title, padding=8)
            lf.pack(fill="x", pady=(0, 8))
            d: dict[str, tuple] = {}
            coord_pair(lf, 0, "Left Corner", d, "LeftCorner")
            coord_pair(lf, 1, "Right Corner", d, "RightCorner")
            self._region_entries[key] = d

    def _build_discord_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="Discord")

        ttk.Label(frame, text="Bot Token").grid(row=0, column=0, sticky="w", pady=6, padx=(0, 12))
        token_frame = ttk.Frame(frame)
        token_frame.grid(row=0, column=1, sticky="ew")
        frame.columnconfigure(1, weight=1)

        self._disc_token_entry = ttk.Entry(token_frame, show="*")
        self._disc_token_entry.pack(side="left", fill="x", expand=True)
        self._token_shown = False

        def toggle_token():
            self._token_shown = not self._token_shown
            self._disc_token_entry.config(show="" if self._token_shown else "*")
            show_btn.config(text="Hide" if self._token_shown else "Show")

        show_btn = ttk.Button(token_frame, text="Show", width=6, command=toggle_token)
        show_btn.pack(side="left", padx=(6, 0))

        ttk.Label(frame, text="Server ID").grid(row=1, column=0, sticky="w", pady=6, padx=(0, 12))
        vcmd = (self.register(lambda s: s == "" or s.isdigit()), "%P")
        self._disc_server_id_entry = ttk.Entry(frame, width=20, validate="key", validatecommand=vcmd)
        self._disc_server_id_entry.grid(row=1, column=1, sticky="w", pady=6)

        save_btn = ttk.Button(frame, text="Save Config", command=self._save_config)
        save_btn.grid(row=2, column=0, columnspan=2, pady=(16, 0))

        self._all_config_widgets += [self._disc_token_entry, self._disc_server_id_entry]

    def _build_logs_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Logs")

        btn_bar = ttk.Frame(frame, padding=(6, 4))
        btn_bar.pack(fill="x")
        ttk.Button(btn_bar, text="Clear", command=self._clear_logs).pack(side="left", padx=(0, 4))
        ttk.Button(btn_bar, text="Copy", command=self._copy_logs).pack(side="left")

        self._log_text = tk.Text(
            frame,
            state="disabled",
            wrap="word",
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            font=("Courier New", 11),
        )
        log_sb = ttk.Scrollbar(frame, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

    # ── Config I/O ───────────────────────────────────────────────────────────

    def _load_all_fields(self) -> None:
        cfg = self._config
        self._gen_hunting_mode.set(cfg.get("HuntingMode", "egg"))
        self._gen_username_var.set(cfg.get("Username", ""))
        self._gen_mode.set(cfg.get("Mode", "Default"))
        for key, var in self._gen_bool_vars.items():
            var.set(bool(cfg.get(key, False)))

        wishlist = cfg.get("Wishlist", {})
        for list_name, txt in self._wish_texts.items():
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join(wishlist.get(list_name, [])))

        positions = cfg.get("Positions", {})
        for key, (xe, ye) in self._pos_entries.items():
            pair = positions.get(key, [0, 0])
            xe.delete(0, "end"); xe.insert(0, str(pair[0]))
            ye.delete(0, "end"); ye.insert(0, str(pair[1]))

        for region_key, entries in self._region_entries.items():
            region = cfg.get(region_key, {})
            for corner_key, (xe, ye) in entries.items():
                pair = region.get(corner_key, [0, 0])
                xe.delete(0, "end"); xe.insert(0, str(pair[0]))
                ye.delete(0, "end"); ye.insert(0, str(pair[1]))

        self._disc_token_entry.delete(0, "end")
        self._disc_token_entry.insert(0, cfg.get("DiscordBotToken", ""))
        self._disc_server_id_entry.delete(0, "end")
        self._disc_server_id_entry.insert(0, str(cfg.get("ServerID", 0)))

    def _collect_config(self) -> dict:
        def read_text(widget: tk.Text) -> list:
            raw = widget.get("1.0", "end").strip()
            items = [i.strip() for part in raw.splitlines() for i in part.split(",")]
            return [i for i in items if i]

        def read_coord(pair: tuple) -> list:
            return [int(pair[0].get() or "0"), int(pair[1].get() or "0")]

        return {
            "HuntingMode": self._gen_hunting_mode.get(),
            "Username": self._gen_username_var.get(),
            "Wishlist": {name: read_text(txt) for name, txt in self._wish_texts.items()},
            "Positions": {key: read_coord(pair) for key, pair in self._pos_entries.items()},
            **{region_key: {corner: read_coord(pair) for corner, pair in entries.items()}
               for region_key, entries in self._region_entries.items()},
            **{key: var.get() for key, var in self._gen_bool_vars.items()},
            "Mode": self._gen_mode.get(),
            "DiscordBotToken": self._disc_token_entry.get(),
            "ServerID": int(self._disc_server_id_entry.get() or "0"),
        }

    def _save_config(self) -> None:
        data = self._collect_config()
        self._config_manager.save(data)
        prev = self._status_label.cget("text")
        self._status_label.config(text="Config saved.")
        self.after(2000, lambda: self._status_label.config(
            text="Running..." if self._is_running else prev if prev != "Config saved." else "Idle"
        ))

    # ── Start / Stop ─────────────────────────────────────────────────────────

    def _toggle_run(self) -> None:
        if not self._is_running:
            self._start_run()
        else:
            self._stop_run()

    def _start_run(self) -> None:
        self._save_config()
        self._is_running = True
        self._start_stop_btn.config(text="Stop")
        self._status_label.config(text="Running...")
        self._set_fields_enabled(False)
        self._subprocess_manager.start(
            log_queue=self._log_queue,
            on_exit=lambda code: self.after(0, lambda: self._on_process_exit(code)),
        )

    def _stop_run(self) -> None:
        self._start_stop_btn.config(text="Stopping...", state="disabled")
        self._status_label.config(text="Stopping...")
        self._subprocess_manager.stop()

    def _on_process_exit(self, returncode: int) -> None:
        self._is_running = False
        self._set_fields_enabled(True)
        self._start_stop_btn.config(text="Start", state="normal")
        label = "Idle" if returncode == 0 else f"Stopped (exit {returncode})"
        self._status_label.config(text=label)

    def _set_fields_enabled(self, enabled: bool) -> None:
        for widget in self._all_config_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.config(state="readonly" if enabled else "disabled")
            else:
                widget.config(state="normal" if enabled else "disabled")

    # ── Log streaming ─────────────────────────────────────────────────────────

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _append_log(self, line: str) -> None:
        at_bottom = self._log_text.yview()[1] >= 0.99
        self._log_text.config(state="normal")
        self._log_text.insert("end", line + "\n")
        self._log_text.config(state="disabled")
        if at_bottom:
            self._log_text.see("end")

    def _clear_logs(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    def _copy_logs(self) -> None:
        content = self._log_text.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(content)

    # ── Window close ─────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._is_running:
            if messagebox.askyesno("Quit", "Macro is running. Stop it and quit?"):
                self._subprocess_manager.stop()
            else:
                return
        self.destroy()


def main() -> None:
    app = PokeMacroApp()
    app.mainloop()


if __name__ == "__main__":
    main()
