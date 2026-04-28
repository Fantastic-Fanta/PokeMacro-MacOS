import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import pyautogui
import yaml

ClickDict = Dict[str, Any]
ClickTuple = Union[
    Tuple[int, int],
    Tuple[int, int, float],
    Tuple[int, int, float, int, int, int, int, int, float],
]
ClickConfig = Union[ClickDict, ClickTuple]


@dataclass(frozen=True)
class RegionConfig:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class PositionsConfig:
    egg_man_position: Tuple[int, int]
    event_button: Tuple[int, int]
    dialogue_yes: Tuple[int, int]
    menu_button: Tuple[int, int]
    quick_rejoin_sprite: Tuple[int, int]
    quick_rejoin_button: Tuple[int, int]
    save_button: Tuple[int, int]
    savefile_card: Tuple[int, int]
    loadingscreen_yellow: Tuple[int, int]


def get_config_path() -> Path:
    if getattr(sys, "frozen", False):
        try:
            exe_path = Path(sys.executable).resolve()
            if exe_path.is_file():
                exe_dir = exe_path.parent
                config_path = exe_dir / "configs.yaml"
                if config_path.exists():
                    return config_path
                return config_path
        except Exception:
            pass
        return Path.cwd() / "configs.yaml"
    return Path(__file__).resolve().parent.parent / "configs.yaml"


def _load_config_from_yaml() -> Dict[str, Any]:
    config_path = get_config_path()
    if not config_path.exists():
        print(f"[ERROR] configs.yaml not found at {config_path}")
        print("[ERROR] Please create configs.yaml in the same directory as the executable")
        print("[ERROR] (or project root in development mode)")
        return {}
    try:
        print(f"[INFO] Loading configuration from: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            if config:
                print("[INFO] Configuration loaded successfully")
            return config
    except Exception as e:
        print(f"[ERROR] Could not load config from {config_path}: {e}")
        return {}


_config = _load_config_from_yaml()


def get_config_dict() -> Dict[str, Any]:
    return _config


_wishlist = _config.get("Wishlist", {})
RESKINS = _wishlist.get("Reskins", ["Whiteout", "Phantom", "Glitch"])
GRADIENTS = _wishlist.get("Gradients", ["Chronos", "Helios", "Gaia", "Nereus", "Nyx", "Frostbite", "Winter"])
USERNAME = _config.get("Username", "Manta")
DISCORD_BOT_TOKEN = _config.get("DiscordBotToken", "")
DISCORD_CHANNEL_ID = _config.get("DiscordChannelId", 0)
DISCORD_GUILD_ID = _config.get("ServerID", 0)
IS_RESKIN = _config.get("IsReskin", False)
IS_SHINY = _config.get("IsShiny", False)
IS_GRADIENT = _config.get("IsGradient", False)
IS_ANY = _config.get("IsAny", True)
IS_GOOD = _config.get("IsGood", False)
# "URL Open" = full click sequence; "Quick rejoin" = skip first 3 steps and use //qre instead of URL rejoin
MODE = str(_config.get("Mode", "URL Open")).strip().lower()


_raw_mode = str(_config.get("HuntingMode", "Egg Resetter")).strip().lower()
HUNTING_MODE = "roam" if _raw_mode in ("roam", "roaming", "roamhunter", "roaming hunter") else "egg"


@dataclass
class MacroConfig:
    region: RegionConfig
    click_sequence: Sequence[ClickConfig]
    positions: PositionsConfig
    username: str = USERNAME
    reskins: Optional[Sequence[str]] = None
    gradients: Optional[Sequence[str]] = None
    is_reskin: bool = IS_RESKIN
    is_shiny: bool = IS_SHINY
    is_gradient: bool = IS_GRADIENT
    is_any: bool = IS_ANY
    is_good: bool = IS_GOOD
    mode: str = MODE
    initial_delay_seconds: float = 3.0
    post_click_delay_seconds: float = 0.0
    between_iterations_delay_seconds: float = 3.0
    discord_bot_token: str = DISCORD_BOT_TOKEN
    discord_channel_id: int = DISCORD_CHANNEL_ID
    discord_guild_id: int = DISCORD_GUILD_ID

    def __post_init__(self) -> None:
        self.reskins = self.reskins or RESKINS
        self.gradients = self.gradients or GRADIENTS


def _to_tuple(value: Any) -> Tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (int(value[0]), int(value[1]))
    raise ValueError(value)


def _load_positions_from_yaml() -> PositionsConfig:
    positions_yaml = _config.get("Positions", {})
    get_pos = lambda key, default: _to_tuple(positions_yaml.get(key, default))
    return PositionsConfig(
        egg_man_position=get_pos("EggManPosition", []),
        event_button=get_pos("EventButton", []),
        dialogue_yes=get_pos("DialogueYES", []),
        menu_button=get_pos("MenuButton", []),
        quick_rejoin_sprite=get_pos("QuickRejoinSprite", []),
        quick_rejoin_button=get_pos("QuickRejoinButton", []),
        save_button=get_pos("SaveButton", []),
        savefile_card=get_pos("SaveFileCard", []),
        loadingscreen_yellow=get_pos("LoadingScreenYellow", []),
    )


def _load_region_from_yaml() -> RegionConfig:
    chat_window_yaml = _config.get("ChatWindow", {})
    left_corner = _to_tuple(chat_window_yaml.get("LeftCorner", [13, 136]))
    right_corner = _to_tuple(chat_window_yaml.get("RightCorner", [440, 354]))
    return RegionConfig(
        x=left_corner[0],
        y=left_corner[1],
        width=right_corner[0] - left_corner[0],
        height=right_corner[1] - left_corner[1],
    )


def _get_screen_center() -> Tuple[int, int]:
    size = pyautogui.size()
    return (size.width // 2, size.height // 2)


def _create_default_click_sequence(
    positions: PositionsConfig,
    screen_center: Tuple[int, int],
    chat_window_center: Tuple[int, int],
) -> Sequence[ClickConfig]:
    return [
        {
            "position": screen_center,
            "sleep": 1.0,
            "wait_for_pixel": {
                "position": positions.loadingscreen_yellow,
                "color": (249, 239, 146),
                "timeout": 20.0,
            },
        },
        {
            "position": (screen_center[0], screen_center[1] // 6),
            "sleep": 0.02,
        },
        {
            "position": (screen_center[0], screen_center[1] // 6 + 20),
            "sleep": 0.1,
        },
        {
            "position": screen_center,
            "sleep": 1,
            "wait_for_pixel": {
                "position": positions.savefile_card,
                "color": (146, 252, 207),
                "timeout": 10.0,
            },
        },
        {
            "position": screen_center,
            "sleep": 0.1,
        },
        {
            "position": positions.egg_man_position,
            "sleep": 0.3,
            "wait_for_pixel": {
                "position": positions.menu_button,
                "color": (255, 255, 255),
                "timeout": 10.0,
            },
        },
        {
            "position": positions.egg_man_position,
            "sleep": 0.05,
            "button": "left",
        },
        {
            "position": chat_window_center,
            "sleep": 0.3,
            "button": "right",
        },
    ]


DEFAULT_POSITIONS = _load_positions_from_yaml()
DEFAULT_REGION = _load_region_from_yaml()
SCREEN_CENTER = _get_screen_center()
_chat_center = (DEFAULT_REGION.x + DEFAULT_REGION.width // 2, DEFAULT_REGION.y + DEFAULT_REGION.height // 2)
DEFAULT_CLICK_SEQUENCE = _create_default_click_sequence(DEFAULT_POSITIONS, SCREEN_CENTER, _chat_center)
# Fast: drop first 3 click steps (loading + two top-screen taps before savefile wait)
_effective_clicks = (
    DEFAULT_CLICK_SEQUENCE[5:] if MODE in ("fast", "quick rejoin") else DEFAULT_CLICK_SEQUENCE
)

DEFAULT_MACRO_CONFIG = MacroConfig(
    region=DEFAULT_REGION,
    click_sequence=_effective_clicks,
    positions=DEFAULT_POSITIONS,
    username=USERNAME,
    reskins=RESKINS,
    gradients=GRADIENTS,
    is_reskin=IS_RESKIN,
    is_shiny=IS_SHINY,
    is_gradient=IS_GRADIENT,
    is_any=IS_ANY,
    is_good=IS_GOOD,
    discord_bot_token=DISCORD_BOT_TOKEN,
    discord_channel_id=DISCORD_CHANNEL_ID,
    discord_guild_id=DISCORD_GUILD_ID,
)
