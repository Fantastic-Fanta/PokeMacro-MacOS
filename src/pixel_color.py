import time
from dataclasses import dataclass
from typing import Tuple

import mss
import numpy as np


@dataclass(frozen=True)
class PixelColorService:
    tolerance: int = 5

    @staticmethod
    def _grab(sct: mss.base.MSSBase, x: int, y: int) -> Tuple[int, int, int]:
        img = np.array(sct.grab({"top": y, "left": x, "width": 1, "height": 1}))
        return (int(img[0, 0, 2]), int(img[0, 0, 1]), int(img[0, 0, 0]))

    def get_pixel_color(self, x: int, y: int) -> Tuple[int, int, int]:
        with mss.mss() as sct:
            return self._grab(sct, x, y)

    def is_pixel_white(self, x: int, y: int, target_color: Tuple[int, int, int], tolerance: int = 30) -> bool:
        r, g, b = self.get_pixel_color(x, y)
        tr, tg, tb = target_color
        return abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance

    def wait_for_pixel_color(
        self,
        x: int,
        y: int,
        target_color: Tuple[int, int, int],
        timeout: float = 10.0,
        check_interval: float = 0.1,
    ) -> bool:
        deadline = time.time() + timeout
        tr, tg, tb = target_color
        with mss.mss() as sct:
            while time.time() < deadline:
                r, g, b = self._grab(sct, x, y)
                if abs(r - tr) <= self.tolerance and abs(g - tg) <= self.tolerance and abs(b - tb) <= self.tolerance:
                    return True
                time.sleep(check_interval)
        return False
