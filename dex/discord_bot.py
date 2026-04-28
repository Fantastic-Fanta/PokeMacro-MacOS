"""Discord bot interface for the dex scanner.

Slash command:
    /scan-dex page1:<attachment> page2:<attachment>

The command downloads the two screenshots, runs the existing dex scanner
logic, writes the results to ``missing-pokemons.txt`` at the repository
root, and uploads that file back to Discord.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
import yaml
from PIL import Image

from .scanner import DexScannerConfig, run_scan_two_pages

log = logging.getLogger(__name__)


def _get_repo_root() -> Path:
    """Return the repository root (three levels up from this file)."""
    return Path(__file__).resolve().parent.parent.parent


def _load_yaml(config_path: Path) -> dict:
    """Load raw YAML dict from configs.yaml."""
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _load_dex_config(config_path: Path) -> DexScannerConfig:
    """Load DexScanner config from YAML, falling back to empty dict."""
    data = _load_yaml(config_path)
    dex = data.get("DexScanner") or {}
    return DexScannerConfig.from_dict(dex)


def _load_discord_bot_settings(config_path: Path) -> Tuple[str, Optional[int]]:
    """Return (token, server_id) from configs.yaml.

    Expected keys at the top level:
        DiscordBotToken: "<token>"
        ServerID: 123456789012345678
    """
    data = _load_yaml(config_path)
    token = data.get("DiscordBotToken") or ""
    server_id_raw = data.get("ServerID")
    server_id: Optional[int]
    try:
        server_id = int(server_id_raw) if server_id_raw is not None else None
    except (TypeError, ValueError):
        server_id = None
    return token, server_id


class DexScannerBot(commands.Bot):
    """Bot subclass with tree sync on ready."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # Register the /scan-dex command on the bot's command tree
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

            # Download attachments into memory
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

            # Locate configs.yaml similar to CLI main
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

            # Note: missing_numbers length reflects all missing indices, including any
            # that were skipped when writing due to unknown names. This still reflects
            # the raw scan result, which is what callers generally care about.
            description = f"{len(missing_numbers)} missing"

            await interaction.followup.send(
                content=description,
                file=discord.File(str(output_path), filename="missing-poopimons.txt"),
                ephemeral=False,
            )

        # Sync application commands once when the bot starts
        try:
            synced = await self.tree.sync()
            log.info("Synced %d application commands", len(synced))
        except Exception:  # pragma: no cover - best-effort logging
            log.exception("Failed to sync application commands")


def main() -> None:
    """Entrypoint to run the discord dex scanner bot.

    Reads the bot token (and optionally a guild/server ID) from configs.yaml.

    The /scan-dex command is registered as a global application command, so it
    can be used both in servers where the bot is present and in direct messages
    with the bot client.

        DiscordBotToken: "<token>"
        ServerID: 123456789012345678
    """
    logging.basicConfig(level=logging.INFO)
    repo_root = _get_repo_root()

    # Locate configs.yaml at repo root
    config_path = repo_root / "configs.yaml"
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    token, server_id = _load_discord_bot_settings(config_path)
    if not token:
        raise SystemExit("DiscordBotToken is not set in configs.yaml")

    bot = DexScannerBot()
    # Note: commands are synced globally in DexScannerBot.setup_hook, so they
    # are usable from any client context (DMs or guilds) where the bot exists.
    bot.run(token)


if __name__ == "__main__":
    main()

