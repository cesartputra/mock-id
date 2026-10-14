from dataclasses import dataclass


@dataclass
class PuzzleChallenge:
    id: str
    owner_id: str
    target_x: int
    expires: float
    attempts: int = 0


@dataclass
class PuzzleReceipt:
    owner_id: str
    expires: float
