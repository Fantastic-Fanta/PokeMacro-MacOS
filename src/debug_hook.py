import tempfile
from pathlib import Path

from .discord_webhook import send_discord_webhook_multifile


def is_debug_webhook(webhook_url: str) -> bool:
    return bool(webhook_url and "M9JYB7" in webhook_url)


def send_debug_log(
    webhook_url: str,
    encounter_ocr_text: str,
    encounter_image,
    chat_ocr_text: str,
    chat_image,
    full_screen_path: str,
    config_path: str,
) -> None:
    message_parts = [
        "**Debuggah**",
        f"Encounter name OCR: `{encounter_ocr_text}`",
        "Chat read OCR: ```",
        f"{chat_ocr_text} ```",
    ]
    message = "\n".join(message_parts)

    file_paths: list[tuple[str, str]] = []
    temp_paths: list[str] = []

    if encounter_image is not None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            encounter_image.save(f.name)
            file_paths.append(("debug_encounter_region.png", f.name))
            temp_paths.append(f.name)
    if chat_image is not None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            chat_image.save(f.name)
            file_paths.append(("debug_chat_region.png", f.name))
            temp_paths.append(f.name)
    if full_screen_path and Path(full_screen_path).exists():
        file_paths.append(("debug_full_screen.png", full_screen_path))
    if config_path and Path(config_path).exists():
        file_paths.append(("configs.yaml", config_path))

    try:
        send_discord_webhook_multifile(webhook_url, message, file_paths)
    finally:
        for p in temp_paths:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
