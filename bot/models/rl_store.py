"""
Rocket League store data models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


PAINT_NAME_BY_CODE: dict[str, str] = {
    "0": "Unpainted",
    "1": "Crimson",
    "2": "Lime",
    "3": "Black",
    "4": "Sky Blue",
    "5": "Cobalt",
    "6": "Burnt Sienna",
    "7": "Forest Green",
    "8": "Purple",
    "9": "Pink",
    "10": "Orange",
    "11": "Grey",
    "12": "Titanium White",
    "13": "Saffron",
    "14": "Gold",
}


@dataclass(frozen=True)
class RocketLeagueStoreItem:
    """Single store item entry."""

    label: str
    category: str
    price: Optional[int] = None
    paint: Optional[str] = None
    thumbnail_url: Optional[str] = None
    end_time: Optional[datetime] = None

    @property
    def paint_name(self) -> Optional[str]:
        """Return a readable paint name when a paint code is present."""
        if self.paint is None:
            return None
        return PAINT_NAME_BY_CODE.get(str(self.paint), f"Paint {self.paint}")


@dataclass(frozen=True)
class RocketLeagueStoreGroup:
    """Bundle/group entry containing one or more store items."""

    name: str
    items: list[RocketLeagueStoreItem] = field(default_factory=list)
    price: Optional[int] = None
    end_time: Optional[datetime] = None


@dataclass(frozen=True)
class RocketLeagueStoreShop:
    """Top-level active Rocket League shop section."""

    shop_id: int
    name: str
    shop_type: str
    title: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    groups: list[RocketLeagueStoreGroup] = field(default_factory=list)
    items: list[RocketLeagueStoreItem] = field(default_factory=list)
    is_rlcs: bool = False

    @property
    def display_name(self) -> str:
        """Return the preferred shop name for UI display."""
        return self.name or self.title or f"Shop {self.shop_id}"


@dataclass(frozen=True)
class RocketLeagueStoreSnapshot:
    """Complete snapshot of today's active Rocket League shops."""

    last_updated: datetime
    shops: list[RocketLeagueStoreShop] = field(default_factory=list)
    source_url: str = "https://rlshop.gg"

