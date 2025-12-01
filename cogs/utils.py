from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set, Optional

import time

# IDs de rôles
ROLE_MEMBRES_ID = 1280235478733422673
ROLE_TEST_ID = 1358771105980088390
ROLE_ADMIN_ID = 1280396795046006836

# IDs de canaux
CHANNEL_PING_ID = 1358772372831994040
CHANNEL_DEFENSE_ID = 1327548733398843413
CHANNEL_LEADERBOARD_ID = 1419025350641582182
CHANNEL_SNAPSHOT_ID = 1421100876977803274  # pas utilisé pour l'instant

# Emoji custom pour le bouton Ping
PING_BUTTON_EMOJI_ID = 1327724142253838390

PING_COOLDOWN_SECONDS = 30


@dataclass
class AlertData:
    message_id: int
    channel_id: int
    guild_id: int
    triggered_by_id: int
    role_kind: str  # "members" ou "test"
    created_timestamp: int
    state: str = "in_progress"  # "in_progress" | "won" | "lost"
    incomplete: bool = False
    defenders: Set[int] = field(default_factory=set)
    attacker: Optional[str] = None


@dataclass
class BotState:
    alerts: Dict[int, AlertData] = field(default_factory=dict)
    ping_counts: Dict[int, int] = field(default_factory=dict)
    defense_counts: Dict[int, int] = field(default_factory=dict)
    leaderboard_ping_message_id: Optional[int] = None
    leaderboard_def_message_id: Optional[int] = None
    last_ping_timestamp: Optional[float] = None


def get_state(bot) -> BotState:
    if not hasattr(bot, "bot_state"):
        bot.bot_state = BotState()
    return bot.bot_state


def now_ts() -> int:
    return int(time.time())


def format_attack_time(ts: int) -> str:
    # Affichage Discord : <t:timestamp:f> -> date/heure locale de l'utilisateur
    return f"<t:{ts}:f>"
