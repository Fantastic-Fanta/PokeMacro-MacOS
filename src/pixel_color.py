import time
from dataclasses import dataclass
from typing import Tuple

import mss
import numpy as np
import pyautogui


@dataclass(frozen=True)
class PixelColorService:
    tolerance: int = 5

    def get_pixel_color(self, x: int, y: int) -> Tuple[int, int, int]:
        with mss.mss() as sct:
            monitor = {"top": y, "left": x, "width": 1, "height": 1}
            img = np.array(sct.grab(monitor))
            return (int(img[0, 0, 2]), int(img[0, 0, 1]), int(img[0, 0, 0]))

    def get_pixel_color_at_mouse(self) -> Tuple[int, int, int, int, int]:
        x, y = pyautogui.position()
        r, g, b = self.get_pixel_color(x - 2, y - 2)
        return x, y, r, g, b

    def is_pixel_white(
        self,
        x: int,
        y: int,
        target_color: Tuple[int, int, int],
        tolerance: int = 30,
    ) -> bool:
        r, g, b = self.get_pixel_color(x, y)
        target_r, target_g, target_b = target_color
        r_within = abs(r - target_r) <= tolerance
        g_within = abs(g - target_g) <= tolerance
        b_within = abs(b - target_b) <= tolerance
        return r_within and g_within and b_within

    def wait_for_pixel_color(
        self,
        x: int,
        y: int,
        target_color: Tuple[int, int, int],
        timeout: float = 10.0,
        check_interval: float = 0.1,
    ) -> bool:
        start_time = time.time()
        target_r, target_g, target_b = target_color
        within_tolerance = lambda current, target: abs(current - target) <= self.tolerance
        matches = lambda r, g, b: all(
            [within_tolerance(r, target_r), within_tolerance(g, target_g), within_tolerance(b, target_b)]
        )
        while time.time() - start_time < timeout:
            if matches(*self.get_pixel_color(x, y)):
                return True
            time.sleep(check_interval)
        return False
