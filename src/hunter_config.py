from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .macro_config import get_config_dict, get_config_path


def _to_tuple(value, default: Tuple[int, int] = (0, 0)) -> Tuple[int, int]:
    if not value:
        return default
    return (int(value[0]), int(value[1]))


def _region_from_corners(
    left_corner,
    right_corner,
    default: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    left = _to_tuple(left_corner, (default[0], default[1]))
    right = _to_tuple(right_corner, (default[0] + default[2], default[1] + default[3]))
    x, y = left[0], left[1]
    w = max(0, right[0] - left[0])
    h = max(0, right[1] - left[1])
    return (x, y, w, h)


_config = get_config_dict()
_wishlist = _config.get("Wishlist", {})

_chat_window = _config.get("ChatWindow", {})
_encounter_region = _config.get("EncounterNameRegion", {})
_sprite_region = _config.get("SpriteRegion", {})
_positions = _config.get("Positions", {})

_run_btn = _to_tuple(_positions.get("RunButton"), (0, 0))
_pokeball = _to_tuple(_positions.get("Pokeball"), (0, 0))

POKEMONS = _wishlist.get("Roamings", [])

SPECIAL_VARIANTS = [v for v in _wishlist.get("Special", []) if v]
WISHLIST_ITEMS = [item.lower() for item in POKEMONS]

CHAT_REGION = _region_from_corners(
    _chat_window.get("LeftCorner"),
    _chat_window.get("RightCorner"),
    (0, 0, 0, 0),
)

ENCOUNTER_NAME_REGION = _region_from_corners(
    _encounter_region.get("LeftCorner"),
    _encounter_region.get("RightCorner"),
    (0, 0, 0, 0),
)

SPRITE_REGION = _region_from_corners(
    _sprite_region.get("LeftCorner"),
    _sprite_region.get("RightCorner"),
    (0, 0, 0, 0),
)

POKEBALL_TOLERANCE = int(_positions.get("PokeballTolerance", 30))
DISCORD_WEBHOOK = _config.get("DiscordWebhook", "")
USERNAME = _config.get("Username", "")

try:
    _pc = _positions.get("PokeballColor")
    POKEBALL_COLOR = (int(_pc[0]), int(_pc[1]), int(_pc[2]))
except Exception:
    POKEBALL_COLOR = (255, 255, 255)

CONFIG_FILE_PATH = get_config_path()


@dataclass(frozen=True)
class HunterConfig:
    white_pixel_x: int = 0
    white_pixel_y: int = 0
    white_color: Tuple[int, int, int] = (255, 255, 255)
    white_tolerance: int = 1

    ocr_region_x: int = 0
    ocr_region_y: int = 0
    ocr_region_width: int = 0
    ocr_region_height: int = 0

    chat_region_x: int = 0
    chat_region_y: int = 0
    chat_region_width: int = 0
    chat_region_height: int = 0

    skip_click_x: int = 0
    skip_click_y: int = 0

    sprite_region_left: int = 0
    sprite_region_top: int = 0
    sprite_region_width: int = 0
    sprite_region_height: int = 0

    key_hold_duration_seconds: float = 0.2
    pixel_check_interval: float = 0.1
    initial_delay_seconds: float = 3.0
    special_click_interval_seconds: float = 10.0

    username: str = ""
    discord_webhook: str = ""
    wishlist_items: Optional[List[str]] = field(default=None)
    special_variants: Optional[List[str]] = field(default=None)

    def __post_init__(self) -> None:
        if self.wishlist_items is None:
            object.__setattr__(self, "wishlist_items", WISHLIST_ITEMS)
        if self.special_variants is None:
            object.__setattr__(self, "special_variants", [v.lower() for v in SPECIAL_VARIANTS])
        if self.discord_webhook == "":
            object.__setattr__(self, "discord_webhook", DISCORD_WEBHOOK or "")
        object.__setattr__(self, "username", USERNAME)
        cx, cy, cw, ch = CHAT_REGION
        object.__setattr__(self, "chat_region_x", cx)
        object.__setattr__(self, "chat_region_y", cy)
        object.__setattr__(self, "chat_region_width", cw)
        object.__setattr__(self, "chat_region_height", ch)
        ex, ey, ew, eh = ENCOUNTER_NAME_REGION
        object.__setattr__(self, "ocr_region_x", ex)
        object.__setattr__(self, "ocr_region_y", ey)
        object.__setattr__(self, "ocr_region_width", ew)
        object.__setattr__(self, "ocr_region_height", eh)
        sx, sy, sw, sh = SPRITE_REGION
        object.__setattr__(self, "sprite_region_left", sx)
        object.__setattr__(self, "sprite_region_top", sy)
        object.__setattr__(self, "sprite_region_width", sw)
        object.__setattr__(self, "sprite_region_height", sh)
        object.__setattr__(self, "skip_click_x", _run_btn[0])
        object.__setattr__(self, "skip_click_y", _run_btn[1])
        object.__setattr__(self, "white_pixel_x", _pokeball[0])
        object.__setattr__(self, "white_pixel_y", _pokeball[1])
        object.__setattr__(self, "white_color", POKEBALL_COLOR)
        object.__setattr__(self, "white_tolerance", POKEBALL_TOLERANCE)


DEFAULT_HUNTER_CONFIG = HunterConfig()
