from dataclasses import dataclass, field

@dataclass
class Player:
    user_id: int
    cls: str | None = None

@dataclass
class Team:
    id: int
    players: tuple[Player, Player, Player]

class State:
    def __init__(self):
        self.players: list[Player] = []
        self.teams: list[Team] = []
        self.embed_message_id: int | None = None

    def reset(self):
        self.players.clear()
        self.teams.clear()
        self.embed_message_id = None

STATE = State()
