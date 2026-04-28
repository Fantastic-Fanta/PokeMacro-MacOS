"""CLI entrypoint: scan dex_screenshot.png and dex_screenshot2.png and write missing Pokémon names."""
import sys
from pathlib import Path

import yaml
from PIL import Image

from .scanner import DexScannerConfig, run_scan_two_pages

DEX_SCREENSHOT_PAGE1 = "dex_screenshot.png"
DEX_SCREENSHOT_PAGE2 = "dex_screenshot2.png"


def _load_config(config_path: Path) -> DexScannerConfig:
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    dex = data.get("DexScanner") or {}
    return DexScannerConfig.from_dict(dex)


def main() -> None:
    argv = [a for a in sys.argv[1:] if a != "--debug"]
    debug = "--debug" in sys.argv[1:]

    repo_root = Path(__file__).resolve().parent.parent.parent
    if argv:
        path1, path2 = Path(argv[0]), Path(argv[1]) if len(argv) > 1 else None
        if path2 is None:
            print("Error: two image paths required (page1 page2)", file=sys.stderr)
            sys.exit(1)
        image_path_1, image_path_2 = path1, path2
    else:
        image_path_1 = repo_root / DEX_SCREENSHOT_PAGE1
        image_path_2 = repo_root / DEX_SCREENSHOT_PAGE2

    config_path = Path(argv[2]) if len(argv) > 2 else Path("configs.yaml")
    if not config_path.is_absolute() and not config_path.exists():
        repo_config = repo_root / "configs.yaml"
        if repo_config.exists():
            config_path = repo_config

    if not image_path_1.exists():
        print(f"Error: image not found: {image_path_1}", file=sys.stderr)
        sys.exit(1)
    if not image_path_2.exists():
        print(f"Error: image not found: {image_path_2}", file=sys.stderr)
        sys.exit(1)
    if not config_path.exists():
        print(f"Error: config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    debug_path_1 = (image_path_1.parent / f"{image_path_1.stem}_debug.png") if debug else None
    debug_path_2 = (image_path_2.parent / f"{image_path_2.stem}_debug.png") if debug else None

    image1 = Image.open(image_path_1).convert("RGB")
    image2 = Image.open(image_path_2).convert("RGB")
    config = _load_config(config_path)
    missing_numbers = run_scan_two_pages(
        image1,
        image2,
        config,
        debug_image_path_1=debug_path_1,
        debug_image_path_2=debug_path_2,
    )
    print(f"Wrote {len(missing_numbers)-33} missing Pokémon to {config.output_file}")
    if debug_path_1:
        print(f"Debug image 1: {debug_path_1}")
    if debug_path_2:
        print(f"Debug image 2: {debug_path_2}")
    if missing_numbers:
        print(f"Numbers: {missing_numbers[:20]}{'...' if len(missing_numbers) > 20 else ''}")


if __name__ == "__main__":
    main()
