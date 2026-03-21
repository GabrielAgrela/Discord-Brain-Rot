"""
Tests for bot/ui/views/rlstore.py - RocketLeagueStoreView.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestRocketLeagueStoreView:
    """Tests for rlstore pagination and image payload rendering."""

    @pytest.mark.asyncio
    async def test_prepare_all_pages_caches_tile_grid_images(self):
        """The view should pre-render every page and reuse cached bytes when paging."""
        from bot.models.rl_store import (
            RocketLeagueStoreGroup,
            RocketLeagueStoreItem,
            RocketLeagueStoreShop,
            RocketLeagueStoreSnapshot,
        )
        from bot.ui.views.rlstore import RocketLeagueStoreView

        bundle_items = [
            RocketLeagueStoreItem(
                label="Cyclone",
                category="Body",
                paint="10",
                thumbnail_url="https://rlshop.gg/cyclone.png",
            ),
            RocketLeagueStoreItem(
                label="Miku Wheels",
                category="Wheels",
                thumbnail_url="https://rlshop.gg/wheels.png",
            ),
        ]
        standalone_items = [
            RocketLeagueStoreItem(
                label=f"Item {index}",
                category="Body",
                price=100 + index,
                thumbnail_url=f"https://rlshop.gg/item-{index}.png",
            )
            for index in range(3)
        ]
        snapshot = RocketLeagueStoreSnapshot(
            last_updated=datetime(2026, 3, 17, 19, 0, 1, tzinfo=timezone.utc),
            shops=[
                RocketLeagueStoreShop(
                    shop_id=52,
                    name="Featured Shop",
                    shop_type="Featured",
                    groups=[RocketLeagueStoreGroup(name="Miku Bundle", items=bundle_items, price=1500)],
                    items=standalone_items,
                )
            ],
        )
        image_generator = Mock()
        image_generator.generate_rl_store_card = AsyncMock(side_effect=[b"page-1", b"page-2"])

        view = RocketLeagueStoreView(
            snapshot=snapshot,
            owner_id=123,
            image_generator=image_generator,
            tiles_per_page=3,
            grid_columns=3,
        )

        assert view.timeout is None
        assert len(view.pages) == 2
        assert [child.label for child in view.children] == ["Featured 1", "Featured 2"]
        assert view.children[0].disabled is True
        assert view.children[1].disabled is False

        first_payload = view.build_card_payload()
        assert first_payload["shop_name"] == "Featured Shop"
        assert first_payload["page_text"] == "Page 1/2"
        assert first_payload["grid_columns"] == 3
        assert first_payload["tiles"][0]["group_label"] == "Miku Bundle"
        assert first_payload["tiles"][0]["paint_badge"] == "Orange"
        assert first_payload["tiles"][0]["paint_badge_background"] == "#F97316"
        assert first_payload["tiles"][0]["paint_badge_color"] == "#FFF7ED"
        assert first_payload["tiles"][0]["image_url"] == "https://rlshop.gg/cyclone.png"
        assert first_payload["tiles"][1]["image_url"] == "https://rlshop.gg/wheels.png"
        assert first_payload["tiles"][2]["label"] == "Item 0"
        assert first_payload["tiles"][2]["image_url"] == "https://rlshop.gg/item-0.png"

        await view.prepare_all_pages()
        assert image_generator.generate_rl_store_card.await_count == 2
        image_file = await view.create_file()
        assert image_file.filename == "rlstore_1.png"

        view.set_current_page(1)
        second_payload = view.build_card_payload()
        assert second_payload["page_text"] == "Page 2/2"
        assert [tile["label"] for tile in second_payload["tiles"]] == ["Item 1", "Item 2"]
        assert view.children[0].disabled is False
        assert view.children[1].disabled is True
        second_file = await view.create_file()
        assert second_file.filename == "rlstore_2.png"
        assert image_generator.generate_rl_store_card.await_count == 2

    @pytest.mark.asyncio
    async def test_view_increases_tiles_per_page_to_fit_button_limit(self):
        """The view should keep total page buttons within Discord's 25-button limit."""
        from bot.models.rl_store import RocketLeagueStoreItem, RocketLeagueStoreShop, RocketLeagueStoreSnapshot
        from bot.ui.views.rlstore import RocketLeagueStoreView

        items = [
            RocketLeagueStoreItem(
                label=f"Item {index}",
                category="Decal",
                thumbnail_url=f"https://rlshop.gg/item-{index}.png",
            )
            for index in range(30)
        ]
        snapshot = RocketLeagueStoreSnapshot(
            last_updated=datetime(2026, 3, 17, 19, 0, 1, tzinfo=timezone.utc),
            shops=[RocketLeagueStoreShop(shop_id=52, name="Featured Shop", shop_type="Featured", items=items)],
        )

        view = RocketLeagueStoreView(
            snapshot=snapshot,
            owner_id=123,
            image_generator=Mock(),
            tiles_per_page=1,
            grid_columns=5,
        )

        assert view.timeout is None
        assert len(view.pages) <= 25
        assert len(view.children) == len(view.pages)
        assert view.tiles_per_page > 1
