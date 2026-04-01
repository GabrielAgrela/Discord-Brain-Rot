"""
Tests for bot/services/rl_store.py - RocketLeagueStoreService.
"""

import os
import sys
from unittest.mock import AsyncMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


ROOT_PAYLOAD = {
    "type": "data",
    "nodes": [
        {
            "type": "data",
            "data": [
                {"activeShops": 1, "lastUpdated": 4},
                [2, 3],
                {"ID": 5, "Type": 6, "StartDate": 7, "EndDate": 8, "LogoURL": 9, "Name": 10, "Title": 9},
                {"ID": 11, "Type": 12, "StartDate": 13, "EndDate": 14, "LogoURL": 9, "Name": 15, "Title": 9},
                ["Date", "2026-03-17T19:00:01.000Z"],
                52,
                "Featured",
                1568070623,
                None,
                None,
                "Featured Shop",
                340,
                "Bundle",
                1773504000,
                1774141200,
                "HATSUNE MIKU",
            ],
            "uses": {},
        },
        {
            "type": "data",
            "data": [
                {"shopName": 1, "isRLCS": 2, "groups": 3, "items": 4},
                "Featured Shop",
                False,
                [],
                [5],
                {"thumbnail": 6, "label": 7, "category": 8, "price": 9, "paint": 10, "endTime": 11},
                "/featured.png",
                "Scarab",
                "Body",
                "400",
                "10",
                1773860400,
            ],
            "uses": {"params": ["id"]},
        },
    ],
}


MULTI_FEATURED_ROOT_PAYLOAD = {
    "type": "data",
    "nodes": [
        {
            "type": "data",
            "data": [
                {"activeShops": 1, "lastUpdated": 4},
                [2, 3],
                {"ID": 5, "Type": 6, "StartDate": 7, "EndDate": 8, "LogoURL": 9, "Name": 10, "Title": 9},
                {"ID": 11, "Type": 6, "StartDate": 12, "EndDate": 13, "LogoURL": 9, "Name": 14, "Title": 9},
                ["Date", "2026-04-01T19:00:24.000Z"],
                52,
                "Featured",
                1568070623,
                None,
                None,
                "Featured Shop",
                420,
                1774638000,
                1775674800,
                "GARAGE GRAB",
            ],
            "uses": {},
        },
        ROOT_PAYLOAD["nodes"][1],
    ],
}


BUNDLE_PAYLOAD = {
    "type": "data",
    "nodes": [
        {"type": "data", "data": [{"unused": 1}, "noop"], "uses": {}},
        {
            "type": "data",
            "data": [
                {"shopName": 1, "isRLCS": 2, "groups": 3, "items": 14},
                "HATSUNE MIKU",
                False,
                [4],
                {"name": 5, "price": 6, "items": 7, "endTime": 9},
                "HATSUNE MIKU CYCLONE",
                "1500",
                [8],
                {"thumbnail": 10, "label": 11, "category": 12, "price": -1, "paint": 13, "endTime": 9},
                1774141200,
                "/group-item.png",
                "Cyclone",
                "Body",
                "12",
                [15],
                {"thumbnail": 16, "label": 17, "category": 18, "price": 19, "paint": -1, "endTime": 9},
                "/item.png",
                "Miku Pop",
                "Goal Explosion",
                "800",
            ],
            "uses": {"params": ["id"]},
        },
    ],
}


GARAGE_GRAB_PAYLOAD = {
    "type": "data",
    "nodes": [
        {"type": "data", "data": [{"unused": 1}, "noop"], "uses": {}},
        {
            "type": "data",
            "data": [
                {"shopName": 1, "isRLCS": 2, "groups": 3, "items": 4},
                "GARAGE GRAB",
                False,
                [],
                [5],
                {"thumbnail": 6, "label": 7, "category": 8, "price": 9, "paint": -1, "endTime": 10},
                "/garage-grab.png",
                "Interstellar",
                "Animated Decal",
                "2000",
                1775674800,
            ],
            "uses": {"params": ["id"]},
        },
    ],
}


class TestRocketLeagueStoreService:
    """Tests for RocketLeagueStoreService decoding and model conversion."""

    @pytest.mark.asyncio
    async def test_fetch_store_snapshot_decodes_featured_and_bundle_shops(self):
        """The service should decode active shops and preserve shop ordering."""
        from bot.services.rl_store import RocketLeagueStoreService

        service = RocketLeagueStoreService()
        service._fetch_json = AsyncMock(side_effect=[ROOT_PAYLOAD, BUNDLE_PAYLOAD])

        snapshot = await service.fetch_store_snapshot()

        assert snapshot.last_updated.isoformat() == "2026-03-17T19:00:01+00:00"
        assert [shop.shop_id for shop in snapshot.shops] == [52, 340]

        featured_shop = snapshot.shops[0]
        assert featured_shop.display_name == "Featured Shop"
        assert featured_shop.items[0].label == "Scarab"
        assert featured_shop.items[0].paint_name == "Orange"
        assert featured_shop.items[0].thumbnail_url == "https://rlshop.gg/featured.png"

        bundle_shop = snapshot.shops[1]
        assert bundle_shop.display_name == "HATSUNE MIKU"
        assert bundle_shop.groups[0].name == "HATSUNE MIKU CYCLONE"
        assert bundle_shop.groups[0].price == 1500
        assert bundle_shop.groups[0].items[0].paint_name == "Titanium White"
        assert bundle_shop.items[0].label == "Miku Pop"
        assert bundle_shop.items[0].price == 800

    @pytest.mark.asyncio
    async def test_fetch_store_snapshot_fetches_additional_featured_sections_from_their_own_pages(self):
        """Only the root-matched featured shop should reuse the homepage data node."""
        from bot.services.rl_store import RocketLeagueStoreService

        service = RocketLeagueStoreService()
        service._fetch_json = AsyncMock(side_effect=[MULTI_FEATURED_ROOT_PAYLOAD, GARAGE_GRAB_PAYLOAD])

        snapshot = await service.fetch_store_snapshot()

        assert [shop.shop_id for shop in snapshot.shops] == [52, 420]
        assert snapshot.shops[0].display_name == "Featured Shop"
        assert snapshot.shops[0].items[0].label == "Scarab"
        assert snapshot.shops[1].display_name == "GARAGE GRAB"
        assert snapshot.shops[1].items[0].label == "Interstellar"
        assert [call.args[1] for call in service._fetch_json.await_args_list] == [
            service.ROOT_PATH,
            "/420/__data.json",
        ]

    def test_decode_data_node_handles_sveltekit_references_and_dates(self):
        """The devalue decoder should resolve reference pools and date sentinels."""
        from bot.services.rl_store import RocketLeagueStoreService

        service = RocketLeagueStoreService()

        decoded = service._decode_data_node(ROOT_PAYLOAD, node_index=0)

        assert decoded["activeShops"][0]["Name"] == "Featured Shop"
        assert decoded["activeShops"][1]["ID"] == 340
        assert decoded["lastUpdated"] == "2026-03-17T19:00:01.000Z"

    def test_build_merc_status_text_reports_yes_only_for_exact_merc_body_matches(self):
        """Merc status should ignore Mercedes bodies and non-body Merc cosmetics."""
        from bot.models.rl_store import (
            RocketLeagueStoreGroup,
            RocketLeagueStoreItem,
            RocketLeagueStoreShop,
            RocketLeagueStoreSnapshot,
        )
        from bot.services.rl_store import RocketLeagueStoreService

        service = RocketLeagueStoreService()
        snapshot = RocketLeagueStoreSnapshot(
            last_updated=service._parse_datetime("2026-03-17T19:00:01.000Z"),
            shops=[
                RocketLeagueStoreShop(
                    shop_id=1,
                    name="Featured",
                    shop_type="Featured",
                    items=[
                        RocketLeagueStoreItem(label="Merc", category="Body"),
                        RocketLeagueStoreItem(label="Mercedes-AMG GT 63 S", category="Body"),
                        RocketLeagueStoreItem(label="Merc: Warlock", category="Decal"),
                    ],
                    groups=[
                        RocketLeagueStoreGroup(
                            name="Bundle",
                            items=[RocketLeagueStoreItem(label="Merc", category="Body")],
                        )
                    ],
                )
            ],
        )

        assert service.build_merc_status_text(snapshot) == "Merc car on the shop: yes (Merc)."

    def test_build_source_url_text_returns_non_unfurled_rlshop_url(self):
        """Source URL helper should expose the rlshop.gg URL wrapped to avoid embeds."""
        from bot.services.rl_store import RocketLeagueStoreService

        service = RocketLeagueStoreService()

        assert service.build_source_url_text() == "<https://rlshop.gg>"
