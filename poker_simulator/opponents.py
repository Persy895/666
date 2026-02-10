"""
Opponent modeling: realistic villain profiles, ranges, and behavior.
"""

import random
from .models import (
    Card, Rank, Suit, VillainProfile, PlayerType, Position,
    ActionType, PlayerAction, Street, HandState,
)


# =============================================================================
# Pre-built villain profiles (realistic stat lines)
# =============================================================================

VILLAIN_TEMPLATES: dict[PlayerType, dict] = {
    PlayerType.TAG: {
        "vpip": 22, "pfr": 18, "aggression_factor": 3.0,
        "fold_to_cbet": 45, "three_bet_pct": 8, "fold_to_3bet": 55,
        "wtsd": 26,
        "notes": "Tight-Aggressive: เล่นน้อยมือ แต่เมื่อเล่นจะก้าวร้าว. "
                 "Raise เป็นหลัก ไม่ค่อย limp. Respects raises.",
    },
    PlayerType.LAG: {
        "vpip": 30, "pfr": 25, "aggression_factor": 4.0,
        "fold_to_cbet": 35, "three_bet_pct": 12, "fold_to_3bet": 40,
        "wtsd": 28,
        "notes": "Loose-Aggressive: เล่นหลายมือ ก้าวร้าวมาก. "
                 "3-bet บ่อย, barrel หลาย street. ยากที่จะอ่าน.",
    },
    PlayerType.NIT: {
        "vpip": 12, "pfr": 10, "aggression_factor": 2.0,
        "fold_to_cbet": 60, "three_bet_pct": 4, "fold_to_3bet": 70,
        "wtsd": 22,
        "notes": "Nit: เล่นแน่นมาก รอแต่มือพรีเมียม. "
                 "เมื่อ raise = มือแข็งแกร่งมากเกือบเสมอ. Exploitable by stealing.",
    },
    PlayerType.FISH: {
        "vpip": 45, "pfr": 10, "aggression_factor": 1.0,
        "fold_to_cbet": 55, "three_bet_pct": 3, "fold_to_3bet": 50,
        "wtsd": 35,
        "notes": "Fish/Recreational: เล่นมากมือ limp บ่อย. "
                 "ชอบดูฟลอบ ไม่ค่อย fold top pair. ให้ value เมื่อเราแข็ง.",
    },
    PlayerType.CALLING_STATION: {
        "vpip": 40, "pfr": 8, "aggression_factor": 0.7,
        "fold_to_cbet": 30, "three_bet_pct": 2, "fold_to_3bet": 35,
        "wtsd": 42,
        "notes": "Calling Station: call ทุกอย่าง ไม่ค่อยพับ ไม่ค่อย raise. "
                 "ห้ามบลัฟ! Value bet หนักเมื่อเราแข็ง.",
    },
    PlayerType.MANIAC: {
        "vpip": 50, "pfr": 35, "aggression_factor": 5.5,
        "fold_to_cbet": 25, "three_bet_pct": 18, "fold_to_3bet": 25,
        "wtsd": 30,
        "notes": "Maniac: raise และ re-raise บ่อยมาก. Range กว้างมาก. "
                 "Trap ด้วยมือแข็ง. อย่า overadjust.",
    },
    PlayerType.REG: {
        "vpip": 24, "pfr": 20, "aggression_factor": 3.2,
        "fold_to_cbet": 42, "three_bet_pct": 9, "fold_to_3bet": 52,
        "wtsd": 25,
        "notes": "Regular: ผู้เล่นประจำที่เล่นดีพอสมควร. "
                 "มี fundamentals ดี. ระวังเมื่อเขา deviate จาก normal line.",
    },
}


def create_villain(
    name: str,
    position: Position,
    player_type: PlayerType,
    stack: float = 500.0,
) -> VillainProfile:
    """Create a villain with realistic stats based on type."""
    template = VILLAIN_TEMPLATES.get(player_type, VILLAIN_TEMPLATES[PlayerType.TAG])
    # Add some variance to make it realistic
    variance = lambda v, pct=10: max(0, v + random.uniform(-pct/2, pct/2))

    return VillainProfile(
        name=name,
        position=position,
        player_type=player_type,
        stack=stack,
        vpip=variance(template["vpip"], 5),
        pfr=variance(template["pfr"], 4),
        aggression_factor=max(0.3, template["aggression_factor"] + random.uniform(-0.5, 0.5)),
        fold_to_cbet=variance(template["fold_to_cbet"], 8),
        three_bet_pct=max(0, variance(template["three_bet_pct"], 3)),
        fold_to_3bet=variance(template["fold_to_3bet"], 8),
        wtsd=variance(template["wtsd"], 5),
        notes=template["notes"],
    )


# =============================================================================
# Range construction by player type and position
# =============================================================================

# Top hands ranked (simplified). Using shorthand like "AA", "AKs", "AKo"
HAND_TIERS = {
    1: ["AA", "KK"],
    2: ["QQ", "JJ", "AKs"],
    3: ["AKo", "TT", "AQs"],
    4: ["AQo", "AJs", "99", "KQs"],
    5: ["ATs", "KJs", "88", "KQo", "QJs"],
    6: ["AJo", "KTs", "QTs", "JTs", "77", "A9s", "A8s"],
    7: ["ATo", "KJo", "66", "55", "A7s", "A6s", "A5s", "K9s", "Q9s", "J9s", "T9s"],
    8: ["A4s", "A3s", "A2s", "K8s", "K7s", "44", "33", "22", "QJo", "98s", "87s", "76s"],
    9: ["KTo", "QTo", "JTo", "97s", "86s", "75s", "65s", "54s", "K6s", "K5s"],
    10: ["K4s-K2s", "Q8s-Q6s", "J8s", "T8s", "96s", "85s", "74s", "64s", "53s", "43s"],
}


def _expand_hand_notation(hand: str) -> list[tuple[str, str, bool]]:
    """
    Expand hand notation to (rank1, rank2, suited).
    E.g. 'AKs' -> [('A','K',True)], 'AKo' -> [('A','K',False)]
    """
    if "-" in hand:
        # Range like K4s-K2s
        return []  # simplified - skip ranges for now

    if len(hand) == 2:  # Pairs like "AA"
        return [(hand[0], hand[1], False)]
    suited = hand[2] == "s"
    return [(hand[0], hand[1], suited)]


def build_range_cards(
    player_type: PlayerType,
    position: Position,
) -> list[list[Card]]:
    """
    Build a list of concrete [Card, Card] hands based on player type and position.
    Returns all suited/offsuit combos for hands in range.
    """
    # Determine how many tiers to include based on player type
    tier_limits = {
        PlayerType.NIT: 3,
        PlayerType.TAG: 5,
        PlayerType.REG: 6,
        PlayerType.LAG: 8,
        PlayerType.FISH: 9,
        PlayerType.CALLING_STATION: 9,
        PlayerType.MANIAC: 10,
    }

    # Position adjustment: earlier position = tighter
    position_adjustment = {
        Position.UTG: -2, Position.UTG1: -2, Position.UTG2: -1,
        Position.LJ: -1, Position.HJ: 0, Position.CO: 0,
        Position.BTN: 1, Position.SB: 0, Position.BB: 1,
    }

    max_tier = tier_limits.get(player_type, 6)
    max_tier += position_adjustment.get(position, 0)
    max_tier = max(1, min(10, max_tier))

    rank_map = {
        "A": Rank.ACE, "K": Rank.KING, "Q": Rank.QUEEN, "J": Rank.JACK,
        "T": Rank.TEN, "9": Rank.NINE, "8": Rank.EIGHT, "7": Rank.SEVEN,
        "6": Rank.SIX, "5": Rank.FIVE, "4": Rank.FOUR, "3": Rank.THREE,
        "2": Rank.TWO,
    }
    suits_list = [Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES]

    hands = []
    for tier in range(1, max_tier + 1):
        for hand_str in HAND_TIERS.get(tier, []):
            expanded = _expand_hand_notation(hand_str)
            for r1_str, r2_str, is_suited in expanded:
                r1 = rank_map.get(r1_str)
                r2 = rank_map.get(r2_str)
                if not r1 or not r2:
                    continue

                if r1 == r2:
                    # Pair: all 6 combos
                    for i in range(4):
                        for j in range(i + 1, 4):
                            hands.append([
                                Card(r1, suits_list[i]),
                                Card(r2, suits_list[j]),
                            ])
                elif is_suited:
                    # Suited: 4 combos
                    for s in suits_list:
                        hands.append([Card(r1, s), Card(r2, s)])
                else:
                    # Offsuit: 12 combos
                    for s1 in suits_list:
                        for s2 in suits_list:
                            if s1 != s2:
                                hands.append([Card(r1, s1), Card(r2, s2)])

    return hands


def describe_range_text(player_type: PlayerType, position: Position) -> str:
    """Human-readable range description."""
    tier_limits = {
        PlayerType.NIT: 3,
        PlayerType.TAG: 5,
        PlayerType.REG: 6,
        PlayerType.LAG: 8,
        PlayerType.FISH: 9,
        PlayerType.CALLING_STATION: 9,
        PlayerType.MANIAC: 10,
    }
    position_adjustment = {
        Position.UTG: -2, Position.UTG1: -2, Position.UTG2: -1,
        Position.LJ: -1, Position.HJ: 0, Position.CO: 0,
        Position.BTN: 1, Position.SB: 0, Position.BB: 1,
    }

    max_tier = tier_limits.get(player_type, 6)
    max_tier += position_adjustment.get(position, 0)
    max_tier = max(1, min(10, max_tier))

    hands = []
    for tier in range(1, max_tier + 1):
        hands.extend(HAND_TIERS.get(tier, []))

    return ", ".join(hands[:20]) + ("..." if len(hands) > 20 else "")


# =============================================================================
# Villain action generation (simple GTO-ish behavior)
# =============================================================================

def generate_villain_preflop_action(
    villain: VillainProfile,
    hand_state: HandState,
    facing_raise: bool = False,
    raise_amount: float = 0.0,
) -> PlayerAction:
    """Generate a realistic preflop action for a villain."""
    roll = random.random() * 100

    if facing_raise:
        # Facing a raise
        fold_pct = 100 - villain.vpip
        call_pct = villain.vpip - villain.three_bet_pct
        three_bet_pct = villain.three_bet_pct

        if roll < fold_pct:
            return PlayerAction(villain.name, ActionType.FOLD, 0, Street.PREFLOP)
        elif roll < fold_pct + call_pct:
            return PlayerAction(villain.name, ActionType.CALL, raise_amount, Street.PREFLOP)
        else:
            three_bet_size = raise_amount * 3
            return PlayerAction(villain.name, ActionType.RAISE, three_bet_size, Street.PREFLOP)
    else:
        # No raise yet (open action)
        fold_pct = 100 - villain.vpip
        limp_pct = villain.vpip - villain.pfr
        raise_pct = villain.pfr

        if roll < fold_pct:
            return PlayerAction(villain.name, ActionType.FOLD, 0, Street.PREFLOP)
        elif roll < fold_pct + limp_pct:
            return PlayerAction(villain.name, ActionType.CALL, 3, Street.PREFLOP)  # limp = BB
        else:
            open_size = random.choice([8, 9, 10, 12])  # typical 1/3 open sizes
            return PlayerAction(villain.name, ActionType.RAISE, open_size, Street.PREFLOP)


def generate_villain_postflop_action(
    villain: VillainProfile,
    hand_state: HandState,
    facing_bet: bool = False,
    bet_amount: float = 0.0,
    is_ip: bool = False,
) -> PlayerAction:
    """Generate a realistic postflop action for a villain."""
    street = hand_state.current_street
    roll = random.random() * 100
    pot = hand_state.pot

    if facing_bet:
        # Facing a bet
        # Use fold_to_cbet as baseline for facing bets
        fold_base = villain.fold_to_cbet
        # Calling stations fold less
        if villain.player_type == PlayerType.CALLING_STATION:
            fold_base *= 0.5
        elif villain.player_type == PlayerType.MANIAC:
            fold_base *= 0.3
        elif villain.player_type == PlayerType.FISH:
            fold_base *= 0.7

        # Adjust for bet size relative to pot
        if bet_amount > pot * 0.75:
            fold_base *= 1.2  # fold more vs big bets
        elif bet_amount < pot * 0.4:
            fold_base *= 0.7  # fold less vs small bets

        raise_pct = villain.aggression_factor * 3  # rough
        if villain.player_type in (PlayerType.CALLING_STATION, PlayerType.FISH):
            raise_pct = max(2, raise_pct * 0.3)

        call_pct = 100 - fold_base - raise_pct

        if roll < fold_base:
            return PlayerAction(villain.name, ActionType.FOLD, 0, street)
        elif roll < fold_base + call_pct:
            return PlayerAction(villain.name, ActionType.CALL, bet_amount, street)
        else:
            raise_size = bet_amount * random.uniform(2.2, 3.0)
            return PlayerAction(villain.name, ActionType.RAISE, min(raise_size, villain.stack), street)
    else:
        # Not facing a bet (can check or bet)
        check_pct = 100 - (villain.aggression_factor * 10)
        if villain.player_type in (PlayerType.CALLING_STATION, PlayerType.FISH):
            check_pct = 80
        elif villain.player_type == PlayerType.MANIAC:
            check_pct = 30
        elif villain.player_type == PlayerType.NIT:
            check_pct = 65

        check_pct = max(20, min(90, check_pct))

        if roll < check_pct:
            return PlayerAction(villain.name, ActionType.CHECK, 0, street)
        else:
            bet_size = pot * random.choice([0.33, 0.5, 0.67, 0.75])
            return PlayerAction(villain.name, ActionType.BET, min(bet_size, villain.stack), street)
