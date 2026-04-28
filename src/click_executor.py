import time
from typing import Any, Dict, Optional, Sequence, Tuple

import pyautogui

from .macro_config import ClickConfig
from .pixel_color import PixelColorService


class ClickExecutor:
    def __init__(self, pixel_service: Optional[PixelColorService] = None) -> None:
        self._pixel_service = pixel_service or PixelColorService()

    def _parse_click_config(
        self, click_config: ClickConfig
    ) -> Tuple[int, int, float, Optional[Dict[str, Any]], str]:
        if isinstance(click_config, dict):
            x, y = click_config["position"]
            return (
                int(x),
                int(y),
                float(click_config.get("sleep", 0)),
                click_config.get("wait_for_pixel"),
                click_config.get("button", "left").lower(),
            )
        if isinstance(click_config, tuple):
            parse_tuple = {
                2: lambda t: (int(t[0]), int(t[1]), 0.0, None, "left"),
                3: lambda t: (int(t[0]), int(t[1]), float(t[2]), None, "left"),
                9: lambda t: (
                    int(t[0]),
                    int(t[1]),
                    float(t[2]),
                    {
                        "position": (int(t[3]), int(t[4])),
                        "color": (int(t[5]), int(t[6]), int(t[7])),
                        "timeout": float(t[8]),
                    },
                    "left",
                ),
            }.get(len(click_config))
            if parse_tuple:
                return parse_tuple(click_config)
        raise ValueError(click_config)

    def execute_mouse_clicks(self, click_sequence: Sequence[ClickConfig]) -> None:
        click_func = lambda btn: pyautogui.rightClick if btn == "right" else pyautogui.click
        for click_config in click_sequence:
            try:
                x, y, sleep_time, pixel_check, button = self._parse_click_config(click_config)
            except ValueError as e:
                print(e)
                continue
            if pixel_check:
                pos, color = pixel_check["position"], pixel_check["color"]
                timeout = float(pixel_check.get("timeout", 10.0))
                if not self._pixel_service.wait_for_pixel_color(pos[0], pos[1], color, timeout):
                    print(pos, color)
            click_func(button)(x, y)
            if sleep_time > 0:
                time.sleep(sleep_time)
