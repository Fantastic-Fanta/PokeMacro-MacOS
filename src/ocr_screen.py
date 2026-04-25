import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyautogui
import pytesseract
from PIL import Image, ImageFilter

# Repo root: auto_resetter_dist/ when this file lives in auto_resetter/ocr_screen.py
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENDORED_PREFIX = _REPO_ROOT / "vendor" / "tesseract"

_tesseract_paths = [
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]


def _tesseract_runs(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            timeout=2,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _apply_vendored_macos_env(prefix: Path) -> None:
    """Set env so a vendored Homebrew-style tree can run (bin, lib, share/tessdata)."""
    lib = prefix / "lib"
    if lib.is_dir():
        prev = os.environ.get("DYLD_LIBRARY_PATH", "")
        p = str(lib)
        os.environ["DYLD_LIBRARY_PATH"] = p if not prev else f"{p}:{prev}"
    share = prefix / "share"
    if (share / "tessdata").is_dir():
        # TESSDATA_PREFIX is the parent directory of the tessdata folder
        os.environ["TESSDATA_PREFIX"] = str(share)


def _find_vendored_tesseract() -> Optional[str]:
    if os.environ.get("AUTO_RESETTER_SKIP_VENDORED_TESSERACT"):
        return None
    exe = _VENDORED_PREFIX / "bin" / "tesseract"
    if not (exe.is_file() and os.access(exe, os.X_OK)):
        return None
    _apply_vendored_macos_env(_VENDORED_PREFIX)
    if _tesseract_runs(str(exe)):
        return str(exe)
    return None


def _find_tesseract() -> Optional[str]:
    v = _find_vendored_tesseract()
    if v:
        return v
    for path in _tesseract_paths:
        if _tesseract_runs(path):
            return path
    try:
        result = subprocess.run(
            ["which", "tesseract"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _set_tesseract_path() -> None:
    if pytesseract.pytesseract.tesseract_cmd:
        return
    found = _find_tesseract()
    if found:
        pytesseract.pytesseract.tesseract_cmd = found


_tesseract_found = _find_tesseract()
if _tesseract_found:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_found


def _denoise(image: Image.Image) -> Image.Image:
    return image.filter(ImageFilter.MedianFilter(size=3))


def _monochromise(image: Image.Image, threshold: int = 128) -> Image.Image:
    gray = image.convert("L")
    return gray.point(lambda p: 255 if p >= threshold else 0, mode="L")


@dataclass(frozen=True)
class ScreenRegion:
    x: int
    y: int
    width: int
    height: int

    def capture(self, save_path: Optional[str] = None) -> Image.Image:
        screenshot = pyautogui.screenshot(region=(self.x, self.y, self.width, self.height))
        if save_path:
            screenshot.save(save_path)
        return screenshot


class OcrService:
    def extract_text(self, image: Image.Image, psm: Optional[int] = None) -> str:
        try:
            if not pytesseract.pytesseract.tesseract_cmd:
                _set_tesseract_path()
            if psm is not None:
                proc = _denoise(image)
                proc = _monochromise(proc)
                return pytesseract.image_to_string(proc, config=f"--psm {psm}").strip()
            return pytesseract.image_to_string(image).strip()
        except Exception as exc:
            error_msg = str(exc)
            print(f"\n[ERROR] OCR failed: {error_msg}")
            if "tesseract" in error_msg.lower() or "not found" in error_msg.lower():
                print("[ERROR] Tesseract OCR is not installed or not in PATH")
                print(f"[ERROR] Tried path: {getattr(pytesseract.pytesseract, 'tesseract_cmd', 'not set')}")
                print("[ERROR] Please install Tesseract, or add a macOS tree at:")
                print(f"[ERROR]   {_VENDORED_PREFIX}/ (bin/tesseract, lib/, share/tessdata/)")
                print("[ERROR]   Or: brew install tesseract")
                print("[ERROR] Then verify: tesseract --version")
            return ""
