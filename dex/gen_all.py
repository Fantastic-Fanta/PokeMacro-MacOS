"""Generate a full dex list (1-1025) for testing output formatting without running the Discord bot."""
from pathlib import Path

from .scanner import (
    DEFAULT_EVO_LINE_TXT,
    DEFAULT_OBTAINMENTS_TXT,
    DEFAULT_POKEMONS_CSV,
    DEFAULT_RAIDS_TXT,
    DEFAULT_ROULETTE_ONLY_TXT,
    DEFAULT_SPECIAL_OBTAINMENTS_TXT,
    DEFAULT_UNOB_TXT,
    write_missing_numbers,
)

DEX_SCANNER_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = DEX_SCANNER_DIR / "dex.txt"
MISSING_PATH = DEX_SCANNER_DIR / "missing.txt"


def main() -> None:
    numbers = list(range(1, 1026))
    write_missing_numbers(
        numbers,
        OUTPUT_PATH,
        pokemons_csv=DEFAULT_POKEMONS_CSV,
        obtainments_txt=DEFAULT_OBTAINMENTS_TXT,
        special_obtainments_txt=DEFAULT_SPECIAL_OBTAINMENTS_TXT,
        roulette_only_txt=DEFAULT_ROULETTE_ONLY_TXT,
        raids_txt=DEFAULT_RAIDS_TXT,
        unob_txt=DEFAULT_UNOB_TXT,
        evo_line_txt=DEFAULT_EVO_LINE_TXT,
        missing_path=MISSING_PATH,
    )
    print(f"Wrote {len(numbers)} entries to {OUTPUT_PATH}")
    print(f"Wrote pokemon without obtainment to {MISSING_PATH}")


if __name__ == "__main__":
    main()
