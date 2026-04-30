import asyncio
import sys
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

import discord


def _http_connector():
    try:
        import aiohttp

        from .github_http import ssl_context

        # limit=0 matches discord.py's default connector (unbounded per-host conns).
        return aiohttp.TCPConnector(ssl=ssl_context(emit=None), limit=0)
    except Exception as e:
        print(
            f"[DiscordBot] Could not build aiohttp TLS connector ({e!r}); "
            "using discord default (often breaks on macOS/python.org without certifi).",
            file=sys.stderr,
        )
        return None


class ConfirmationResult(Enum):
    KEEP = "keep"
    ROLL = "roll"
    TIMEOUT = "timeout"


class DiscordBot:
    def __init__(self, token: str, guild_id: int):
        # Avoid message_content intent (privileged); this bot uses interactions/send only.
        intents = discord.Intents.default()
        connector = _http_connector()
        if connector is not None:
            self.client = discord.Client(intents=intents, connector=connector)
        else:
            self.client = discord.Client(intents=intents)
        self.token = token
        self.guild_id = guild_id
        self.user_id: Optional[int] = None
        self.confirmation_channel: Optional[discord.TextChannel] = None
        self.log_channel: Optional[discord.TextChannel] = None
        self.roam_channel: Optional[discord.TextChannel] = None
        self.static_channel: Optional[discord.TextChannel] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._pending_confirmations: dict[str, asyncio.Future] = {}
        self._timeout_tasks: dict[str, asyncio.Task] = {}
        self.client.event(self.on_ready)
        self.client.event(self.on_interaction)

    async def on_ready(self):
        print(f"[Discord Bot] Logged in as {self.client.user}")
        guild = self.client.get_guild(self.guild_id)
        if not guild:
            print(f"[Discord Bot] Warning: Guild {self.guild_id} not found")
            return
        try:
            owner = guild.owner or await guild.fetch_member(guild.owner_id)
            self.user_id = owner.id if owner else None
            if self.user_id:
                print(f"[Discord Bot] Using guild owner {self.user_id} for pings")
        except Exception as e:
            print(f"[Discord Bot] Failed to resolve guild owner: {e}")
        category_name = "MantiNotify"
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            try:
                category = await guild.create_category(category_name, reason="Auto-created for Pokemon Macro")
                print(f"[Discord Bot] Created category: {category_name}")
            except Exception as e:
                print(f"[Discord Bot] Failed to create category {category_name}: {e}")

        async def get_or_create_channel(channel_name: str) -> Optional[discord.TextChannel]:
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if channel is not None:
                return channel
            try:
                channel = await guild.create_text_channel(
                    channel_name,
                    category=category,
                    reason="Auto-created for Pokemon Macro",
                )
                print(f"[Discord Bot] Created channel: {channel_name}")
                return channel
            except Exception as e:
                print(f"[Discord Bot] Failed to create channel {channel_name}: {e}")
                return None

        self.confirmation_channel = await get_or_create_channel("egg-hunting")
        self.log_channel = await get_or_create_channel("reset-history")
        self.roam_channel = await get_or_create_channel("roam-hunting")
        self.static_channel = await get_or_create_channel("static-hunting")
        if self.confirmation_channel:
            print(f"[Discord Bot] Confirmation channel: {self.confirmation_channel.name}")
        if self.log_channel:
            print(f"[Discord Bot] Log channel: {self.log_channel.name}")
        if self.roam_channel:
            print(f"[Discord Bot] Roam channel: {self.roam_channel.name}")
        if self.static_channel:
            print(f"[Discord Bot] Static channel: {self.static_channel.name}")

    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data or "custom_id" not in interaction.data:
            return
        custom_id = interaction.data["custom_id"]
        if custom_id.startswith("confirm_"):
            parts = custom_id.split("_", 2)
            if len(parts) >= 3:
                confirmation_id = parts[1]
                action = parts[2]
            else:
                return
            if confirmation_id in self._pending_confirmations:
                future = self._pending_confirmations[confirmation_id]
                if confirmation_id in self._timeout_tasks:
                    self._timeout_tasks[confirmation_id].cancel()
                    del self._timeout_tasks[confirmation_id]
                mention = f"<@{self.user_id}>" if self.user_id else "@everyone"
                if action == "keep":
                    result = ConfirmationResult.KEEP
                    await interaction.response.edit_message(
                        content=f"{mention} Egg successfully saved.",
                        view=None,
                    )
                else:
                    result = ConfirmationResult.ROLL
                    await interaction.response.edit_message(
                        content=f"{mention} Egg rolled off, continuing hunt.",
                        view=None,
                    )
                if not future.done():
                    future.set_result(result)
                del self._pending_confirmations[confirmation_id]
            else:
                await interaction.response.send_message(
                    "This confirmation has expired or already been processed.",
                    ephemeral=True,
                )

    async def send_confirmation(
        self,
        message: str,
        timeout_seconds: float = 600.0,
        file_path: Optional[str] = None,
    ) -> ConfirmationResult:
        if not self.confirmation_channel:
            print("[Discord Bot] Confirmation channel not available, defaulting to KEEP")
            return ConfirmationResult.KEEP
        confirmation_id = str(uuid.uuid4())
        keep_button = discord.ui.Button(
            label="Keep",
            style=discord.ButtonStyle.grey,
            custom_id=f"confirm_{confirmation_id}_keep",
        )
        roll_button = discord.ui.Button(
            label="Roll",
            style=discord.ButtonStyle.grey,
            custom_id=f"confirm_{confirmation_id}_roll",
        )
        view = discord.ui.View()
        view.add_item(keep_button)
        view.add_item(roll_button)
        future = asyncio.Future()
        self._pending_confirmations[confirmation_id] = future
        embed = discord.Embed(description=message, color=discord.Color.from_rgb(0, 170, 255))
        file = None
        if file_path:
            path = Path(file_path)
            if path.exists():
                file = discord.File(str(path), filename=path.name)
                embed.set_image(url=f"attachment://{path.name}")
        mention = f"<@{self.user_id}>" if self.user_id else "@everyone"
        content = f"{mention} Awaiting confirmation..."
        if file is not None:
            sent_message = await self.confirmation_channel.send(content=content, embed=embed, view=view, file=file)
        else:
            sent_message = await self.confirmation_channel.send(content=content, embed=embed, view=view)

        async def timeout_handler():
            await asyncio.sleep(timeout_seconds)
            if confirmation_id in self._pending_confirmations:
                future_inner = self._pending_confirmations[confirmation_id]
                if not future_inner.done():
                    try:
                        await sent_message.edit(
                            content=f"{mention} Egg successfully saved.",
                            view=None,
                        )
                    except Exception:
                        pass
                    future_inner.set_result(ConfirmationResult.TIMEOUT)
                del self._pending_confirmations[confirmation_id]
                if confirmation_id in self._timeout_tasks:
                    del self._timeout_tasks[confirmation_id]

        timeout_task = asyncio.create_task(timeout_handler())
        self._timeout_tasks[confirmation_id] = timeout_task
        try:
            return await future
        except Exception as e:
            print(f"[Discord Bot] Error waiting for confirmation: {e}")
            return ConfirmationResult.TIMEOUT

    async def send_log_embed(self, description: str, color: Optional[discord.Color] = None) -> None:
        if not self.log_channel:
            print("[Discord Bot] Log channel not available, cannot send log embed")
            return
        embed = discord.Embed(
            description=description,
            color=color or discord.Color.from_rgb(0, 170, 255),
        )
        await self.log_channel.send(embed=embed)

    async def send_notification(self, message: str, file_path: Optional[str] = None) -> None:
        if not self.roam_channel:
            print("[Discord Bot] Roam channel not available, cannot send notification")
            return
        file = None
        if file_path:
            path = Path(file_path)
            if path.exists():
                file = discord.File(str(path), filename=path.name)
        if file is not None:
            await self.roam_channel.send(content=message, file=file)
        else:
            await self.roam_channel.send(content=message)

    def send_notification_sync(self, message: str, file_path: Optional[str] = None) -> None:
        if not self._loop or not self._loop.is_running():
            print("[Discord Bot] Bot not running, cannot send notification")
            return
        future = asyncio.run_coroutine_threadsafe(
            self.send_notification(message, file_path=file_path),
            self._loop,
        )
        try:
            future.result(timeout=15)
        except Exception as e:
            print(f"[Discord Bot] Error in sync notification: {e}")

    async def send_static_notification(self, message: str, file_path: Optional[str] = None) -> None:
        if not self.static_channel:
            print("[Discord Bot] Static channel not available, cannot send static notification")
            return
        file = None
        if file_path:
            path = Path(file_path)
            if path.exists():
                file = discord.File(str(path), filename=path.name)
        if file is not None:
            await self.static_channel.send(content=message, file=file)
        else:
            await self.static_channel.send(content=message)

    def send_static_notification_sync(self, message: str, file_path: Optional[str] = None) -> None:
        if not self._loop or not self._loop.is_running():
            print("[Discord Bot] Bot not running, cannot send static notification")
            return
        future = asyncio.run_coroutine_threadsafe(
            self.send_static_notification(message, file_path=file_path),
            self._loop,
        )
        try:
            future.result(timeout=15)
        except Exception as e:
            print(f"[Discord Bot] Error in sync static notification: {e}")

    async def send_static_confirmation(
        self,
        message: str,
        timeout_seconds: float = 600.0,
        file_path: Optional[str] = None,
    ) -> ConfirmationResult:
        if not self.static_channel:
            print("[Discord Bot] Static channel not available, defaulting to KEEP")
            return ConfirmationResult.KEEP
        confirmation_id = str(uuid.uuid4())
        keep_button = discord.ui.Button(
            label="Keep",
            style=discord.ButtonStyle.grey,
            custom_id=f"confirm_{confirmation_id}_keep",
        )
        roll_button = discord.ui.Button(
            label="Roll",
            style=discord.ButtonStyle.grey,
            custom_id=f"confirm_{confirmation_id}_roll",
        )
        view = discord.ui.View()
        view.add_item(keep_button)
        view.add_item(roll_button)
        future = asyncio.Future()
        self._pending_confirmations[confirmation_id] = future
        embed = discord.Embed(description=message, color=discord.Color.from_rgb(0, 170, 255))
        file = None
        if file_path:
            path = Path(file_path)
            if path.exists():
                file = discord.File(str(path), filename=path.name)
                embed.set_image(url=f"attachment://{path.name}")
        mention = f"<@{self.user_id}>" if self.user_id else "@everyone"
        content = f"{mention} Awaiting confirmation..."
        if file is not None:
            sent_message = await self.static_channel.send(content=content, embed=embed, view=view, file=file)
        else:
            sent_message = await self.static_channel.send(content=content, embed=embed, view=view)

        async def timeout_handler():
            await asyncio.sleep(timeout_seconds)
            if confirmation_id in self._pending_confirmations:
                future_inner = self._pending_confirmations[confirmation_id]
                if not future_inner.done():
                    try:
                        await sent_message.edit(
                            content=f"{mention} Static successfully saved.",
                            view=None,
                        )
                    except Exception:
                        pass
                    future_inner.set_result(ConfirmationResult.TIMEOUT)
                del self._pending_confirmations[confirmation_id]
                if confirmation_id in self._timeout_tasks:
                    del self._timeout_tasks[confirmation_id]

        timeout_task = asyncio.create_task(timeout_handler())
        self._timeout_tasks[confirmation_id] = timeout_task
        try:
            return await future
        except Exception as e:
            print(f"[Discord Bot] Error waiting for static confirmation: {e}")
            return ConfirmationResult.TIMEOUT

    def send_static_confirmation_sync(
        self,
        message: str,
        timeout_seconds: float = 300.0,
        file_path: Optional[str] = None,
    ) -> ConfirmationResult:
        if not self._loop or not self._loop.is_running():
            print("[Discord Bot] Bot not running, defaulting to KEEP")
            return ConfirmationResult.KEEP
        future = asyncio.run_coroutine_threadsafe(
            self.send_static_confirmation(message, timeout_seconds, file_path=file_path),
            self._loop,
        )
        try:
            return future.result(timeout=timeout_seconds + 5)
        except Exception as e:
            print(f"[Discord Bot] Error in sync static confirmation: {e}")
            return ConfirmationResult.TIMEOUT

    async def send_static_log_embed(self, description: str, color: Optional[discord.Color] = None) -> None:
        if not self.static_channel:
            print("[Discord Bot] Static channel not available, cannot send static log embed")
            return
        embed = discord.Embed(
            description=description,
            color=color or discord.Color.from_rgb(0, 170, 255),
        )
        await self.static_channel.send(embed=embed)

    def send_static_log_embed_sync(self, description: str, color: Optional[discord.Color] = None) -> None:
        if not self._loop or not self._loop.is_running():
            print("[Discord Bot] Bot not running, cannot send static log embed")
            return
        future = asyncio.run_coroutine_threadsafe(
            self.send_static_log_embed(description, color),
            self._loop,
        )
        try:
            future.result(timeout=5)
        except Exception as e:
            print(f"[Discord Bot] Error in sync static log embed: {e}")

    def start(self):
        def run_bot():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._loop.run_until_complete(self.client.start(self.token))
            except BaseException:
                import traceback

                err = sys.exc_info()[1]
                traceback.print_exc(file=sys.stderr)
                try:
                    from .github_http import emit_tls_hint

                    emit_tls_hint(lambda s: print(s, file=sys.stderr), err)
                    cause = getattr(err, "__cause__", None)
                    if cause is not None:
                        emit_tls_hint(lambda s: print(s, file=sys.stderr), cause)
                except Exception:
                    pass
                sys.stderr.flush()

        self._thread = threading.Thread(target=run_bot, daemon=True)
        self._thread.start()
        max_wait = 30
        waited = 0
        while (not self.confirmation_channel or not self.log_channel or not self.roam_channel or not self.static_channel) and waited < max_wait:
            time.sleep(0.5)
            waited += 0.5
        if not self.confirmation_channel or not self.log_channel or not self.roam_channel or not self.static_channel:
            print("[Discord Bot] Warning: Bot did not fully initialize channels within timeout")

    def stop(self):
        if self._loop and self._loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self.client.close(), self._loop)
            try:
                fut.result(timeout=15)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)

    def send_confirmation_sync(
        self,
        message: str,
        timeout_seconds: float = 300.0,
        file_path: Optional[str] = None,
    ) -> ConfirmationResult:
        if not self._loop or not self._loop.is_running():
            print("[Discord Bot] Bot not running, defaulting to KEEP")
            return ConfirmationResult.KEEP
        future = asyncio.run_coroutine_threadsafe(
            self.send_confirmation(message, timeout_seconds, file_path=file_path),
            self._loop,
        )
        try:
            return future.result(timeout=timeout_seconds + 5)
        except Exception as e:
            print(f"[Discord Bot] Error in sync confirmation: {e}")
            return ConfirmationResult.TIMEOUT

    def send_log_embed_sync(
        self,
        description: str,
        color: Optional[discord.Color] = None,
    ) -> None:
        if not self._loop or not self._loop.is_running():
            print("[Discord Bot] Bot not running, cannot send log embed")
            return
        future = asyncio.run_coroutine_threadsafe(
            self.send_log_embed(description, color),
            self._loop,
        )
        try:
            future.result(timeout=5)
        except Exception as e:
            print(f"[Discord Bot] Error in sync log embed: {e}")
