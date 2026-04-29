from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pyautogui

from .click_executor import ClickExecutor
from .discord_bot import DiscordBot
from .hunter_config import CHAT_REGION, SPECIAL_VARIANTS
from .macro_config import DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, get_config_dict
from .ocr_screen import OcrService, ScreenRegion
from .roam_text import is_special_roaming
from .url_opener import open_roblox_place


class StaticRunner:
    """Execute a user-defined sequence of Statics blocks in a loop."""

    def __init__(self) -> None:
        c = get_config_dict()
        self._blocks: list[dict] = c.get("Statics") or []
        self._click_executor = ClickExecutor()
        self._ocr = OcrService()
        cx, cy, cw, ch = CHAT_REGION
        self._chat_region = ScreenRegion(x=cx, y=cy, width=cw, height=ch)
        self._screenshot_path = (
            Path(__file__).resolve().parent.parent / "static_screenshot.png"
        )
        self._running = False
        self._discord: Optional[DiscordBot] = None
        if DISCORD_BOT_TOKEN and DISCORD_GUILD_ID:
            try:
                self._discord = DiscordBot(DISCORD_BOT_TOKEN, int(DISCORD_GUILD_ID))
            except Exception as e:
                print(f"[StaticRunner] Discord init failed: {e}")

    def run(self) -> None:
        if not self._blocks:
            print("[StaticRunner] No blocks configured.")
            return
        if self._discord:
            self._discord.start()
            time.sleep(2)
        print(f"[StaticRunner] Running {len(self._blocks)} block(s).")
        self._running = True
        try:
            self._loop()
        finally:
            if self._discord:
                self._discord.stop()

    def _loop(self) -> None:
        while self._running:
            for block in self._blocks:
                if not self._running:
                    return
                btype = block.get("type", "click")
                if btype == "click":
                    self._do_click(block)
                elif btype == "chat_reader":
                    self._do_chat_reader(block)

    def _do_click(self, block: dict) -> None:
        cfg: dict = {
            "position": block.get("position", [0, 0]),
            "button":   block.get("button", "left"),
            "sleep":    block.get("sleep", 0.0),
        }
        wfp = block.get("wait_for_pixel")
        if wfp:
            cfg["wait_for_pixel"] = {
                "position": wfp.get("position", [0, 0]),
                "color":    wfp.get("color",    [0, 0, 0]),
                "timeout":  float(wfp.get("timeout", 10.0)),
            }
        self._click_executor.execute_mouse_clicks([cfg])

    def _do_chat_reader(self, block: dict) -> None:
        name = str(block.get("pokemon_name", "")).strip()
        if not name:
            return
        try:
            img  = self._chat_region.capture()
            text = self._ocr.extract_text(img)
        except Exception as e:
            print(f"[StaticRunner] OCR error: {e}")
            return

        if name.lower() not in text.lower():
            return

        if is_special_roaming(text, name, SPECIAL_VARIANTS):
            print(f"[StaticRunner] Special {name} — notifying + autoclicking.")
            self._notify(f"SPECIAL {name} found!")
            self._autoclick_loop()
            self._running = False
        else:
            print(f"[StaticRunner] {name} (not special) — rejoining.")
            self._notify(f"{name} found (not special).")
            open_roblox_place()

    def _notify(self, msg: str) -> None:
        if not self._discord:
            return
        try:
            pyautogui.screenshot().save(str(self._screenshot_path))
        except Exception:
            pass
        fp = str(self._screenshot_path) if self._screenshot_path.exists() else None
        self._discord.send_notification_sync(msg, file_path=fp)

    def _autoclick_loop(self) -> None:
        w, h = pyautogui.size()
        cx, cy = w // 2, h // 2
        while self._running:
            pyautogui.click(cx, cy)
            time.sleep(10.0)
