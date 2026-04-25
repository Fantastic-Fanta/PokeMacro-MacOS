import subprocess
import time
from pathlib import Path

import pyautogui

from .debug_hook import is_debug_webhook, send_debug_log
from .discord_webhook import send_discord_webhook
from .hunter_config import CONFIG_FILE_PATH, DEFAULT_HUNTER_CONFIG, HunterConfig
from .ocr_screen import OcrService, ScreenRegion
from .pixel_color import PixelColorService
from .roam_text import (
    capture_full_screen_to_file,
    capture_sprite_region_to_file,
    is_special_roaming,
    is_text_in_wishlist,
)


class HunterRunner:
    def __init__(self, config: HunterConfig = DEFAULT_HUNTER_CONFIG) -> None:
        self._config = config
        self._pixel_service = PixelColorService()
        self._ocr_service = OcrService()
        self._ocr_region = ScreenRegion(
            x=config.ocr_region_x,
            y=config.ocr_region_y,
            width=config.ocr_region_width,
            height=config.ocr_region_height,
        )
        self._chat_region = ScreenRegion(
            x=config.chat_region_x,
            y=config.chat_region_y,
            width=config.chat_region_width,
            height=config.chat_region_height,
        )
        self._running = False
        self._project_dir = Path(__file__).resolve().parent.parent
        self._screenshot_path = self._project_dir / "roaming_sprite_screenshot.png"
        self._debug_full_screen_path = self._project_dir / "debug_full_screen.png"
        self._config_path = Path(CONFIG_FILE_PATH) if CONFIG_FILE_PATH else (self._project_dir / "configs.yaml")
        self._log_path = self._project_dir / "hunting_history.log"

    def _log_find(self, ocr_text: str) -> None:
        line = f"{ocr_text}\n"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def _is_white_pixel_detected(self) -> bool:
        return self._pixel_service.is_pixel_white(
            self._config.white_pixel_x,
            self._config.white_pixel_y,
            self._config.white_color,
            self._config.white_tolerance,
        )

    def _send_sprite_to_discord(self, ocr_text: str, is_special: bool = False) -> None:
        capture_sprite_region_to_file(
            self._config.sprite_region_left,
            self._config.sprite_region_top,
            self._config.sprite_region_width,
            self._config.sprite_region_height,
            str(self._screenshot_path),
        )
        if is_debug_webhook(self._config.discord_webhook):
            capture_full_screen_to_file(str(self._debug_full_screen_path))
        if not self._config.discord_webhook or not self._config.discord_webhook.strip():
            return
        msg = "Something tuff appeared!!!" if is_special else f"Roaming found (OCR: {ocr_text})"
        send_discord_webhook(
            self._config.discord_webhook,
            msg,
            file_path=str(self._screenshot_path) if self._screenshot_path.exists() else None,
        )

    def _send_debug_log(
        self,
        encounter_image,
        encounter_ocr_text: str,
        chat_image,
        chat_ocr_text: str,
    ) -> None:
        if not is_debug_webhook(self._config.discord_webhook):
            return
        full_screen = str(self._debug_full_screen_path) if self._debug_full_screen_path.exists() else None
        send_debug_log(
            self._config.discord_webhook,
            encounter_ocr_text=encounter_ocr_text,
            encounter_image=encounter_image,
            chat_ocr_text=chat_ocr_text,
            chat_image=chat_image,
            full_screen_path=full_screen or "",
            config_path=str(self._config_path),
        )

    def _is_roblox_focused(self) -> bool:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout:
            return "roblox" in result.stdout.strip().lower()
        return False

    def _check_autostop(self) -> None:
        if not self._is_roblox_focused():
            self._running = False

    def _hold_key(self, key: str, duration: float) -> bool:
        start_time = time.time()
        pyautogui.keyDown(key)
        try:
            while time.time() - start_time < duration:
                self._check_autostop()
                if not self._running:
                    return False
                if self._is_white_pixel_detected():
                    pyautogui.keyUp(key)
                    self._handle_white_pixel_detection()
                    return True
                time.sleep(self._config.pixel_check_interval)
            return False
        finally:
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass

    def _handle_white_pixel_detection(self) -> None:
        time.sleep(1.0)
        encounter_image = self._ocr_region.capture()
        text = self._ocr_service.extract_text(encounter_image, psm=8)
        self._log_find(text)
        if not is_text_in_wishlist(text, self._config.wishlist_items):
            pyautogui.click(self._config.skip_click_x, self._config.skip_click_y)
            time.sleep(0.3)
            return
        chat_center_x = self._config.chat_region_x + self._config.chat_region_width // 2
        chat_center_y = self._config.chat_region_y + self._config.chat_region_height // 2
        pyautogui.click(chat_center_x, chat_center_y)
        time.sleep(0.2)
        chat_image = self._chat_region.capture()
        chat_text = self._ocr_service.extract_text(chat_image)
        if is_special_roaming(
            chat_text,
            text,
            self._config.special_variants,
            self._config.wishlist_items,
        ):
            self._send_sprite_to_discord(text, is_special=True)
            self._send_debug_log(encounter_image, text, chat_image, chat_text)
            self._handle_special_roaming()
            self._running = False
            return
        self._send_sprite_to_discord(text, is_special=False)
        self._send_debug_log(encounter_image, text, chat_image, chat_text)
        pyautogui.click(self._config.skip_click_x, self._config.skip_click_y)
        time.sleep(3.0)
        return

    def _handle_special_roaming(self) -> None:
        center_x, center_y = pyautogui.size()[0] // 2, pyautogui.size()[1] // 2
        interval = self._config.special_click_interval_seconds
        while self._running:
            self._check_autostop()
            if not self._running:
                break
            pyautogui.click(center_x, center_y)
            time.sleep(interval)

    def run(self) -> None:
        time.sleep(self._config.initial_delay_seconds)
        self._running = True
        try:
            while self._running:
                self._check_autostop()
                if self._running:
                    self._hold_key("a", self._config.key_hold_duration_seconds)
                if self._running:
                    self._hold_key("d", self._config.key_hold_duration_seconds)
        finally:
            try:
                pyautogui.keyUp("a")
            except Exception:
                pass
            try:
                pyautogui.keyUp("d")
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
