"""Dex grid scanner: finds cells without the red marker by sampling a small region per cell."""
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image, ImageDraw, ImageFont

_DEX_SCANNER_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _DEX_SCANNER_DIR / "data"
DEFAULT_POKEMONS_CSV = DEFAULT_DATA_DIR / "pokemons.csv"
DEFAULT_OBTAINMENTS_TXT = DEFAULT_DATA_DIR / "obtainments.txt"
DEFAULT_EVO_LINE_TXT = DEFAULT_DATA_DIR / "evo_line.txt"
DEFAULT_SPECIAL_OBTAINMENTS_TXT = DEFAULT_DATA_DIR / "special_obtainments.txt"
DEFAULT_ROULETTE_ONLY_TXT = DEFAULT_DATA_DIR / "roulette_only.txt"
DEFAULT_RAIDS_TXT = DEFAULT_DATA_DIR / "raids.txt"
DEFAULT_UNOB_TXT = DEFAULT_DATA_DIR / "unob.txt"


@dataclass
class DexScannerConfig:
    """Configurable grid and sampling parameters for the dex scanner. Grid uses full image dimensions."""

    rows: int
    cols: int
    sample_offset: Tuple[int, int] = (10, 10)  # (dx, dy) from top-left of each cell
    output_file: str = "missing-poopimons.txt"
    red_min_r: int = 120  # minimum R channel for red
    red_dominance: int = 25  # R must exceed G and B by at least this much (tolerance)
    white_min: int = 200  # R,G,B all >= this to consider pixel white (marker highlight)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DexScannerConfig":
        """Build config from a dict (e.g. configs.yaml DexScanner section)."""
        offset = d.get("SampleOffset", [10, 10])
        return cls(
            rows=int(d.get("Rows", 23)),
            cols=int(d.get("Cols", 33)),
            sample_offset=(int(offset[0]), int(offset[1])),
            output_file=str(d.get("OutputFile", "missing-poopimons.txt")),
            red_min_r=int(d.get("RedMinR", 120)),
            red_dominance=int(d.get("RedDominance", 25)),
            white_min=int(d.get("WhiteMin", 200)),
        )


def _is_red(r: int, g: int, b: int, config: DexScannerConfig) -> bool:
    """
    Treat pixel as red if R is clearly the dominant channel (marker color).
    Uses red-dominant logic so darker reds and anti-aliased pixels are detected.
    """
    if r < config.red_min_r:
        return False
    # Red must dominate over G and B (handles dark red, bright red, slight blending)
    if r <= g or r <= b:
        return False
    # Clearly red: R sufficiently above both G and B (avoid pink/gray)
    return (r - g) >= config.red_dominance and (r - b) >= config.red_dominance


def _is_white(r: int, g: int, b: int, config: DexScannerConfig) -> bool:
    """Treat pixel as white if R, G, B are all at or above white_min (marker highlight)."""
    return r >= config.white_min and g >= config.white_min and b >= config.white_min


def _get_cell_top_left(
    width: int,
    height: int,
    config: DexScannerConfig,
    row: int,
    col: int,
) -> Tuple[int, int]:
    """Return (x, y) of the top-left corner of the cell at (row, col). Grid spans full image (0,0) to (width, height)."""
    cell_w = width / config.cols
    cell_h = height / config.rows
    x = int(col * cell_w)
    y = int(row * cell_h)
    return x, y


def _get_cell_rect(
    width: int,
    height: int,
    config: DexScannerConfig,
    row: int,
    col: int,
) -> Tuple[int, int, int, int]:
    """Return (x1, y1, x2, y2) bounding box of the cell at (row, col)."""
    x1, y1 = _get_cell_top_left(width, height, config, row, col)
    x2 = int((col + 1) * (width / config.cols))
    y2 = int((row + 1) * (height / config.rows))
    return x1, y1, x2, y2


def _sample_pixel(image: Image.Image, x: int, y: int) -> Tuple[int, int, int]:
    """Get RGB at (x, y); handle RGBA by dropping alpha."""
    w, h = image.size
    if x < 0 or x >= w or y < 0 or y >= h:
        return 0, 0, 0
    px = image.getpixel((x, y))
    if len(px) >= 3:
        return (px[0], px[1], px[2])
    return (px[0], px[0], px[0])


SAMPLE_SIZE = 12  # scan a SAMPLE_SIZE x SAMPLE_SIZE square per cell


def _get_sample_region(
    width: int,
    height: int,
    config: DexScannerConfig,
    row: int,
    col: int,
) -> Tuple[int, int, int, int]:
    """Return (x_start, y_start, x_end, y_end) of the sample region (offset + 6x6) for the cell."""
    cx, cy = _get_cell_top_left(width, height, config, row, col)
    dx, dy = config.sample_offset
    sx, sy = cx + dx, cy + dy
    return sx, sy, sx + SAMPLE_SIZE, sy + SAMPLE_SIZE


def _cell_has_red(image: Image.Image, config: DexScannerConfig, row: int, col: int) -> bool:
    """True if any pixel in the cell's sample region is red."""
    width, height = image.size
    x1, y1, x2, y2 = _get_sample_region(width, height, config, row, col)
    for py in range(y1, y2):
        for px in range(x1, x2):
            r, g, b = _sample_pixel(image, px, py)
            if _is_red(r, g, b, config):
                return True
    return False


def _cell_has_white(image: Image.Image, config: DexScannerConfig, row: int, col: int) -> bool:
    """True if any pixel in the cell's sample region is white."""
    width, height = image.size
    x1, y1, x2, y2 = _get_sample_region(width, height, config, row, col)
    for py in range(y1, y2):
        for px in range(x1, x2):
            r, g, b = _sample_pixel(image, px, py)
            if _is_white(r, g, b, config):
                return True
    return False


def _get_checked_pixels(image: Image.Image, config: DexScannerConfig) -> List[Tuple[int, int]]:
    """Return (x, y) of every pixel that is sampled during the scan (all pixels in each 6x6 region)."""
    width, height = image.size
    points: List[Tuple[int, int]] = []
    for row in range(config.rows):
        for col in range(config.cols):
            x1, y1, x2, y2 = _get_sample_region(width, height, config, row, col)
            for py in range(y1, y2):
                for px in range(x1, x2):
                    points.append((px, py))
    return points


def scan_image(image: Image.Image, config: DexScannerConfig) -> List[int]:
    """
    Scan the grid on `image` and return list of cell indices where neither red nor white
    is present in the sample region (mark as missing only when both are absent).
    Grid uses full image dimensions. Index is row-major: index = row * cols + col (0-based).
    """
    width, height = image.size
    missing: List[int] = []
    for row in range(config.rows):
        for col in range(config.cols):
            has_red = _cell_has_red(image, config, row, col)
            has_white = _cell_has_white(image, config, row, col)
            if not has_red and not has_white:
                idx = row * config.cols + col
                missing.append(idx)
    return missing


BLUE = (0, 0, 255)
OUTLINE_COLOR = (0, 255, 0)  # green for cell outlines


def create_debug_image(
    image: Image.Image,
    config: DexScannerConfig,
    output_path: str | Path,
) -> None:
    """
    Write a copy of the image with every checked pixel in the 6x6 sample regions highlighted in blue,
    each cell drawn as a square outline, and each box labeled with its index.
    """
    copy = image.convert("RGB").copy()
    w, h = copy.size
    draw = ImageDraw.Draw(copy)

    _font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    font = ImageFont.load_default()
    size = max(8, min(w, h) // 60)
    for path in _font_paths:
        try:
            font = ImageFont.truetype(path, size=size)
            break
        except (OSError, IOError):
            continue

    for px, py in _get_checked_pixels(image, config):
        if 0 <= px < w and 0 <= py < h:
            copy.putpixel((px, py), BLUE)

    for row in range(config.rows):
        for col in range(config.cols):
            x1, y1, x2, y2 = _get_cell_rect(w, h, config, row, col)
            draw.rectangle([x1, y1, x2 - 1, y2 - 1], outline=OUTLINE_COLOR, width=1)
            idx = row * config.cols + col
            draw.text((x1 + 2, y1 + 2), str(idx), fill=OUTLINE_COLOR, font=font)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    copy.save(output_path)


def _load_pokemon_names(csv_path: Path) -> Dict[int, str]:
    """Load 1-based pokemon number -> name from pokemons.csv (first occurrence per No.)."""
    names: Dict[int, str] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                no = int(row["No."])
                if no not in names:
                    names[no] = row.get("Name", "").strip() or f"#{no}"
            except (ValueError, KeyError):
                continue
    return names


# obtainments.txt: ## Location, **Method**, then "PokemonName [X.X%]" lines
_OBTAINMENT_LINE_RE = re.compile(r"^(.+?)\s*\[(\d+(?:\.\d+)?)%\]")


def _load_obtainments(txt_path: Path) -> Dict[str, List[Tuple[str, str, float]]]:
    """
    Parse obtainments.txt. Returns name -> [(location, method, percentage), ...].
    Caller picks the entry with highest percentage per name.
    """
    path = Path(txt_path)
    if not path.exists():
        return {}
    entries: Dict[str, List[Tuple[str, str, float]]] = {}
    location = ""
    method = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("## "):
                location = line[3:].strip()
                continue
            if line.startswith("**") and line.endswith("**"):
                method = line[2:-2].strip()
                continue
            m = _OBTAINMENT_LINE_RE.match(line)
            if m:
                name = m.group(1).strip()
                pct = float(m.group(2))
                if name not in entries:
                    entries[name] = []
                entries[name].append((location, method, pct))
    return entries


def _load_special_obtainments(txt_path: Path) -> Dict[str, str]:
    """
    Parse special_obtainments.txt. Returns name -> "Location (Method %)".
    Format: Name: Location (Method % or Unknown % or Static: Day or White Egg etc)
    """
    path = Path(txt_path)
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if ":" not in line or not line.strip():
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            rest = rest.strip()
            if name and rest:
                result[name] = rest
    return result


def _load_roulette_only(txt_path: Path) -> Dict[str, str]:
    """
    Parse roulette_only.txt. Returns name -> suffix string.
    Format: one name per line, optional ^ (Breedable) or * (Obtainable in past).
    Suffix: "(Roulette Only)", "(Roulette Only - Breedable)", or "(Roulette Only - Obtainable in past)"
    """
    path = Path(txt_path)
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip().strip()
            if not line:
                continue
            if line.endswith("^"):
                result[line[:-1].strip()] = "(Roulette Only - Breedable)"
            elif line.endswith("*"):
                result[line[:-1].strip()] = "(Roulette Only - Obtainable in past)"
            else:
                result[line] = "(Roulette Only)"
    return result


def _load_unob(txt_path: Path) -> Set[str]:
    """Parse unob.txt. Returns set of unobtainable pokemon names."""
    path = Path(txt_path)
    if not path.exists():
        return set()
    result: Set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            name = line.rstrip().strip()
            if name:
                result.add(name)
    return result


def _load_raids(txt_path: Path) -> Dict[str, str]:
    """
    Parse raids.txt. Returns name -> "(Location: X* Raid Y.Y%)".
    Format: Name (Location: X* Raid Y.Y%) - stored with brackets for output.
    """
    path = Path(txt_path)
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if "(" not in line or ")" not in line or not line.strip():
                continue
            idx = line.index("(")
            name = line[:idx].strip()
            inner = line[idx + 1 : line.rindex(")")].strip()
            if name and inner:
                result[name] = f"({inner})"
    return result


def _best_obtainment(
    obtainments: Dict[str, List[Tuple[str, str, float]]],
    name: str,
) -> Optional[str]:
    """Return 'Location (Method X.X%)' for the highest-percentage obtainment, or None."""
    if not name or name == "(unknown)":
        return None
    lst = obtainments.get(name)
    if not lst:
        return None
    location, method, pct = max(lst, key=lambda x: x[2])
    return f"{location} ({method} {pct}%)"


def _load_evo_lines(txt_path: Path) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Parse evo_line.txt. Returns (name -> 'Basename line', base -> [names in line]).
    Numbered lines start a new evolution line (first name is base); continuation lines add to current base.
    """
    path = Path(txt_path)
    if not path.exists():
        return {}, {}
    evo: Dict[str, str] = {}
    line_members: Dict[str, List[str]] = {}
    current_base: Optional[str] = None
    skip_headers = ("Johto", "Evolution", "Pokémon", "Kanto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            if line[0].isdigit():
                parts = line.split("\t")
                if len(parts) >= 2:
                    names = [p.strip() for p in parts[1:] if p.strip()]
                    if names:
                        current_base = names[0]
                        if current_base not in line_members:
                            line_members[current_base] = []
                        for n in names:
                            evo[n] = f"{current_base} line"
                            if n not in line_members[current_base]:
                                line_members[current_base].append(n)
                continue
            if current_base and not any(h in line for h in skip_headers):
                name = line.strip()
                if name:
                    evo[name] = f"{current_base} line"
                    if current_base not in line_members:
                        line_members[current_base] = []
                    if name not in line_members[current_base]:
                        line_members[current_base].append(name)
    return evo, line_members


def _evolution_line_fallback(evo_lines: Dict[str, str], name: str) -> Optional[str]:
    """Return 'Basename line' if name is in an evolution line, else None."""
    if not name or name == "(unknown)":
        return None
    return evo_lines.get(name)


def _get_obtainment_for_member(
    name: str,
    obtainments: Dict[str, List[Tuple[str, str, float]]],
    special_obtainments: Dict[str, str],
    raids: Dict[str, str],
    roulette_only: Dict[str, str],
) -> Optional[str]:
    """
    Get obtainment string for a pokemon from any source (for evo line embedding).
    Returns plain string e.g. "Location (Method X%)" or "Route 7: 3* Raid 8.7%".
    Raids are returned without outer parens for clean embedding.
    """
    ob = _best_obtainment(obtainments, name)
    if ob:
        return ob
    if name in special_obtainments:
        return special_obtainments[name]
    if name in raids:
        s = raids[name]
        if s.startswith("(") and s.endswith(")"):
            return s[1:-1].strip()
        return s
    if name in roulette_only:
        return roulette_only[name]
    return None


def _best_obtainment_in_line_any_source(
    evo_line_str: str,
    line_members: Dict[str, List[str]],
    obtainments: Dict[str, List[Tuple[str, str, float]]],
    special_obtainments: Dict[str, str],
    raids: Dict[str, str],
    roulette_only: Dict[str, str],
) -> Optional[str]:
    """
    Given an evolution line, find any member with an obtainment (from any source).
    Return 'MemberName - ObtainmentString' e.g. 'Squirtle - Route 7: 3* Raid 8.7%'.
    """
    base = evo_line_str.replace(" line", "").strip()
    members = line_members.get(base, [])
    for member in members:
        ob = _get_obtainment_for_member(
            member, obtainments, special_obtainments, raids, roulette_only
        )
        if ob:
            return f"{member} - {ob}"
    return None


def write_missing_indices(
    indices: List[int],
    path: str | Path,
    *,
    pokemons_csv: Path | None = None,
) -> None:
    """
    Write missing entries to the file. If pokemons_csv is set, resolve each index to
    pokemon number (index+1) and name from the CSV and write "number name" per line.
    Otherwise write one index per line.
    """
    write_missing_numbers(
        [i + 1 for i in indices],
        path,
        pokemons_csv=pokemons_csv,
        obtainments_txt=DEFAULT_OBTAINMENTS_TXT,
        special_obtainments_txt=DEFAULT_SPECIAL_OBTAINMENTS_TXT,
        roulette_only_txt=DEFAULT_ROULETTE_ONLY_TXT,
        raids_txt=DEFAULT_RAIDS_TXT,
        unob_txt=DEFAULT_UNOB_TXT,
        evo_line_txt=DEFAULT_EVO_LINE_TXT,
    )


def write_missing_numbers(
    numbers: List[int],
    path: str | Path,
    *,
    pokemons_csv: Path | None = None,
    obtainments_txt: Path | None = None,
    special_obtainments_txt: Path | None = None,
    roulette_only_txt: Path | None = None,
    raids_txt: Path | None = None,
    unob_txt: Path | None = None,
    evo_line_txt: Path | None = None,
    missing_path: str | Path | None = None,
) -> None:
    """
    Write 1-based pokemon numbers to the file. If pokemons_csv is set, resolve to name.
    Suffix resolution order: obtainments -> special_obtainments -> raids (with evo line)
    -> roulette_only -> unob (with evo line) -> evo line + obtainment in line -> else no suffix.
    If missing_path is set, also write entries with no obtainment method to that file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names_map: Dict[int, str] = {}
    if pokemons_csv and Path(pokemons_csv).exists():
        names_map = _load_pokemon_names(Path(pokemons_csv))
    obtainments: Dict[str, List[Tuple[str, str, float]]] = {}
    if obtainments_txt and Path(obtainments_txt).exists():
        obtainments = _load_obtainments(Path(obtainments_txt))
    special_obtainments: Dict[str, str] = {}
    if special_obtainments_txt and Path(special_obtainments_txt).exists():
        special_obtainments = _load_special_obtainments(Path(special_obtainments_txt))
    roulette_only: Dict[str, str] = {}
    if roulette_only_txt and Path(roulette_only_txt).exists():
        roulette_only = _load_roulette_only(Path(roulette_only_txt))
    raids: Dict[str, str] = {}
    if raids_txt and Path(raids_txt).exists():
        raids = _load_raids(Path(raids_txt))
    unob: Set[str] = set()
    if unob_txt and Path(unob_txt).exists():
        unob = _load_unob(Path(unob_txt))
    evo_lines: Dict[str, str] = {}
    line_members: Dict[str, List[str]] = {}
    if evo_line_txt and Path(evo_line_txt).exists():
        evo_lines, line_members = _load_evo_lines(Path(evo_line_txt))

    def _resolve_suffix(name: str) -> Optional[str]:
        suffix = _best_obtainment(obtainments, name)
        if suffix:
            return suffix
        if name in special_obtainments:
            return special_obtainments[name]
        if name in raids:
            evo_line_str = _evolution_line_fallback(evo_lines, name) if evo_lines else None
            raid_suffix = raids[name]
            if evo_line_str:
                return f"{evo_line_str} {raid_suffix}"
            return raid_suffix
        if name in roulette_only:
            return roulette_only[name]
        if name in unob:
            evo_line_str = _evolution_line_fallback(evo_lines, name) if evo_lines else None
            if evo_line_str:
                return f"{evo_line_str} (Unobtainable)"
            return "(Unobtainable)"
        if evo_lines:
            evo_line_str = _evolution_line_fallback(evo_lines, name)
            if evo_line_str and line_members:
                evo_obtain = _best_obtainment_in_line_any_source(
                    evo_line_str,
                    line_members,
                    obtainments,
                    special_obtainments,
                    raids,
                    roulette_only,
                )
                if evo_obtain:
                    return f"{evo_line_str} ({evo_obtain})"
        return None

    missing_entries: List[str] = []
    with open(path, "w", encoding="utf-8") as f:
        for num in numbers:
            if names_map:
                name = names_map.get(num, "(unknown)")
                # Skip entries where the pokemon name is unknown
                if name == "(unknown)":
                    continue
                suffix = _resolve_suffix(name)
                if suffix:
                    f.write(f"{num} {name} - {suffix}\n")
                else:
                    f.write(f"{num} {name}\n")
                    if missing_path is not None:
                        missing_entries.append(f"{num} {name}")
            else:
                f.write(f"{num}\n")
                if missing_path is not None:
                    missing_entries.append(str(num))

    if missing_path is not None:
        missing_path = Path(missing_path)
        missing_path.parent.mkdir(parents=True, exist_ok=True)
        with open(missing_path, "w", encoding="utf-8") as mf:
            if missing_entries:
                mf.write("\n".join(missing_entries) + "\n")


def run_scan(
    image: Image.Image,
    config: DexScannerConfig,
    *,
    output_path: str | Path | None = None,
    debug_image_path: str | Path | None = None,
) -> List[int]:
    """
    Run the dex scan on `image` and write missing indices to file.
    If debug_image_path is set, save a copy of the image with every checked pixel highlighted in blue.
    Returns the list of missing indices.
    """
    missing = scan_image(image, config)
    out = output_path or config.output_file
    write_missing_indices(missing, out, pokemons_csv=DEFAULT_POKEMONS_CSV)
    if debug_image_path is not None:
        create_debug_image(image, config, debug_image_path)
    return missing


PAGE1_ROWS = 22
PAGE2_ROWS = 10
PAGE2_NUMBER_START = 727  # second page indices resolve to #727 (Incineroar), #728, ...


def run_scan_two_pages(
    image1: Image.Image,
    image2: Image.Image,
    config: DexScannerConfig,
    *,
    output_path: str | Path | None = None,
    debug_image_path_1: str | Path | None = None,
    debug_image_path_2: str | Path | None = None,
) -> List[int]:
    """
    Scan two dex screenshots: page 1 (22 rows, numbers 1..) and page 2 (10 rows, numbers 727..).
    Merges missing numbers from both, sorts, resolves names, and writes to output.
    """
    config1 = DexScannerConfig(
        rows=PAGE1_ROWS,
        cols=config.cols,
        sample_offset=config.sample_offset,
        output_file=config.output_file,
        red_min_r=config.red_min_r,
        red_dominance=config.red_dominance,
        white_min=config.white_min,
    )
    config2 = DexScannerConfig(
        rows=PAGE2_ROWS,
        cols=config.cols,
        sample_offset=config.sample_offset,
        output_file=config.output_file,
        red_min_r=config.red_min_r,
        red_dominance=config.red_dominance,
        white_min=config.white_min,
    )
    missing1 = scan_image(image1, config1)
    missing2 = scan_image(image2, config2)
    numbers1 = [i + 1 for i in missing1]
    numbers2 = [i + PAGE2_NUMBER_START for i in missing2]
    all_numbers = sorted(set(numbers1) | set(numbers2))
    out = output_path or config.output_file
    write_missing_numbers(
        all_numbers,
        out,
        pokemons_csv=DEFAULT_POKEMONS_CSV,
        obtainments_txt=DEFAULT_OBTAINMENTS_TXT,
        special_obtainments_txt=DEFAULT_SPECIAL_OBTAINMENTS_TXT,
        roulette_only_txt=DEFAULT_ROULETTE_ONLY_TXT,
        raids_txt=DEFAULT_RAIDS_TXT,
        unob_txt=DEFAULT_UNOB_TXT,
        evo_line_txt=DEFAULT_EVO_LINE_TXT,
    )
    if debug_image_path_1 is not None:
        create_debug_image(image1, config1, debug_image_path_1)
    if debug_image_path_2 is not None:
        create_debug_image(image2, config2, debug_image_path_2)
    return all_numbers
