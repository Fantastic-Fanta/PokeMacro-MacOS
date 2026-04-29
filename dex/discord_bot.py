from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import yaml
from PIL import Image

from .scanner import DexScannerConfig, run_scan_two_pages

log = logging.getLogger(__name__)


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_yaml(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _load_dex_config(config_path: Path) -> DexScannerConfig:
    data = _load_yaml(config_path)
    dex = data.get("DexScanner") or {}
    return DexScannerConfig.from_dict(dex)


def _load_discord_bot_token(config_path: Path) -> str:
    return _load_yaml(config_path).get("DiscordBotToken") or ""


class DexScannerBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        @self.tree.command(
            name="scan-dex",
            description="Poopidex scanner",
        )
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def scan_dex(
            interaction: discord.Interaction,
            page1: discord.Attachment,
            page2: discord.Attachment,
        ) -> None:
            await interaction.response.defer(thinking=True, ephemeral=False)

            try:
                data1 = await page1.read()
                data2 = await page2.read()
            except discord.HTTPException as exc:
                await interaction.followup.send(f"Failed to download attachments: {exc}", ephemeral=False)
                return

            try:
                image1 = Image.open(BytesIO(data1)).convert("RGB")
                image2 = Image.open(BytesIO(data2)).convert("RGB")
            except Exception as exc:  # pragma: no cover - PIL-specific failure
                await interaction.followup.send(f"Failed to open images: {exc}", ephemeral=False)
                return

            repo_root = _get_repo_root()

            config_path: Optional[Path] = None
            candidate = Path("configs.yaml")
            if candidate.is_absolute() or candidate.exists():
                config_path = candidate
            else:
                repo_candidate = repo_root / "configs.yaml"
                if repo_candidate.exists():
                    config_path = repo_candidate

            if config_path is None or not config_path.exists():
                await interaction.followup.send("Config file configs.yaml not found.", ephemeral=False)
                return

            try:
                config = _load_dex_config(config_path)
            except Exception as exc:  # pragma: no cover - YAML errors
                await interaction.followup.send(f"Failed to load config: {exc}", ephemeral=False)
                return

            output_path = repo_root / "missing-poopimons.txt"

            try:
                missing_numbers = run_scan_two_pages(
                    image1,
                    image2,
                    config,
                    output_path=output_path,
                )
            except Exception as exc:  # pragma: no cover - scanner errors
                log.exception("Dex scan failed")
                await interaction.followup.send(f"Dex scan failed: {exc}", ephemeral=False)
                return

            if not output_path.exists():
                await interaction.followup.send(
                    "Scan completed but missing-poopimons.txt could not be found.",
                    ephemeral=False,
                )
                return

            description = f"{len(missing_numbers)} missing"

            await interaction.followup.send(
                content=description,
                file=discord.File(str(output_path), filename="missing-poopimons.txt"),
                ephemeral=False,
            )

        try:
            synced = await self.tree.sync()
            log.info("Synced %d application commands", len(synced))
        except Exception:  # pragma: no cover - best-effort logging
            log.exception("Failed to sync application commands")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    repo_root = _get_repo_root()
    config_path = repo_root / "configs.yaml"
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")
    token = _load_discord_bot_token(config_path)
    if not token:
        raise SystemExit("DiscordBotToken is not set in configs.yaml")
    DexScannerBot().run(token)


if __name__ == "__main__":
    main()

