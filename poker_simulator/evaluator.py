"""
Hand evaluator and equity calculator.
Uses simple combinatorial logic - no external poker libraries needed.
"""

from itertools import combinations
from collections import Counter
from typing import Optional

from .models import Card, Rank, Suit, HandRanking


def evaluate_hand(cards: list[Card]) -> tuple[HandRanking, list[int]]:
    """
    Evaluate the best 5-card hand from a list of cards (5-7 cards).
    Returns (HandRanking, kickers) where kickers is used for tiebreaking.
    """
    if len(cards) < 5:
        raise ValueError(f"Need at least 5 cards, got {len(cards)}")

    best_ranking = None
    best_kickers = None

    for combo in combinations(cards, 5):
        ranking, kickers = _evaluate_five(list(combo))
        if best_ranking is None or (ranking.value, kickers) > (best_ranking.value, best_kickers):
            best_ranking = ranking
            best_kickers = kickers

    return best_ranking, best_kickers


def _evaluate_five(cards: list[Card]) -> tuple[HandRanking, list[int]]:
    """Evaluate exactly 5 cards."""
    ranks = sorted([c.rank.value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    rank_counts = Counter(ranks)

    is_flush = len(set(suits)) == 1

    # Check straight
    is_straight, straight_high = _check_straight(ranks)

    # Straight flush / Royal flush
    if is_flush and is_straight:
        if straight_high == 14:
            return HandRanking.ROYAL_FLUSH, [14]
        return HandRanking.STRAIGHT_FLUSH, [straight_high]

    # Four of a kind
    fours = [r for r, c in rank_counts.items() if c == 4]
    if fours:
        kicker = [r for r in ranks if r != fours[0]][0]
        return HandRanking.FOUR_OF_A_KIND, [fours[0], kicker]

    # Full house
    threes = [r for r, c in rank_counts.items() if c == 3]
    pairs = [r for r, c in rank_counts.items() if c == 2]
    if threes and pairs:
        return HandRanking.FULL_HOUSE, [max(threes), max(pairs)]

    # Flush
    if is_flush:
        return HandRanking.FLUSH, ranks

    # Straight
    if is_straight:
        return HandRanking.STRAIGHT, [straight_high]

    # Three of a kind
    if threes:
        kickers = sorted([r for r in ranks if r != threes[0]], reverse=True)
        return HandRanking.THREE_OF_A_KIND, [threes[0]] + kickers[:2]

    # Two pair
    if len(pairs) == 2:
        high_pair = max(pairs)
        low_pair = min(pairs)
        kicker = [r for r in ranks if r not in pairs][0]
        return HandRanking.TWO_PAIR, [high_pair, low_pair, kicker]

    # One pair
    if len(pairs) == 1:
        kickers = sorted([r for r in ranks if r != pairs[0]], reverse=True)
        return HandRanking.ONE_PAIR, [pairs[0]] + kickers[:3]

    # High card
    return HandRanking.HIGH_CARD, ranks


def _check_straight(ranks: list[int]) -> tuple[bool, int]:
    """Check if sorted (desc) ranks form a straight. Returns (is_straight, high_card)."""
    unique = sorted(set(ranks), reverse=True)
    if len(unique) < 5:
        return False, 0

    # Normal straight check
    for i in range(len(unique) - 4):
        window = unique[i:i + 5]
        if window[0] - window[4] == 4:
            return True, window[0]

    # Wheel (A-2-3-4-5)
    if set([14, 5, 4, 3, 2]).issubset(set(unique)):
        return True, 5

    return False, 0


def hand_rank_name(ranking: HandRanking) -> str:
    names = {
        HandRanking.HIGH_CARD: "High Card",
        HandRanking.ONE_PAIR: "One Pair",
        HandRanking.TWO_PAIR: "Two Pair",
        HandRanking.THREE_OF_A_KIND: "Three of a Kind (Set/Trips)",
        HandRanking.STRAIGHT: "Straight",
        HandRanking.FLUSH: "Flush",
        HandRanking.FULL_HOUSE: "Full House",
        HandRanking.FOUR_OF_A_KIND: "Four of a Kind (Quads)",
        HandRanking.STRAIGHT_FLUSH: "Straight Flush",
        HandRanking.ROYAL_FLUSH: "Royal Flush",
    }
    return names.get(ranking, str(ranking))


# =============================================================================
# Equity Calculator (Monte Carlo)
# =============================================================================

def make_deck(exclude: list[Card]) -> list[Card]:
    """Create a full deck minus excluded cards."""
    excluded_set = {(c.rank, c.suit) for c in exclude}
    deck = []
    for suit in Suit:
        for rank in Rank:
            if (rank, suit) not in excluded_set:
                deck.append(Card(rank, suit))
    return deck


def estimate_equity_vs_range(
    hero_cards: list[Card],
    board: list[Card],
    villain_range: list[list[Card]],
    simulations: int = 5000,
) -> float:
    """
    Estimate hero equity vs a villain range using Monte Carlo.
    villain_range: list of [Card, Card] hands villain could have.
    Returns equity as percentage (0-100).
    """
    import random

    if not villain_range:
        return 50.0

    known = set((c.rank, c.suit) for c in hero_cards + board)
    remaining_board = 5 - len(board)

    wins = 0
    ties = 0
    total = 0

    # Filter out villain hands that conflict with known cards
    valid_range = []
    for vh in villain_range:
        if not any((c.rank, c.suit) in known for c in vh):
            valid_range.append(vh)

    if not valid_range:
        return 50.0

    for _ in range(simulations):
        villain_hand = random.choice(valid_range)
        villain_known = {(c.rank, c.suit) for c in villain_hand}

        all_known = known | villain_known
        deck = [
            Card(rank, suit)
            for suit in Suit
            for rank in Rank
            if (rank, suit) not in all_known
        ]

        random.shuffle(deck)
        runout = deck[:remaining_board]
        full_board = board + runout

        hero_eval = evaluate_hand(hero_cards + full_board)
        villain_eval = evaluate_hand(list(villain_hand) + full_board)

        hero_score = (hero_eval[0].value, hero_eval[1])
        villain_score = (villain_eval[0].value, villain_eval[1])

        if hero_score > villain_score:
            wins += 1
        elif hero_score == villain_score:
            ties += 1
        total += 1

    if total == 0:
        return 50.0
    return (wins + ties * 0.5) / total * 100


def count_outs(
    hero_cards: list[Card],
    board: list[Card],
    target_rankings: Optional[list[HandRanking]] = None,
) -> tuple[int, list[str]]:
    """
    Count outs that meaningfully improve hero's hand through hole cards.
    Only counts:
    - Cards that pair our hole cards (not just the board)
    - Cards that complete flush draws (when we contribute suited cards)
    - Cards that complete straight draws (when we contribute to the straight)
    - Cards that improve already-made hands (e.g., pair -> trips)
    Returns (number_of_outs, list of descriptions).
    """
    if not board:
        return 0, []

    current_ranking, current_kickers = evaluate_hand(hero_cards + board)
    hero_ranks = {c.rank for c in hero_cards}
    hero_suits = [c.suit for c in hero_cards]

    known = set((c.rank, c.suit) for c in hero_cards + board)
    remaining_deck = [
        Card(rank, suit)
        for suit in Suit
        for rank in Rank
        if (rank, suit) not in known
    ]

    outs = []
    out_descriptions = []
    seen_ranks_for_pair = set()  # avoid counting same rank multiple times in desc

    for card in remaining_deck:
        new_board = board + [card]
        new_ranking, new_kickers = evaluate_hand(hero_cards + new_board)

        # Must be a ranking improvement
        if new_ranking.value <= current_ranking.value:
            continue

        if target_rankings and new_ranking not in target_rankings:
            continue

        # Check if this out is "connected" to our hole cards
        is_connected = False
        reason = ""

        # 1. Card pairs one of our hole cards
        if card.rank in hero_ranks:
            is_connected = True
            reason = f"pairs our {card.rank}"

        # 2. Card completes a flush and we have suited cards contributing
        elif new_ranking == HandRanking.FLUSH:
            from collections import Counter as _Counter
            all_suits = _Counter(c.suit for c in hero_cards + new_board)
            for suit, count in all_suits.items():
                if count >= 5 and suit in hero_suits:
                    is_connected = True
                    reason = "completes flush"
                    break

        # 3. Card completes a straight and our hole cards are part of it
        elif new_ranking == HandRanking.STRAIGHT:
            # Check if hero cards are used in the straight
            all_ranks = sorted(set(c.rank.value for c in hero_cards + new_board), reverse=True)
            # Also check wheel
            if 14 in all_ranks:
                all_ranks_ext = all_ranks + [1]
            else:
                all_ranks_ext = all_ranks
            all_ranks_ext = sorted(set(all_ranks_ext), reverse=True)
            for i in range(len(all_ranks_ext) - 4):
                window = all_ranks_ext[i:i+5]
                if window[0] - window[4] == 4:
                    straight_ranks = set(window)
                    # Does hero contribute?
                    hero_vals = {c.rank.value for c in hero_cards}
                    if 1 in straight_ranks and 14 in hero_vals:
                        hero_vals.add(1)
                    if hero_vals & straight_ranks:
                        is_connected = True
                        reason = "completes straight"
                        break

        # 4. Card improves our already-made hand (trips, full house, etc.)
        elif new_ranking.value >= HandRanking.THREE_OF_A_KIND.value:
            if card.rank in hero_ranks:
                is_connected = True
                reason = f"improves to {hand_rank_name(new_ranking)}"
            # Also: card on board pairs our set/trips to make full house
            elif current_ranking.value >= HandRanking.ONE_PAIR.value:
                is_connected = True
                reason = f"improves to {hand_rank_name(new_ranking)}"

        # 5. Two pair improvement (our pair + board pair)
        elif new_ranking == HandRanking.TWO_PAIR:
            if card.rank in hero_ranks:
                is_connected = True
                reason = "makes two pair"

        if is_connected:
            outs.append(card)
            out_descriptions.append(f"{card} -> {hand_rank_name(new_ranking)} ({reason})")

    return len(outs), out_descriptions


def outs_to_equity_rule(outs: int, street: str) -> float:
    """
    Simple rule of 2 and 4.
    Flop (2 cards to come): outs * 4
    Turn (1 card to come): outs * 2
    """
    if street == "flop":
        return min(outs * 4, 100)
    else:
        return min(outs * 2, 100)
