from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pyautogui

from .click_executor import ClickExecutor
from .discord_bot import ConfirmationResult, DiscordBot
from .hunter_config import CHAT_REGION
from .img_funcs import matches_chat_config, trim_text_from_username_to_pokemon
from .macro_config import (
    DEFAULT_POSITIONS,
    DISCORD_BOT_TOKEN,
    DISCORD_GUILD_ID,
    GRADIENTS,
    IS_ANY,
    IS_GOOD,
    IS_GRADIENT,
    IS_RESKIN,
    IS_SHINY,
    MODE,
    RESKINS,
    SCREEN_CENTER,
    USERNAME,
    get_config_dict,
)
from .ocr_screen import OcrService, ScreenRegion
from .url_opener import open_roblox_place

_sc = SCREEN_CENTER
_pos = DEFAULT_POSITIONS

_URL_OPEN_PREAMBLE_CLICKS = [
    {
        "position": _sc,
        "sleep": 1.0,
        "wait_for_pixel": {
            "position": _pos.loadingscreen_yellow,
            "color": (249, 239, 146),
            "timeout": 20.0,
        },
    },
    {
        "position": (_sc[0], _sc[1] // 6),
        "sleep": 0.02,
    },
    {
        "position": (_sc[0], _sc[1] // 6 + 20),
        "sleep": 0.1,
    },
    {
        "position": _sc,
        "sleep": 1.0,
        "wait_for_pixel": {
            "position": _pos.savefile_card,
            "color": (146, 252, 207),
            "timeout": 10.0,
        },
    },
    {
        "position": _sc,
        "sleep": 0.1,
    },
]

_URL_OPEN_PREAMBLE_WAIT = {
    "sleep": 0.3,
    "wait_for_pixel": {
        "position": _pos.menu_button,
        "color": (255, 255, 255),
        "timeout": 10.0,
    },
}


class StaticRunner:
    """Execute a user-defined sequence of Statics blocks in a loop."""

    def __init__(self) -> None:
        c = get_config_dict()
        self._blocks: list[dict] = c.get("Statics") or []
        self._click_executor = ClickExecutor()
        self._use_url_open_preamble = MODE == "url open"
        self._ocr = OcrService()
        cx, cy, cw, ch = CHAT_REGION
        self._chat_region = ScreenRegion(x=cx, y=cy, width=cw, height=ch)
        _root = Path(__file__).resolve().parent.parent
        self._screenshot_path = _root / "screenshot.png"
        self._ocr_text_path   = _root / "ocr_text.txt"
        self._username = USERNAME
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
            if self._use_url_open_preamble:
                self._click_executor.execute_mouse_clicks(_URL_OPEN_PREAMBLE_CLICKS)
                self._do_wait(_URL_OPEN_PREAMBLE_WAIT)
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

    def _do_wait(self, step: dict) -> None:
        wfp = step.get("wait_for_pixel")
        if wfp:
            pos, color = wfp["position"], wfp["color"]
            timeout = float(wfp.get("timeout", 10.0))
            self._click_executor._pixel_service.wait_for_pixel_color(
                pos[0], pos[1], color, timeout
            )
        sleep_time = float(step.get("sleep", 0.0))
        if sleep_time > 0:
            time.sleep(sleep_time)

    def _do_chat_reader(self, block: dict) -> None:
        name = str(block.get("pokemon_name", "")).strip()
        if not name:
            return

        # 1. Click chat midpoint to focus the window before capturing
        cx = self._chat_region.x + self._chat_region.width // 2
        cy = self._chat_region.y + self._chat_region.height // 2
        pyautogui.click(cx, cy)
        time.sleep(0.3)

        # 2. OCR the chat region; write debug files for the Debug tab
        try:
            img  = self._chat_region.capture(save_path=str(self._screenshot_path))
            text = self._ocr.extract_text(img)
            self._ocr_text_path.write_text(text, encoding="utf-8")
        except Exception as e:
            print(f"[StaticRunner] OCR error: {e}")
            return

        # 3. Username must appear in chat — otherwise nothing happened, rejoin
        if self._username.lower() not in text.lower():
            print(f"[StaticRunner] '{self._username}' not in chat — rejoining.")
            open_roblox_place()
            return

        # 4. Trim to the segment {username} … {pokemon}
        segment = trim_text_from_username_to_pokemon(text, self._username, name)
        print(f"[StaticRunner] Chat segment: {segment!r}")

        # 5. Apply egg-resetter filter flags to decide whether to keep
        if matches_chat_config(
            segment,
            reskins=RESKINS,
            gradients=GRADIENTS,
            is_reskin=IS_RESKIN,
            is_shiny=IS_SHINY,
            is_gradient=IS_GRADIENT,
            is_any=IS_ANY,
            is_good=IS_GOOD,
        ):
            print(f"[StaticRunner] Variant match in '{segment}' — awaiting confirmation.")
            result = self._confirm_match(segment)
            if result == ConfirmationResult.ROLL:
                print("[StaticRunner] User chose to ROLL — rejoining.")
                open_roblox_place()
            else:
                if result == ConfirmationResult.TIMEOUT:
                    print("[StaticRunner] Confirmation timeout — automatically keeping match.")
                else:
                    print("[StaticRunner] User chose to KEEP — autoclicking.")
                self._autoclick_loop()
                self._running = False
        else:
            print(f"[StaticRunner] No variant match — rejoining.")
            if self._discord:
                try:
                    self._discord.send_static_log_embed_sync(f"```\n{segment}\n```")
                except Exception as e:
                    print(f"[StaticRunner] Discord log failed: {e}")
            open_roblox_place()

    def _confirm_match(self, segment: str) -> ConfirmationResult:
        if not self._discord:
            return ConfirmationResult.KEEP
        fp = str(self._screenshot_path) if self._screenshot_path.exists() else None
        return self._discord.send_static_confirmation_sync(
            f"```\n{segment}\n```",
            timeout_seconds=60.0,
            file_path=fp,
        )

    def _autoclick_loop(self) -> None:
        w, h = pyautogui.size()
        cx, cy = w // 2, h // 2
        while self._running:
            pyautogui.click(cx, cy)
            time.sleep(10.0)
