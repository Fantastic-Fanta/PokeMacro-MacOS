import time
from pathlib import Path
from typing import Optional

import pyautogui

from .click_executor import ClickExecutor
from .discord_bot import DiscordBot, ConfirmationResult
from .img_funcs import (
    matches_config,
    remove_chronos_event_phrase,
    trim_text_from_username_to_attempts,
)
from .macro_config import DEFAULT_MACRO_CONFIG, MacroConfig
from .ocr_screen import OcrService, ScreenRegion
from .url_opener import open_roblox_place as rejoin


class MacroRunner:
    def __init__(
        self,
        config: MacroConfig,
        click_executor: Optional[ClickExecutor] = None,
        ocr_service: Optional[OcrService] = None,
    ) -> None:
        self._config = config
        self._click_executor = click_executor or ClickExecutor()
        self._ocr_service = ocr_service or OcrService()
        self._screen_region = ScreenRegion(
            x=config.region.x,
            y=config.region.y,
            width=config.region.width,
            height=config.region.height,
        )
        _root = Path(__file__).resolve().parent.parent
        self._log_file_path = _root / "history.log"
        self._screenshot_path = _root / "screenshot.png"
        self._ocr_text_path = _root / "ocr_text.txt"
        self._discord_bot: Optional[DiscordBot] = None
        if config.discord_bot_token and getattr(config, "discord_guild_id", 0):
            try:
                self._discord_bot = DiscordBot(
                    config.discord_bot_token,
                    config.discord_guild_id,
                )
            except Exception as e:
                print(f"[MacroRunner] Failed to initialize Discord bot: {e}")
                self._discord_bot = None

    def _matches_config(self, text: str) -> bool:
        return matches_config(
            text,
            self._config.username,
            self._config.reskins,
            self._config.gradients,
            self._config.is_reskin,
            self._config.is_shiny,
            self._config.is_gradient,
            self._config.is_any,
            self._config.is_good,
        )

    def run(self) -> None:
        if self._discord_bot:
            print("[MacroRunner] Starting Discord bot...")
            self._discord_bot.start()
            time.sleep(2)
        try:
            time.sleep(self._config.initial_delay_seconds)
            while True:
                self._click_executor.execute_mouse_clicks(self._config.click_sequence)
                time.sleep(self._config.post_click_delay_seconds)
                image = self._screen_region.capture(save_path=str(self._screenshot_path))
                text = trim_text_from_username_to_attempts(
                    remove_chronos_event_phrase(self._ocr_service.extract_text(image)),
                    self._config.username,
                )
                self._ocr_text_path.write_text(text, encoding="utf-8")
                is_match = self._matches_config(text)
                if not is_match and self._config.username.lower() in text.lower():
                    self._log_username_detection(text)
                if is_match:
                    should_continue = self._handle_match_found()
                    if not should_continue:
                        break
                self._handle_no_match()
                time.sleep(self._config.between_iterations_delay_seconds)
        finally:
            if self._discord_bot:
                print("[MacroRunner] Stopping Discord bot...")
                self._discord_bot.stop()

    def _handle_match_found(self) -> bool:
        positions = self._config.positions
        if self._discord_bot:
            image = self._screen_region.capture(save_path=str(self._screenshot_path))
            text = trim_text_from_username_to_attempts(
                remove_chronos_event_phrase(self._ocr_service.extract_text(image)),
                self._config.username,
            )
            confirmation_message = f"```\n{text}\n```"
            print("[MacroRunner] Waiting for user confirmation...")
            result = self._discord_bot.send_confirmation_sync(
                confirmation_message,
                timeout_seconds=60.0,
                file_path=str(self._screenshot_path),
            )
            if result == ConfirmationResult.ROLL:
                print("[MacroRunner] User chose to ROLL - ignoring match and continuing...")
                return True
            elif result == ConfirmationResult.TIMEOUT:
                print("[MacroRunner] Confirmation timeout - automatically keeping match...")
            else:
                print("[MacroRunner] User chose to KEEP - proceeding with match...")
        for _ in range(3):
            pyautogui.click(*positions.dialogue_yes)
            time.sleep(0.2)
        pyautogui.click(*positions.menu_button)
        time.sleep(2)
        pyautogui.click(*positions.save_button)
        time.sleep(2)
        pyautogui.click(*positions.dialogue_yes)
        return False

    def _handle_no_match(self) -> None:
        if self._config.mode in ("fast", "quick rejoin"):
            pyautogui.write("//qre", interval=0.02)
            pyautogui.press("enter")
        else:
            rejoin()

    def _log_username_detection(self, text: str) -> None:
        with open(self._log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"{text}\n{'=' * 80}\n")
        if self._discord_bot:
            try:
                self._discord_bot.send_log_embed_sync(f"```\n{text}\n```")
            except Exception as e:
                print(f"[MacroRunner] Failed to send log via Discord bot: {e}")
