"""
Core data models for the poker decision simulator.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# Enums
# =============================================================================

class Suit(Enum):
    HEARTS = "h"
    DIAMONDS = "d"
    CLUBS = "c"
    SPADES = "s"


class Rank(Enum):
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14

    def __str__(self):
        names = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "T"}
        return names.get(self.value, str(self.value))

    def __lt__(self, other):
        return self.value < other.value

    def __le__(self, other):
        return self.value <= other.value

    def __gt__(self, other):
        return self.value > other.value

    def __ge__(self, other):
        return self.value >= other.value


class HandRanking(Enum):
    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8
    ROYAL_FLUSH = 9


class BoardTexture(Enum):
    """S/B/C classification per street."""
    S = "S"  # Nut / สัมพันธ์กับไพ่ที่ดีที่สุด
    B = "B"  # Good but not nut / ดีแต่ไม่ใช่ nut
    C = "C"  # Unconnected / ไม่สัมพันธ์


class Street(Enum):
    PREFLOP = "Preflop"
    FLOP = "Flop"
    TURN = "Turn"
    RIVER = "River"


class PlayerType(Enum):
    TAG = "TAG"                      # Tight-Aggressive
    LAG = "LAG"                      # Loose-Aggressive
    NIT = "NIT"                      # Nit
    FISH = "FISH"                    # Fish / Recreational
    CALLING_STATION = "CALLING_STATION"  # Calling Station
    MANIAC = "MANIAC"                # Maniac
    REG = "REG"                      # Regular
    UNKNOWN = "UNKNOWN"              # Unknown


class Position(Enum):
    UTG = "UTG"
    UTG1 = "UTG+1"
    UTG2 = "UTG+2"
    LJ = "LJ"       # Lojack
    HJ = "HJ"       # Hijack
    CO = "CO"        # Cutoff
    BTN = "BTN"      # Button
    SB = "SB"        # Small Blind
    BB = "BB"        # Big Blind


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all-in"


# =============================================================================
# Card
# =============================================================================

@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit

    def __str__(self):
        return f"{self.rank}{self.suit.value}"

    def __repr__(self):
        return self.__str__()

    @staticmethod
    def from_str(s: str) -> "Card":
        """Parse 'Ah', 'Td', '2c' etc."""
        s = s.strip()
        rank_map = {
            "A": Rank.ACE, "K": Rank.KING, "Q": Rank.QUEEN, "J": Rank.JACK,
            "T": Rank.TEN, "10": Rank.TEN,
            "9": Rank.NINE, "8": Rank.EIGHT, "7": Rank.SEVEN, "6": Rank.SIX,
            "5": Rank.FIVE, "4": Rank.FOUR, "3": Rank.THREE, "2": Rank.TWO,
        }
        suit_map = {"h": Suit.HEARTS, "d": Suit.DIAMONDS, "c": Suit.CLUBS, "s": Suit.SPADES}
        rank_str = s[:-1]
        suit_str = s[-1].lower()
        return Card(rank_map[rank_str], suit_map[suit_str])

    @property
    def numeric_rank(self) -> int:
        return self.rank.value


# =============================================================================
# Player Action
# =============================================================================

@dataclass
class PlayerAction:
    actor: str
    action_type: ActionType
    amount: float = 0.0
    street: Street = Street.PREFLOP

    def __str__(self):
        if self.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
            return f"{self.actor} {self.action_type.value} ${self.amount:.0f}"
        return f"{self.actor} {self.action_type.value}"


# =============================================================================
# Opponent Profile
# =============================================================================

@dataclass
class VillainProfile:
    """Realistic villain profile with stats."""
    name: str
    position: Position
    player_type: PlayerType
    stack: float               # in dollars
    vpip: float = 0.0         # %
    pfr: float = 0.0          # %
    aggression_factor: float = 0.0
    fold_to_cbet: float = 0.0  # %
    three_bet_pct: float = 0.0  # %
    fold_to_3bet: float = 0.0   # %
    wtsd: float = 0.0           # Went to Showdown %
    notes: str = ""

    @property
    def stack_bb(self) -> float:
        return self.stack / 3.0  # $3 BB

    def describe(self) -> str:
        return (
            f"{self.name} ({self.position.value}) - {self.player_type.value}\n"
            f"  Stack: ${self.stack:.0f} ({self.stack_bb:.0f} BB)\n"
            f"  VPIP/PFR: {self.vpip:.0f}/{self.pfr:.0f}  |  "
            f"3Bet: {self.three_bet_pct:.0f}%  |  AF: {self.aggression_factor:.1f}\n"
            f"  Fold to CBet: {self.fold_to_cbet:.0f}%  |  WTSD: {self.wtsd:.0f}%"
        )


# =============================================================================
# Hand State (the full game state)
# =============================================================================

@dataclass
class HandState:
    """Complete state of a single hand."""
    # Hero info
    hero_cards: list[Card] = field(default_factory=list)
    hero_position: Position = Position.BTN
    hero_stack: float = 500.0

    # Board
    flop: list[Card] = field(default_factory=list)
    turn_card: Optional[Card] = None
    river_card: Optional[Card] = None

    # Game state
    pot: float = 0.0
    current_street: Street = Street.PREFLOP
    current_bet: float = 0.0  # current bet to call

    # Villains
    villains: list[VillainProfile] = field(default_factory=list)
    active_villains: list[str] = field(default_factory=list)  # names of still-in villains

    # History
    action_history: list[PlayerAction] = field(default_factory=list)

    # S/B/C path
    texture_path: list[BoardTexture] = field(default_factory=list)

    @property
    def board_cards(self) -> list[Card]:
        cards = list(self.flop)
        if self.turn_card:
            cards.append(self.turn_card)
        if self.river_card:
            cards.append(self.river_card)
        return cards

    @property
    def texture_code(self) -> str:
        """Returns e.g. 'S', 'SB', 'SBC'"""
        return "".join(t.value for t in self.texture_path)

    @property
    def effective_stack(self) -> float:
        """Effective stack = min of hero and active villains."""
        if not self.active_villains:
            return self.hero_stack
        villain_stacks = [
            v.stack for v in self.villains if v.name in self.active_villains
        ]
        if not villain_stacks:
            return self.hero_stack
        return min(self.hero_stack, min(villain_stacks))

    @property
    def spr(self) -> float:
        """Stack-to-Pot Ratio."""
        if self.pot == 0:
            return float("inf")
        return self.effective_stack / self.pot

    def pot_odds(self, call_amount: float) -> float:
        """Pot odds as a percentage: call / (pot + call)."""
        if call_amount <= 0:
            return 0.0
        return call_amount / (self.pot + call_amount) * 100

    def mdf(self, bet_amount: float) -> float:
        """Minimum Defense Frequency: pot / (pot + bet)."""
        if bet_amount <= 0:
            return 100.0
        return self.pot / (self.pot + bet_amount) * 100
