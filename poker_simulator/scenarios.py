"""
Hand scenario generator.
Deals cards, creates villains, generates realistic preflop/postflop action.
"""

import random
from typing import Optional

from .models import (
    Card, Rank, Suit, Street, Position, ActionType, PlayerAction,
    HandState, VillainProfile, PlayerType, BoardTexture,
)
from .opponents import (
    create_villain, generate_villain_preflop_action,
    generate_villain_postflop_action,
)
from .classifier import classify_hand_vs_board
from .evaluator import evaluate_hand, hand_rank_name


# =============================================================================
# Deck management
# =============================================================================

def make_full_deck() -> list[Card]:
    deck = []
    for suit in Suit:
        for rank in Rank:
            deck.append(Card(rank, suit))
    return deck


def shuffle_deck(exclude: list[Card] = None) -> list[Card]:
    deck = make_full_deck()
    if exclude:
        excluded_set = {(c.rank, c.suit) for c in exclude}
        deck = [c for c in deck if (c.rank, c.suit) not in excluded_set]
    random.shuffle(deck)
    return deck


# =============================================================================
# Position order for 9-max
# =============================================================================

ALL_POSITIONS_9MAX = [
    Position.UTG, Position.UTG1, Position.UTG2,
    Position.LJ, Position.HJ, Position.CO,
    Position.BTN, Position.SB, Position.BB,
]


def positions_after(pos: Position) -> list[Position]:
    """Positions that act after given position preflop."""
    idx = ALL_POSITIONS_9MAX.index(pos)
    return ALL_POSITIONS_9MAX[idx + 1:]


def postflop_order(active_positions: list[Position]) -> list[Position]:
    """
    Postflop order: SB, BB, UTG, ..., BTN.
    Filter to only active positions.
    """
    postflop_seq = [
        Position.SB, Position.BB,
        Position.UTG, Position.UTG1, Position.UTG2,
        Position.LJ, Position.HJ, Position.CO, Position.BTN,
    ]
    return [p for p in postflop_seq if p in active_positions]


# =============================================================================
# Scenario Generator
# =============================================================================

class ScenarioGenerator:
    """Generates complete poker hand scenarios."""

    def __init__(
        self,
        stakes: tuple[float, float] = (1.0, 3.0),
        effective_stack: float = 500.0,
        hero_vpip_range: float = 15.0,
    ):
        self.sb = stakes[0]
        self.bb = stakes[1]
        self.effective_stack = effective_stack
        self.hero_vpip_range = hero_vpip_range
        self.deck: list[Card] = []
        self.dealt_cards: list[Card] = []

    def generate_hand(
        self,
        hero_position: Optional[Position] = None,
        hero_cards: Optional[list[Card]] = None,
        num_villains: int = 0,
        villain_types: Optional[list[PlayerType]] = None,
    ) -> HandState:
        """
        Generate a new hand scenario.
        If hero_position/hero_cards not specified, randomly assign.
        """
        # Reset deck
        self.dealt_cards = []

        # Hero position
        if hero_position is None:
            hero_position = random.choice(ALL_POSITIONS_9MAX)

        # Hero cards
        if hero_cards is None:
            self.deck = shuffle_deck()
            hero_cards = [self.deck.pop(), self.deck.pop()]
            self.dealt_cards.extend(hero_cards)
        else:
            self.deck = shuffle_deck(exclude=hero_cards)
            self.dealt_cards.extend(hero_cards)

        # Create villains
        if num_villains == 0:
            num_villains = random.randint(1, 3)

        available_positions = [p for p in ALL_POSITIONS_9MAX if p != hero_position]
        random.shuffle(available_positions)

        villains = []
        for i in range(min(num_villains, len(available_positions))):
            pos = available_positions[i]
            if villain_types and i < len(villain_types):
                v_type = villain_types[i]
            else:
                v_type = random.choice([
                    PlayerType.TAG, PlayerType.LAG, PlayerType.NIT,
                    PlayerType.FISH, PlayerType.CALLING_STATION, PlayerType.REG,
                ])
            stack_variance = random.uniform(0.7, 1.5)
            villain = create_villain(
                name=f"Villain_{pos.value}",
                position=pos,
                player_type=v_type,
                stack=self.effective_stack * stack_variance,
            )
            villains.append(villain)

        # Create hand state
        state = HandState(
            hero_cards=hero_cards,
            hero_position=hero_position,
            hero_stack=self.effective_stack,
            pot=self.sb + self.bb,  # Start with blinds
            current_street=Street.PREFLOP,
            villains=villains,
            active_villains=[v.name for v in villains],
        )

        return state

    def deal_flop(self, state: HandState) -> list[Card]:
        """Deal 3 flop cards."""
        flop = [self.deck.pop() for _ in range(3)]
        state.flop = flop
        state.current_street = Street.FLOP
        self.dealt_cards.extend(flop)

        # Classify
        texture, _, _ = classify_hand_vs_board(state.hero_cards, flop)
        state.texture_path.append(texture)

        return flop

    def deal_turn(self, state: HandState) -> Card:
        """Deal 1 turn card."""
        turn = self.deck.pop()
        state.turn_card = turn
        state.current_street = Street.TURN
        self.dealt_cards.append(turn)

        # Classify
        board = state.flop + [turn]
        texture, _, _ = classify_hand_vs_board(state.hero_cards, board)
        state.texture_path.append(texture)

        return turn

    def deal_river(self, state: HandState) -> Card:
        """Deal 1 river card."""
        river = self.deck.pop()
        state.river_card = river
        state.current_street = Street.RIVER
        self.dealt_cards.append(river)

        # Classify
        board = state.flop + [state.turn_card, river]
        texture, _, _ = classify_hand_vs_board(state.hero_cards, board)
        state.texture_path.append(texture)

        return river

    def generate_preflop_action(
        self,
        state: HandState,
    ) -> list[PlayerAction]:
        """
        Generate villain preflop actions up to hero's turn to act.
        Returns list of actions that happened before hero.
        """
        actions = []
        hero_pos = state.hero_position

        # Determine acting order preflop: UTG -> ... -> BB
        # But we rearrange: positions before hero act first
        all_pos = ALL_POSITIONS_9MAX.copy()
        # Preflop order: UTG, UTG1, UTG2, LJ, HJ, CO, BTN, SB, BB
        hero_idx = all_pos.index(hero_pos)

        current_raise = self.bb
        has_raise = False

        # Track preflop investments: blinds are already posted
        state.street_invested = {}
        for v in state.villains:
            if v.position == Position.SB:
                state.street_invested[v.name] = self.sb
            elif v.position == Position.BB:
                state.street_invested[v.name] = self.bb
            else:
                state.street_invested[v.name] = 0.0
        # Hero blind tracking
        if state.hero_position == Position.SB:
            state.street_invested["Hero"] = self.sb
        elif state.hero_position == Position.BB:
            state.street_invested["Hero"] = self.bb
        else:
            state.street_invested["Hero"] = 0.0

        # Players acting before hero
        for pos in all_pos:
            if pos == hero_pos:
                break  # Stop - hero's turn

            villain = next((v for v in state.villains if v.position == pos), None)
            if villain is None:
                continue
            if villain.name not in state.active_villains:
                continue

            action = generate_villain_preflop_action(
                villain, state,
                facing_raise=has_raise,
                raise_amount=current_raise,
            )
            actions.append(action)

            already_in = state.street_invested.get(villain.name, 0.0)
            if action.action_type == ActionType.FOLD:
                state.active_villains.remove(villain.name)
            elif action.action_type == ActionType.CALL:
                additional = max(0, action.amount - already_in)
                state.pot += additional
                villain.stack -= additional
                state.street_invested[villain.name] = action.amount
                action.amount = additional  # display the additional cost
            elif action.action_type == ActionType.RAISE:
                additional = max(0, action.amount - already_in)
                state.pot += additional
                villain.stack -= additional
                state.street_invested[villain.name] = action.amount
                current_raise = action.amount
                has_raise = True

        state.action_history.extend(actions)
        state.current_bet = current_raise if has_raise else self.bb

        return actions

    def generate_villain_postflop_actions(
        self,
        state: HandState,
        hero_acted: bool = False,
        hero_bet: float = 0.0,
    ) -> list[PlayerAction]:
        """
        Generate villain postflop actions.
        If hero hasn't acted yet, generate actions for players acting before hero.
        If hero has acted, generate responses.
        """
        actions = []
        hero_pos = state.hero_position
        active_positions = []

        for v in state.villains:
            if v.name in state.active_villains:
                active_positions.append(v.position)

        pf_order = postflop_order(active_positions + [hero_pos])

        facing_bet = hero_bet > 0
        current_bet = hero_bet

        for pos in pf_order:
            if pos == hero_pos:
                if not hero_acted:
                    break  # Hero's turn to act
                continue  # Hero already acted, skip

            villain = next((v for v in state.villains if v.position == pos), None)
            if not villain or villain.name not in state.active_villains:
                continue

            is_ip = pf_order.index(pos) > pf_order.index(hero_pos) if hero_pos in pf_order else True

            action = generate_villain_postflop_action(
                villain, state,
                facing_bet=facing_bet,
                bet_amount=current_bet,
                is_ip=is_ip,
            )
            actions.append(action)

            if action.action_type == ActionType.FOLD:
                state.active_villains.remove(villain.name)
            elif action.action_type == ActionType.CALL:
                state.pot += action.amount
                villain.stack -= action.amount
            elif action.action_type in (ActionType.BET, ActionType.RAISE):
                state.pot += action.amount
                villain.stack -= action.amount
                current_bet = action.amount
                facing_bet = True

        state.action_history.extend(actions)
        state.current_bet = current_bet

        return actions


# =============================================================================
# Display helpers
# =============================================================================

def format_cards(cards: list[Card]) -> str:
    """Format cards for display with suit symbols."""
    suit_symbols = {
        Suit.HEARTS: "\u2665",    # ♥
        Suit.DIAMONDS: "\u2666",  # ♦
        Suit.CLUBS: "\u2663",     # ♣
        Suit.SPADES: "\u2660",    # ♠
    }
    parts = []
    for c in cards:
        symbol = suit_symbols.get(c.suit, c.suit.value)
        parts.append(f"{c.rank}{symbol}")
    return " ".join(parts)


def format_board_display(state: HandState) -> str:
    """Format the board for display."""
    parts = []
    if state.flop:
        parts.append(f"Flop: [{format_cards(state.flop)}]")
    if state.turn_card:
        parts.append(f"Turn: [{format_cards([state.turn_card])}]")
    if state.river_card:
        parts.append(f"River: [{format_cards([state.river_card])}]")
    return "  ".join(parts)


def format_hand_summary(state: HandState) -> str:
    """Format a summary of the current hand state."""
    lines = []
    lines.append("=" * 65)
    lines.append(f"  HAND STATUS / สถานะมือ")
    lines.append("=" * 65)
    lines.append(f"  Stakes: ${state.pot - state.current_bet:.0f} in pot")
    lines.append(f"  Your Position: {state.hero_position.value}")
    lines.append(f"  Your Cards: [{format_cards(state.hero_cards)}]")
    lines.append(f"  Your Stack: ${state.hero_stack:.0f} "
                 f"({state.hero_stack / 3:.0f} BB)")

    if state.board_cards:
        lines.append(f"\n  Board: {format_board_display(state)}")

    lines.append(f"\n  Pot: ${state.pot:.0f}")
    lines.append(f"  Effective Stack: ${state.effective_stack:.0f}")
    lines.append(f"  SPR: {state.spr:.1f}")

    if state.texture_path:
        lines.append(f"  Texture Path: [{state.texture_code}]")

    # Villains
    if state.active_villains:
        lines.append(f"\n  Active Villain(s):")
        for v in state.villains:
            if v.name in state.active_villains:
                lines.append(f"    {v.describe()}")

    # Current bet to act on
    if state.current_bet > 0 and state.current_street != Street.PREFLOP:
        lines.append(f"\n  Facing bet: ${state.current_bet:.0f}")
        po = state.pot_odds(state.current_bet)
        lines.append(f"  Pot Odds: {po:.1f}%")

    lines.append("=" * 65)
    return "\n".join(lines)


def format_preflop_display(state: HandState, preflop_actions: list) -> str:
    """Format preflop situation for display."""
    lines = []
    lines.append("\n" + "=" * 65)
    lines.append("  PREFLOP / พรีฟลอบ")
    lines.append("=" * 65)
    lines.append(f"  Stakes: $1/$3 NLH  |  9-max")
    lines.append(f"  Your Position: {state.hero_position.value}")
    lines.append(f"  Your Cards: [{format_cards(state.hero_cards)}]")
    lines.append(f"  Your Stack: ${state.hero_stack:.0f} "
                 f"({state.hero_stack / 3:.0f} BB)")
    lines.append(f"  Effective Stack: ${state.effective_stack:.0f} "
                 f"({state.effective_stack / 3:.0f} BB)")
    lines.append(f"  SPR (current): {state.spr:.1f}")

    lines.append(f"\n  Villain(s) at the table:")
    for v in state.villains:
        status = "ACTIVE" if v.name in state.active_villains else "FOLDED"
        lines.append(f"    [{status}] {v.describe()}")

    if preflop_actions:
        lines.append(f"\n  Action before you:")
        for a in preflop_actions:
            lines.append(f"    > {a}")
    else:
        lines.append(f"\n  Action folds to you.")

    lines.append(f"\n  Current pot: ${state.pot:.0f}")
    if state.current_bet > state.pot * 0:
        facing = state.current_bet
        lines.append(f"  Facing: ${facing:.0f} to call")
        po = state.pot_odds(facing)
        lines.append(f"  Pot Odds: {po:.1f}%")

    lines.append("=" * 65)

    lines.append("\n  YOUR TURN TO ACT / ถึงตาคุณ")
    lines.append("  Options: fold / call / raise [amount]")
    lines.append("  What do you do?\n")

    return "\n".join(lines)


def format_postflop_display(
    state: HandState,
    street_name: str,
    villain_actions: list,
) -> str:
    """Format postflop situation for display."""
    from .classifier import classify_hand_vs_board
    from .evaluator import evaluate_hand, hand_rank_name, count_outs, outs_to_equity_rule

    board = state.board_cards
    hero = state.hero_cards

    ranking, kickers = evaluate_hand(hero + board)
    texture, reason_en, reason_th = classify_hand_vs_board(hero, board)

    lines = []
    lines.append("\n" + "=" * 65)
    lines.append(f"  {street_name.upper()} / {_street_th(street_name)}")
    lines.append("=" * 65)
    lines.append(f"  Your Cards: [{format_cards(hero)}]")
    lines.append(f"  Board: {format_board_display(state)}")
    lines.append(f"\n  Your Hand: {hand_rank_name(ranking)}")
    lines.append(f"  Classification: [{texture.value}] {reason_en}")
    lines.append(f"  (TH): [{texture.value}] {reason_th}")
    lines.append(f"  Texture Path: [{state.texture_code}]")

    # Outs (if not river)
    if state.current_street != Street.RIVER:
        num_outs, out_descs = count_outs(hero, board)
        street_calc = "flop" if state.current_street == Street.FLOP else "turn"
        outs_eq = outs_to_equity_rule(num_outs, street_calc)
        lines.append(f"\n  Outs: {num_outs} (~{outs_eq:.0f}% equity from draws)")

    lines.append(f"\n  Pot: ${state.pot:.0f}")
    lines.append(f"  Effective Stack: ${state.effective_stack:.0f}")
    lines.append(f"  SPR: {state.spr:.1f}")

    if villain_actions:
        lines.append(f"\n  Villain action(s):")
        for a in villain_actions:
            lines.append(f"    > {a}")

    facing = state.current_bet
    if facing > 0:
        lines.append(f"\n  Facing bet: ${facing:.0f}")
        po = state.pot_odds(facing)
        lines.append(f"  Pot Odds: {po:.1f}% (you need {po:.1f}% equity to call)")
        mdf = state.mdf(facing)
        lines.append(f"  MDF: {mdf:.1f}% (you should defend at least this % of your range)")
    else:
        lines.append(f"\n  Action is on you (no bet to face)")

    lines.append("=" * 65)

    if facing > 0:
        lines.append("\n  YOUR TURN TO ACT / ถึงตาคุณ")
        lines.append("  Options: fold / call / raise [amount]")
    else:
        lines.append("\n  YOUR TURN TO ACT / ถึงตาคุณ")
        lines.append("  Options: check / bet [amount]")
    lines.append("  What do you do?\n")

    return "\n".join(lines)


def _street_th(name: str) -> str:
    mapping = {
        "flop": "ฟลอบ",
        "turn": "เทิร์น",
        "river": "ริเวอร์",
        "preflop": "พรีฟลอบ",
    }
    return mapping.get(name.lower(), name)
