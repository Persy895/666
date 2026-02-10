"""
Unit tests for the poker simulator.
Run: python -m poker_simulator.tests
"""

import sys
from .models import Card, Rank, Suit, HandRanking, BoardTexture, PlayerType, Position
from .evaluator import evaluate_hand, hand_rank_name, count_outs, outs_to_equity_rule
from .classifier import classify_hand_vs_board
from .opponents import build_range_cards, create_villain


def test_card_parsing():
    c = Card.from_str("Ah")
    assert c.rank == Rank.ACE
    assert c.suit == Suit.HEARTS

    c2 = Card.from_str("Td")
    assert c2.rank == Rank.TEN
    assert c2.suit == Suit.DIAMONDS

    c3 = Card.from_str("2c")
    assert c3.rank == Rank.TWO
    assert c3.suit == Suit.CLUBS
    print("  [PASS] Card parsing")


def test_hand_evaluation():
    # Royal flush
    cards = [Card.from_str(s) for s in ["Ah", "Kh", "Qh", "Jh", "Th"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.ROYAL_FLUSH

    # Straight flush
    cards = [Card.from_str(s) for s in ["9h", "8h", "7h", "6h", "5h"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.STRAIGHT_FLUSH

    # Four of a kind
    cards = [Card.from_str(s) for s in ["Ah", "Ad", "Ac", "As", "Kh"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.FOUR_OF_A_KIND

    # Full house
    cards = [Card.from_str(s) for s in ["Ah", "Ad", "Ac", "Kh", "Kd"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.FULL_HOUSE

    # Flush
    cards = [Card.from_str(s) for s in ["Ah", "Jh", "9h", "5h", "2h"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.FLUSH

    # Straight
    cards = [Card.from_str(s) for s in ["Ah", "Kd", "Qc", "Js", "Th"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.STRAIGHT

    # Wheel
    cards = [Card.from_str(s) for s in ["Ah", "2d", "3c", "4s", "5h"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.STRAIGHT

    # Three of a kind
    cards = [Card.from_str(s) for s in ["Ah", "Ad", "Ac", "Kh", "Qd"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.THREE_OF_A_KIND

    # Two pair
    cards = [Card.from_str(s) for s in ["Ah", "Ad", "Kh", "Kd", "Qc"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.TWO_PAIR

    # One pair
    cards = [Card.from_str(s) for s in ["Ah", "Ad", "Kh", "Qd", "Jc"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.ONE_PAIR

    # High card
    cards = [Card.from_str(s) for s in ["Ah", "Kd", "Qc", "Js", "9h"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.HIGH_CARD

    # 7-card evaluation (pick best 5)
    cards = [Card.from_str(s) for s in ["Ah", "Kd", "Qc", "Jh", "Th", "2s", "3d"]]
    ranking, _ = evaluate_hand(cards)
    assert ranking == HandRanking.STRAIGHT

    print("  [PASS] Hand evaluation")


def test_sbc_classification():
    # S: Top set
    hero = [Card.from_str("As"), Card.from_str("Ah")]
    board = [Card.from_str(s) for s in ["Ac", "7d", "2c"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex == BoardTexture.S, f"Expected S got {tex.value}"

    # S: Top two pair
    hero = [Card.from_str("As"), Card.from_str("Kh")]
    board = [Card.from_str(s) for s in ["Ac", "Kd", "2c"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex == BoardTexture.S, f"Expected S got {tex.value}"

    # B: Overpair
    hero = [Card.from_str("Qs"), Card.from_str("Qh")]
    board = [Card.from_str(s) for s in ["Jc", "7d", "2c"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex == BoardTexture.B, f"Expected B got {tex.value}"

    # B: TPTK
    hero = [Card.from_str("As"), Card.from_str("Kh")]
    board = [Card.from_str(s) for s in ["Ac", "7d", "2c"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex == BoardTexture.B, f"Expected B got {tex.value}"

    # B: Flush draw
    hero = [Card.from_str("Ah"), Card.from_str("Th")]
    board = [Card.from_str(s) for s in ["Kh", "7h", "2c"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex in (BoardTexture.S, BoardTexture.B), f"Expected S or B got {tex.value}"

    # C: Air
    hero = [Card.from_str("6s"), Card.from_str("5h")]
    board = [Card.from_str(s) for s in ["Ac", "Kd", "Qc"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex == BoardTexture.C, f"Expected C got {tex.value}"

    # C: Bottom pair
    hero = [Card.from_str("2s"), Card.from_str("3h")]
    board = [Card.from_str(s) for s in ["Ac", "Kd", "2c"]]
    tex, _, _ = classify_hand_vs_board(hero, board)
    assert tex == BoardTexture.C, f"Expected C got {tex.value}"

    print("  [PASS] S/B/C classification")


def test_outs():
    # AK on 593 rainbow: 6 outs (3A + 3K)
    hero = [Card.from_str("Ah"), Card.from_str("Kd")]
    board = [Card.from_str(s) for s in ["5s", "9h", "3c"]]
    outs, _ = count_outs(hero, board)
    assert outs == 6, f"Expected 6 outs got {outs}"

    # Rule of 4: 6 outs on flop = 24%
    eq = outs_to_equity_rule(6, "flop")
    assert eq == 24, f"Expected 24% got {eq}"

    # Rule of 2: 6 outs on turn = 12%
    eq2 = outs_to_equity_rule(6, "turn")
    assert eq2 == 12, f"Expected 12% got {eq2}"

    print("  [PASS] Outs calculation")


def test_ranges():
    # TAG should have fewer combos than LAG
    tag_range = build_range_cards(PlayerType.TAG, Position.CO)
    lag_range = build_range_cards(PlayerType.LAG, Position.CO)
    nit_range = build_range_cards(PlayerType.NIT, Position.CO)

    assert len(nit_range) < len(tag_range) < len(lag_range), \
        f"Range sizes: NIT={len(nit_range)}, TAG={len(tag_range)}, LAG={len(lag_range)}"

    print(f"  [PASS] Ranges (NIT={len(nit_range)}, TAG={len(tag_range)}, LAG={len(lag_range)} combos)")


def test_villain_creation():
    v = create_villain("Test", Position.CO, PlayerType.TAG, 500.0)
    assert v.vpip > 0
    assert v.pfr > 0
    assert v.player_type == PlayerType.TAG
    print("  [PASS] Villain creation")


def run_all_tests():
    print("\n  Running tests...")
    print("  " + "-" * 40)
    test_card_parsing()
    test_hand_evaluation()
    test_sbc_classification()
    test_outs()
    test_ranges()
    test_villain_creation()
    print("  " + "-" * 40)
    print("  All tests passed!\n")


if __name__ == "__main__":
    run_all_tests()
