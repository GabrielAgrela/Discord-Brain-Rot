"""
Service for fetching today's Rocket League item shop data.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp

from bot.models import (
    RocketLeagueStoreGroup,
    RocketLeagueStoreItem,
    RocketLeagueStoreShop,
    RocketLeagueStoreSnapshot,
)


logger = logging.getLogger(__name__)


class RocketLeagueStoreService:
    """Fetch and decode Rocket League shop data from rlshop.gg."""

    BASE_URL = "https://rlshop.gg"
    ROOT_PATH = "/__data.json"

    def __init__(self, timeout_seconds: int = 15):
        """
        Initialize the Rocket League store service.

        Args:
            timeout_seconds: Total request timeout for upstream calls.
        """
        self.timeout_seconds = timeout_seconds

    async def fetch_store_snapshot(self) -> RocketLeagueStoreSnapshot:
        """
        Fetch the current active Rocket League shops.

        Returns:
            A decoded store snapshot ordered like the upstream site.
        """
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        headers = {"Accept": "application/json"}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            root_payload = await self._fetch_json(session, self.ROOT_PATH)
            root_meta = self._decode_data_node(root_payload, node_index=0)
            featured_shop_data = self._decode_data_node(root_payload, node_index=1)

            active_shops = root_meta.get("activeShops") or []
            last_updated = self._parse_datetime(root_meta.get("lastUpdated"))
            if last_updated is None:
                raise ValueError("Rocket League store payload missing lastUpdated timestamp")

            non_featured = [
                shop for shop in active_shops
                if not self._is_featured_shop(shop)
            ]
            fetch_tasks = {
                int(shop["ID"]): asyncio.create_task(self._fetch_shop_data(session, int(shop["ID"])))
                for shop in non_featured
            }

            shops: list[RocketLeagueStoreShop] = []
            for shop_meta in active_shops:
                try:
                    if self._is_featured_shop(shop_meta):
                        shop_data = featured_shop_data
                    else:
                        shop_data = await fetch_tasks[int(shop_meta["ID"])]
                    shops.append(self._build_shop(shop_meta, shop_data))
                except Exception:
                    logger.exception(
                        "Failed to load Rocket League shop %s (%s)",
                        shop_meta.get("Name"),
                        shop_meta.get("ID"),
                    )

            if not shops:
                raise RuntimeError("No active Rocket League shops could be loaded")

            return RocketLeagueStoreSnapshot(
                last_updated=last_updated,
                shops=shops,
                source_url=self.BASE_URL,
            )

    def find_merc_body_items(
        self,
        snapshot: RocketLeagueStoreSnapshot,
    ) -> list[RocketLeagueStoreItem]:
        """
        Return all shop items that look like a Merc body.

        Args:
            snapshot: Store snapshot to inspect.

        Returns:
            Matching Merc body items across standalone and bundle entries.
        """
        merc_items: list[RocketLeagueStoreItem] = []
        for shop in snapshot.shops:
            merc_items.extend(item for item in shop.items if self._is_merc_body_item(item))
            for group in shop.groups:
                merc_items.extend(item for item in group.items if self._is_merc_body_item(item))
        return merc_items

    def build_merc_status_text(self, snapshot: RocketLeagueStoreSnapshot) -> str:
        """
        Build a short yes/no summary for Merc availability.

        Args:
            snapshot: Store snapshot to inspect.

        Returns:
            Human-readable Merc presence text.
        """
        merc_items = self.find_merc_body_items(snapshot)
        if merc_items:
            labels = ", ".join(sorted({item.label for item in merc_items})[:3])
            return f"Merc car on the shop: yes ({labels})."
        return "Merc car on the shop: no."

    async def _fetch_shop_data(
        self,
        session: aiohttp.ClientSession,
        shop_id: int,
    ) -> dict[str, Any]:
        """Fetch the decoded node data for a non-featured shop page."""
        payload = await self._fetch_json(session, f"/{shop_id}/__data.json")
        return self._decode_data_node(payload, node_index=1)

    async def _fetch_json(
        self,
        session: aiohttp.ClientSession,
        path: str,
    ) -> dict[str, Any]:
        """Fetch a JSON payload from rlshop.gg."""
        url = f"{self.BASE_URL}{path}"
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.json()

    def _decode_data_node(self, payload: dict[str, Any], node_index: int) -> dict[str, Any]:
        """Decode a SvelteKit devalue-encoded data node."""
        nodes = payload.get("nodes") or []
        if node_index >= len(nodes):
            raise IndexError(f"Missing data node {node_index}")

        pool = nodes[node_index].get("data")
        if not isinstance(pool, list) or not pool:
            raise ValueError(f"Unexpected data node format for node {node_index}")

        memo: dict[int, Any] = {}

        def decode_ref(ref_index: int) -> Any:
            if ref_index == -1:
                return None
            if ref_index in memo:
                return memo[ref_index]

            raw = pool[ref_index]
            if isinstance(raw, list):
                if len(raw) == 2 and raw[0] == "Date":
                    memo[ref_index] = raw[1]
                else:
                    memo[ref_index] = [decode_child(item) for item in raw]
            elif isinstance(raw, dict):
                decoded: dict[str, Any] = {}
                memo[ref_index] = decoded
                decoded.update({key: decode_child(value) for key, value in raw.items()})
            else:
                memo[ref_index] = raw

            return memo[ref_index]

        def decode_child(value: Any) -> Any:
            if value == -1:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return decode_ref(value)
            if isinstance(value, list):
                if len(value) == 2 and value[0] == "Date":
                    return value[1]
                return [decode_child(item) for item in value]
            if isinstance(value, dict):
                return {key: decode_child(child) for key, child in value.items()}
            return value

        decoded_root = decode_ref(0)
        if not isinstance(decoded_root, dict):
            raise ValueError(f"Decoded node {node_index} is not an object")
        return decoded_root

    def _build_shop(
        self,
        shop_meta: dict[str, Any],
        shop_data: dict[str, Any],
    ) -> RocketLeagueStoreShop:
        """Convert upstream shop data into a typed model."""
        return RocketLeagueStoreShop(
            shop_id=int(shop_meta["ID"]),
            name=str(shop_data.get("shopName") or shop_meta.get("Name") or f"Shop {shop_meta['ID']}"),
            shop_type=str(shop_meta.get("Type") or "Unknown"),
            title=shop_meta.get("Title"),
            starts_at=self._parse_datetime(shop_meta.get("StartDate")),
            ends_at=self._parse_datetime(shop_meta.get("EndDate")),
            groups=[self._build_group(group) for group in shop_data.get("groups") or []],
            items=[self._build_item(item) for item in shop_data.get("items") or []],
            is_rlcs=bool(shop_data.get("isRLCS")),
        )

    def _build_group(self, group_data: dict[str, Any]) -> RocketLeagueStoreGroup:
        """Convert upstream group data into a typed model."""
        return RocketLeagueStoreGroup(
            name=str(group_data.get("name") or "Bundle"),
            items=[self._build_item(item) for item in group_data.get("items") or []],
            price=self._parse_int(group_data.get("price")),
            end_time=self._parse_datetime(group_data.get("endTime")),
        )

    def _build_item(self, item_data: dict[str, Any]) -> RocketLeagueStoreItem:
        """Convert upstream item data into a typed model."""
        return RocketLeagueStoreItem(
            label=str(item_data.get("label") or "Unknown Item"),
            category=str(item_data.get("category") or "Unknown"),
            price=self._parse_int(item_data.get("price")),
            paint=str(item_data.get("paint")) if item_data.get("paint") is not None else None,
            thumbnail_url=self._normalize_thumbnail_url(item_data.get("thumbnail")),
            end_time=self._parse_datetime(item_data.get("endTime")),
        )

    def _normalize_thumbnail_url(self, value: Any) -> Optional[str]:
        """Normalize relative rlshop.gg image paths into absolute URLs."""
        if not value:
            return None

        thumbnail = str(value)
        if thumbnail.startswith("http://") or thumbnail.startswith("https://"):
            return thumbnail
        if thumbnail.startswith("/"):
            return f"{self.BASE_URL}{thumbnail}"
        return f"{self.BASE_URL}/{thumbnail.lstrip('./')}"

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse either unix timestamps or ISO datetime strings."""
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000.0
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError(f"Unsupported datetime value: {value!r}")

    def _parse_int(self, value: Any) -> Optional[int]:
        """Parse an integer field when upstream provides a numeric string."""
        if value in (None, ""):
            return None
        return int(value)

    def _is_merc_body_item(self, item: RocketLeagueStoreItem) -> bool:
        """Return whether a store item appears to be the Merc car body."""
        return item.category.strip().lower() == "body" and "merc" in item.label.strip().lower()

    def _is_featured_shop(self, shop_meta: dict[str, Any]) -> bool:
        """Return whether this shop uses the root featured-shop page data."""
        return str(shop_meta.get("Type")) == "Featured"
