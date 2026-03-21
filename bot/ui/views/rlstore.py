"""
Paginated Rocket League store view.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import discord
from discord.ui import Button, View

from bot.models import (
    RocketLeagueStoreGroup,
    RocketLeagueStoreItem,
    RocketLeagueStoreShop,
    RocketLeagueStoreSnapshot,
)
from bot.services.image_generator import ImageGeneratorService


PAINT_BADGE_STYLES: dict[str, dict[str, str]] = {
    "Black": {
        "background": "#0F172A",
        "color": "#F8FAFC",
        "border": "rgba(148, 163, 184, 0.42)",
    },
    "Burnt Sienna": {
        "background": "#9A3412",
        "color": "#F8FAFC",
        "border": "rgba(251, 146, 60, 0.38)",
    },
    "Cobalt": {
        "background": "#1D4ED8",
        "color": "#F8FAFC",
        "border": "rgba(147, 197, 253, 0.36)",
    },
    "Crimson": {
        "background": "#DC2626",
        "color": "#F8FAFC",
        "border": "rgba(254, 202, 202, 0.3)",
    },
    "Forest Green": {
        "background": "#15803D",
        "color": "#F8FAFC",
        "border": "rgba(187, 247, 208, 0.34)",
    },
    "Gold": {
        "background": "#F59E0B",
        "color": "#111827",
        "border": "rgba(253, 230, 138, 0.4)",
    },
    "Grey": {
        "background": "#94A3B8",
        "color": "#0F172A",
        "border": "rgba(226, 232, 240, 0.4)",
    },
    "Lime": {
        "background": "#84CC16",
        "color": "#111827",
        "border": "rgba(217, 249, 157, 0.36)",
    },
    "Orange": {
        "background": "#F97316",
        "color": "#FFF7ED",
        "border": "rgba(254, 215, 170, 0.36)",
    },
    "Pink": {
        "background": "#EC4899",
        "color": "#FFF7FB",
        "border": "rgba(251, 207, 232, 0.34)",
    },
    "Purple": {
        "background": "#7C3AED",
        "color": "#F5F3FF",
        "border": "rgba(221, 214, 254, 0.34)",
    },
    "Saffron": {
        "background": "#FACC15",
        "color": "#111827",
        "border": "rgba(254, 240, 138, 0.42)",
    },
    "Sky Blue": {
        "background": "#38BDF8",
        "color": "#082F49",
        "border": "rgba(186, 230, 253, 0.4)",
    },
    "Titanium White": {
        "background": "#F8FAFC",
        "color": "#0F172A",
        "border": "rgba(148, 163, 184, 0.4)",
    },
}
DEFAULT_PAINT_BADGE_STYLE = {
    "background": "rgba(71, 85, 105, 0.92)",
    "color": "#F8FAFC",
    "border": "rgba(226, 232, 240, 0.18)",
}


@dataclass(frozen=True)
class RocketLeagueStoreTile:
    """Single compact tile rendered on a store page."""

    item: RocketLeagueStoreItem
    bundle_name: Optional[str] = None
    bundle_price: Optional[int] = None
    bundle_end_time: Optional[datetime] = None


@dataclass(frozen=True)
class RocketLeagueStorePage:
    """Single rendered page in the Rocket League store view."""

    shop: RocketLeagueStoreShop
    tiles: list[RocketLeagueStoreTile]
    shop_index: int
    shop_page_index: int
    total_shop_pages: int


class RocketLeagueStorePageButton(Button):
    """Jump directly to one cached store page."""

    def __init__(self, page_index: int, label: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=page_index // 5,
        )
        self.page_index = page_index

    async def callback(self, interaction: discord.Interaction):
        """Update the visible store page."""
        view: RocketLeagueStoreView = self.view
        if view.owner_id is not None and interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "Only the user who opened `/rlstore` can change pages.",
                ephemeral=True,
            )
            return

        view.set_current_page(self.page_index)
        image_file = await view.create_file()
        if image_file is not None:
            await interaction.response.edit_message(
                attachments=[],
                file=image_file,
                embed=None,
                view=view,
            )
            return

        await interaction.response.edit_message(embed=view.create_embed(), view=view)


class RocketLeagueStoreView(View):
    """Discord view for browsing active Rocket League store pages."""

    MAX_PAGE_BUTTONS = 25

    def __init__(
        self,
        snapshot: RocketLeagueStoreSnapshot,
        owner_id: Optional[int],
        image_generator: ImageGeneratorService,
        tiles_per_page: int = 10,
        grid_columns: int = 5,
    ):
        """
        Initialize the Rocket League store view.

        Args:
            snapshot: Current upstream store snapshot.
            owner_id: Optional Discord user ID allowed to page this view.
            image_generator: Shared image generator used for page rendering.
            tiles_per_page: Number of tiles to render per page.
            grid_columns: Number of columns in the compact store grid.
        """
        super().__init__(timeout=None)
        self.snapshot = snapshot
        self.owner_id = owner_id
        self.image_generator = image_generator
        self.grid_columns = max(1, grid_columns)
        self._shop_tiles = [(shop, self._build_tiles(shop)) for shop in self.snapshot.shops]
        self.tiles_per_page = self._resolve_tiles_per_page(max(1, tiles_per_page))
        self.current_page = 0
        self.pages = self._build_pages()
        self._prepare_lock = asyncio.Lock()
        self._prepared_page_images: list[Optional[bytes]] = [None] * len(self.pages)
        self._all_pages_prepared = False

        self._build_page_buttons()
        self._sync_button_state()

    def _resolve_tiles_per_page(self, base_tiles_per_page: int) -> int:
        """Increase tile density until the view fits Discord's 25-button limit."""
        tiles_per_page = base_tiles_per_page
        while len(self._build_pages(tiles_per_page)) > self.MAX_PAGE_BUTTONS:
            tiles_per_page += 1
        return tiles_per_page

    def _build_pages(self, tiles_per_page: Optional[int] = None) -> list[RocketLeagueStorePage]:
        """Flatten active shops into compact tile pages."""
        resolved_tiles_per_page = tiles_per_page or self.tiles_per_page
        pages: list[RocketLeagueStorePage] = []

        for shop_index, (shop, tiles) in enumerate(self._shop_tiles):
            total_shop_pages = max(1, (len(tiles) + resolved_tiles_per_page - 1) // resolved_tiles_per_page)
            for shop_page_index in range(total_shop_pages):
                start = shop_page_index * resolved_tiles_per_page
                end = start + resolved_tiles_per_page
                pages.append(
                    RocketLeagueStorePage(
                        shop=shop,
                        tiles=tiles[start:end],
                        shop_index=shop_index,
                        shop_page_index=shop_page_index,
                        total_shop_pages=total_shop_pages,
                    )
                )

        if pages:
            return pages

        return [
            RocketLeagueStorePage(
                shop=RocketLeagueStoreShop(shop_id=0, name="No Shop Data", shop_type="Unknown"),
                tiles=[],
                shop_index=0,
                shop_page_index=0,
                total_shop_pages=1,
            )
        ]

    def _build_page_buttons(self) -> None:
        """Add one numbered button for every cached page."""
        self.clear_items()
        for page_index in range(len(self.pages)):
            self.add_item(
                RocketLeagueStorePageButton(
                    page_index=page_index,
                    label=self._page_button_label(self.pages[page_index]),
                )
            )

    def _build_tiles(self, shop: RocketLeagueStoreShop) -> list[RocketLeagueStoreTile]:
        """Flatten grouped and standalone items into compact tile records."""
        tiles: list[RocketLeagueStoreTile] = []
        for group in shop.groups:
            tiles.extend(
                RocketLeagueStoreTile(
                    item=item,
                    bundle_name=group.name,
                    bundle_price=group.price,
                    bundle_end_time=group.end_time,
                )
                for item in group.items
            )
        tiles.extend(RocketLeagueStoreTile(item=item) for item in shop.items)
        return tiles

    def advance_page(self, direction: str) -> None:
        """Move to the next or previous global page."""
        if not self.pages:
            return

        if direction == "previous":
            target_page = (self.current_page - 1) % len(self.pages)
        else:
            target_page = (self.current_page + 1) % len(self.pages)

        self.set_current_page(target_page)

    def set_current_page(self, page_index: int) -> None:
        """Jump directly to a target page index."""
        if not self.pages:
            return

        self.current_page = page_index % len(self.pages)

        self._sync_button_state()

    async def prepare_all_pages(self) -> None:
        """Pre-render every page image so pagination reuses cached bytes."""
        if self._all_pages_prepared:
            return

        async with self._prepare_lock:
            if self._all_pages_prepared:
                return

            rendered_pages = await asyncio.gather(
                *[
                    self.image_generator.generate_rl_store_card(self.build_card_payload(page_index=index))
                    for index in range(len(self.pages))
                ]
            )
            self._prepared_page_images = list(rendered_pages)
            self._all_pages_prepared = True

    async def create_file(self) -> Optional[discord.File]:
        """
        Create an image attachment for the current store page.

        Returns:
            A Discord file when image rendering succeeds, otherwise ``None``.
        """
        await self.prepare_all_pages()
        image_bytes = self._prepared_page_images[self.current_page]
        if not image_bytes:
            return None
        filename = f"rlstore_{self.current_page + 1}.png"
        return discord.File(io.BytesIO(image_bytes), filename=filename)

    def build_card_payload(self, page_index: Optional[int] = None) -> dict[str, Any]:
        """
        Build the template payload for a page image.

        Args:
            page_index: Optional page index; defaults to the current page.

        Returns:
            A dictionary consumed by ``ImageGeneratorService.generate_rl_store_card``.
        """
        target_index = self.current_page if page_index is None else page_index
        page = self.pages[target_index]
        return {
            "shop_name": page.shop.display_name,
            "shop_subtitle": page.shop.title if page.shop.title and page.shop.title != page.shop.display_name else None,
            "shop_type": page.shop.shop_type,
            "updated_text": self.snapshot.last_updated.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC"),
            "ends_text": self._page_ends_text(page),
            "page_text": f"Page {target_index + 1}/{len(self.pages)}",
            "summary_text": (
                f"Shop {page.shop_index + 1}/{max(1, len(self.snapshot.shops))}"
                f" | Shop Page {page.shop_page_index + 1}/{page.total_shop_pages}"
            ),
            "source_label": "Source rlshop.gg",
            "accent_color": self._shop_accent_color_hex(page.shop),
            "grid_columns": self.grid_columns,
            "tiles": [self._build_card_tile(tile, page.shop) for tile in page.tiles],
        }

    def create_embed(self) -> discord.Embed:
        """Create an embed fallback for the current store page."""
        page = self.pages[self.current_page]
        embed = discord.Embed(
            title=f"Rocket League Store | {page.shop.display_name}",
            description=self._build_description(page),
            color=self._shop_color(page.shop),
        )

        thumbnail_url = self._first_thumbnail(page)
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        if not page.tiles:
            embed.add_field(
                name="No Items",
                value="The upstream shop page returned no items for this section.",
                inline=False,
            )
        else:
            for tile in page.tiles:
                embed.add_field(
                    name=self._truncate(self._tile_title(tile), 256),
                    value=self._truncate(self._tile_value(tile, page.shop), 1024),
                    inline=True,
                )

        embed.timestamp = self.snapshot.last_updated
        total_shops = max(1, len(self.snapshot.shops))
        embed.set_footer(
            text=(
                f"Global Page {self.current_page + 1}/{len(self.pages)}"
                f" | Shop {page.shop_index + 1}/{total_shops}"
                f" | Shop Page {page.shop_page_index + 1}/{page.total_shop_pages}"
            )
        )
        return embed

    def _build_card_tile(
        self,
        tile: RocketLeagueStoreTile,
        shop: RocketLeagueStoreShop,
    ) -> dict[str, Any]:
        """Convert a compact tile into template data."""
        item = tile.item
        paint_badge = self._paint_badge_payload(item)
        return {
            "label": item.label,
            "category": item.category,
            "group_label": tile.bundle_name,
            "paint_badge": paint_badge["label"],
            "paint_badge_background": paint_badge["background"],
            "paint_badge_color": paint_badge["color"],
            "paint_badge_border": paint_badge["border"],
            "time_badge": self._tile_time_badge(tile, shop),
            "price_text": self._tile_price_text(tile),
            "image_url": item.thumbnail_url,
            "placeholder": self._placeholder_text(item.label),
        }

    def _tile_price_text(self, tile: RocketLeagueStoreTile) -> Optional[str]:
        """Return the effective price label for a tile."""
        price = tile.item.price if tile.item.price is not None else tile.bundle_price
        if price is None:
            return None
        return f"{price} credits"

    def _tile_end_time(
        self,
        tile: RocketLeagueStoreTile,
        shop: RocketLeagueStoreShop,
    ) -> Optional[datetime]:
        """Resolve the end time shown for a tile."""
        return tile.item.end_time or tile.bundle_end_time or shop.ends_at

    def _tile_time_badge(
        self,
        tile: RocketLeagueStoreTile,
        shop: RocketLeagueStoreShop,
    ) -> Optional[str]:
        """Return a relative remaining-time label for the tile."""
        end_time = self._tile_end_time(tile, shop)
        if end_time is None:
            return None
        return self._format_remaining(end_time, self.snapshot.last_updated)

    def _page_ends_text(self, page: RocketLeagueStorePage) -> Optional[str]:
        """Return a concise page-level end-time label."""
        if page.shop.ends_at:
            return f"Ends {self._format_short_datetime(page.shop.ends_at)}"
        if page.shop.is_rlcs:
            return "Persistent RLCS rotation"
        return None

    def _format_remaining(self, end_time: datetime, reference_time: datetime) -> str:
        """Return a compact relative duration like '23h 4m'."""
        remaining_seconds = max(0, int((end_time - reference_time).total_seconds()))
        total_minutes = max(0, remaining_seconds // 60)
        days, rem_minutes = divmod(total_minutes, 24 * 60)
        hours, minutes = divmod(rem_minutes, 60)
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _sync_button_state(self) -> None:
        """Highlight the active numbered page button."""
        for child in self.children:
            if isinstance(child, RocketLeagueStorePageButton):
                is_current = child.page_index == self.current_page
                child.disabled = is_current
                child.style = (
                    discord.ButtonStyle.primary
                    if is_current
                    else discord.ButtonStyle.secondary
                )

    def _page_button_label(self, page: RocketLeagueStorePage) -> str:
        """Return a short but descriptive label for a page-jump button."""
        base = (page.shop.display_name or f"Shop {page.shop_index + 1}").strip()
        if base.lower().endswith(" shop"):
            base = base[:-5].strip()

        words = base.split()
        if len(base) > 12 and len(words) > 1:
            shortened = " ".join(words[:2])
            if len(shortened) <= 12:
                base = shortened

        if len(base) > 12:
            base = f"{base[:9].rstrip()}..."

        if page.total_shop_pages > 1:
            return f"{base} {page.shop_page_index + 1}"
        return base

    def _build_description(self, page: RocketLeagueStorePage) -> str:
        """Build the current page description."""
        updated_text = self.snapshot.last_updated.astimezone(timezone.utc).strftime("%B %d, %Y %H:%M UTC")
        lines = [
            f"Updated: {updated_text}",
            f"Type: {page.shop.shop_type}",
        ]

        if page.shop.title and page.shop.title != page.shop.display_name:
            lines.append(f"Title: {page.shop.title}")
        if page.shop.ends_at:
            lines.append(f"Ends: {self._format_datetime(page.shop.ends_at)}")
        elif page.shop.is_rlcs:
            lines.append("Ends: Persistent RLCS shop rotation")

        return "\n".join(lines)

    def _tile_title(self, tile: RocketLeagueStoreTile) -> str:
        """Return the embed field title for a compact tile."""
        price_text = self._tile_price_text(tile)
        if price_text:
            return f"{tile.item.label} | {price_text}"
        return tile.item.label

    def _tile_value(self, tile: RocketLeagueStoreTile, shop: RocketLeagueStoreShop) -> str:
        """Return the embed field value for a compact tile."""
        lines = [f"Category: {tile.item.category}"]
        if tile.item.paint_name:
            lines.append(f"Paint: {tile.item.paint_name}")
        if tile.bundle_name:
            lines.append(f"Bundle: {tile.bundle_name}")
        end_time = self._tile_end_time(tile, shop)
        if end_time is not None:
            lines.append(f"Ends: {self._format_datetime(end_time)}")
        return "\n".join(lines)

    def _first_thumbnail(self, page: RocketLeagueStorePage) -> Optional[str]:
        """Return the first usable thumbnail from the current page."""
        for tile in page.tiles:
            if tile.item.thumbnail_url:
                return tile.item.thumbnail_url
        return None

    def _placeholder_text(self, label: str) -> str:
        """Return a compact fallback label when an item image is missing."""
        words = [word for word in label.split() if word]
        if not words:
            return "RL"
        if len(words) == 1:
            return words[0][:10]
        return " ".join(word[:4] for word in words[:2])

    def _paint_badge_payload(self, item: RocketLeagueStoreItem) -> dict[str, Optional[str]]:
        """Return label and style tokens for the item's paint badge."""
        paint_name = item.paint_name
        if not paint_name or paint_name == "Unpainted":
            return {
                "label": None,
                "background": None,
                "color": None,
                "border": None,
            }

        style = PAINT_BADGE_STYLES.get(paint_name, DEFAULT_PAINT_BADGE_STYLE)
        return {
            "label": paint_name,
            "background": style["background"],
            "color": style["color"],
            "border": style["border"],
        }

    def _format_datetime(self, value: datetime) -> str:
        """Format a timezone-aware datetime for embeds."""
        return value.astimezone(timezone.utc).strftime("%B %d, %Y %H:%M UTC")

    def _format_short_datetime(self, value: datetime) -> str:
        """Format a timezone-aware datetime for compact card metadata."""
        return value.astimezone(timezone.utc).strftime("%b %d %H:%M UTC")

    def _shop_color(self, shop: RocketLeagueStoreShop) -> discord.Color:
        """Return an embed color by shop type."""
        if shop.is_rlcs:
            return discord.Color.red()
        if shop.shop_type == "Featured":
            return discord.Color.gold()
        if shop.shop_type == "Bundle":
            return discord.Color.blue()
        return discord.Color.blurple()

    def _shop_accent_color_hex(self, shop: RocketLeagueStoreShop) -> str:
        """Return a hex border accent that matches the shop type."""
        if shop.is_rlcs:
            return "#EF4444"
        if shop.shop_type == "Featured":
            return "#F59E0B"
        if shop.shop_type == "Bundle":
            return "#38BDF8"
        return "#5865F2"

    def _truncate(self, value: str, limit: int) -> str:
        """Clamp text to Discord embed limits."""
        if len(value) <= limit:
            return value
        return value[: limit - 3].rstrip() + "..."
