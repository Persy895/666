"""
S/B/C Board Texture Classifier.

Classifies hero's hand strength relative to the board at each street:
  S = Nut (สัมพันธ์กับไพ่ที่ดีที่สุดที่เป็นไปได้)
      - Top set, top two pair, nut flush, nut straight, full house+
      - Nut flush draw + overcards on flop
  B = Good but not nut (ดีแต่ผู้เล่นอื่นอาจดีกว่า)
      - Middle/bottom set, overpair, top pair top kicker, strong draws
      - Second nut flush, non-nut straight
  C = Unconnected (ไม่สัมพันธ์กับบอร์ด)
      - Missed completely, bottom pair weak kicker, gutshot only
      - Backdoor draws only, no pair no draw
"""

from collections import Counter
from .models import Card, Rank, Suit, BoardTexture, HandRanking
from .evaluator import evaluate_hand, hand_rank_name


def classify_hand_vs_board(
    hero_cards: list[Card],
    board: list[Card],
) -> tuple[BoardTexture, str, str]:
    """
    Classify hero's hand relative to the board.
    Returns (BoardTexture, reason_en, reason_th).
    """
    if not board:
        return BoardTexture.B, "Preflop", "พรีฟลอบ"

    all_cards = hero_cards + board
    ranking, kickers = evaluate_hand(all_cards)
    board_ranks = sorted([c.rank.value for c in board], reverse=True)
    hero_ranks = sorted([c.rank.value for c in hero_cards], reverse=True)
    board_suits = [c.suit for c in board]
    hero_suits = [c.suit for c in hero_cards]

    # Check specific hand attributes
    has_overpair = _has_overpair(hero_cards, board)
    has_top_pair = _has_top_pair(hero_cards, board)
    has_top_kicker = _has_top_kicker(hero_cards, board) if has_top_pair else False
    has_flush_draw = _has_flush_draw(hero_cards, board)
    has_nut_flush_draw = _has_nut_flush_draw(hero_cards, board)
    has_straight_draw = _count_straight_outs(hero_cards, board) >= 8
    has_gutshot = 4 <= _count_straight_outs(hero_cards, board) < 8
    pair_type = _pair_type(hero_cards, board)
    set_type = _set_type(hero_cards, board)
    is_nut_flush = _is_nut_flush(hero_cards, board) if ranking == HandRanking.FLUSH else False
    is_nut_straight = _is_nut_straight(hero_cards, board) if ranking == HandRanking.STRAIGHT else False

    # =====================================================================
    # S - Nut tier
    # =====================================================================
    if ranking.value >= HandRanking.FULL_HOUSE.value:
        return BoardTexture.S, \
            f"{hand_rank_name(ranking)} - Monster hand", \
            f"{hand_rank_name(ranking)} - มือสุดแกร่ง"

    if ranking == HandRanking.FLUSH and is_nut_flush:
        return BoardTexture.S, "Nut flush", "nut flush - ฟลัชที่ดีที่สุด"

    if ranking == HandRanking.STRAIGHT and is_nut_straight:
        return BoardTexture.S, "Nut straight", "nut straight - สเตรทที่ดีที่สุด"

    if ranking == HandRanking.THREE_OF_A_KIND and set_type == "top":
        return BoardTexture.S, "Top set", "top set - เซ็ตสูงสุด"

    if ranking == HandRanking.TWO_PAIR:
        if _is_top_two_pair(hero_cards, board):
            return BoardTexture.S, "Top two pair", "top two pair - ทูแพร์สูงสุด"

    if has_overpair and hero_ranks[0] >= Rank.KING.value:
        # AA/KK overpair on low board
        if board_ranks[0] <= Rank.TEN.value:
            return BoardTexture.S, \
                f"Premium overpair ({_rank_name(hero_ranks[0])}x) on low board", \
                f"โอเวอร์แพร์พรีเมียม ({_rank_name(hero_ranks[0])}x) บนบอร์ดต่ำ"

    # Nut flush draw + overcards on flop (semi-bluff power)
    if has_nut_flush_draw and len(board) == 3:
        overcards = sum(1 for r in hero_ranks if r > board_ranks[0])
        if overcards >= 1:
            return BoardTexture.S, \
                "Nut flush draw + overcard(s) - massive equity", \
                "Nut flush draw + โอเวอร์การ์ด - equity สูงมาก"

    # =====================================================================
    # B - Good but not nut tier
    # =====================================================================
    if ranking == HandRanking.FLUSH and not is_nut_flush:
        return BoardTexture.B, "Non-nut flush", "ฟลัชไม่ใช่ nut"

    if ranking == HandRanking.STRAIGHT and not is_nut_straight:
        return BoardTexture.B, "Non-nut straight", "สเตรทไม่ใช่ nut"

    if ranking == HandRanking.THREE_OF_A_KIND:
        if set_type in ("middle", "bottom"):
            return BoardTexture.B, f"{set_type.title()} set", f"{set_type} set"
        # Trips (pair on board + hero has one)
        return BoardTexture.B, "Trips", "ทริปส์"

    if ranking == HandRanking.TWO_PAIR and not _is_top_two_pair(hero_cards, board):
        return BoardTexture.B, "Non-top two pair", "ทูแพร์ไม่สูงสุด"

    if has_overpair:
        return BoardTexture.B, \
            f"Overpair ({_rank_name(hero_ranks[0])}x)", \
            f"โอเวอร์แพร์ ({_rank_name(hero_ranks[0])}x)"

    if has_top_pair and has_top_kicker:
        return BoardTexture.B, \
            "Top pair top kicker (TPTK)", \
            "ท็อปแพร์ท็อปคิกเกอร์ (TPTK)"

    if has_top_pair:
        return BoardTexture.B, \
            "Top pair (decent kicker)", \
            "ท็อปแพร์ (คิกเกอร์ปานกลาง)"

    # Strong draws
    if has_flush_draw and has_straight_draw:
        return BoardTexture.B, \
            "Combo draw (flush draw + straight draw)", \
            "คอมโบดรอว์ (ฟลัชดรอว์ + สเตรทดรอว์)"

    if has_nut_flush_draw:
        return BoardTexture.B, "Nut flush draw", "Nut flush draw"

    if has_flush_draw:
        return BoardTexture.B, "Flush draw", "ฟลัชดรอว์"

    if has_straight_draw:
        return BoardTexture.B, "Open-ended straight draw", "สเตรทดรอว์ปลายเปิด"

    if pair_type == "middle":
        return BoardTexture.B, "Middle pair", "มิดเดิลแพร์"

    # =====================================================================
    # C - Unconnected tier
    # =====================================================================
    if has_gutshot:
        return BoardTexture.C, \
            "Gutshot only - weak draw", \
            "กัตช็อตเท่านั้น - ดรอว์อ่อน"

    if pair_type == "bottom":
        return BoardTexture.C, \
            "Bottom pair - vulnerable", \
            "บอตทอมแพร์ - เปราะบาง"

    if ranking == HandRanking.HIGH_CARD:
        overcards = sum(1 for r in hero_ranks if r > board_ranks[0])
        if overcards >= 2:
            return BoardTexture.C, \
                "Two overcards - no pair no draw", \
                "โอเวอร์การ์ดสองใบ - ไม่มีแพร์ ไม่มีดรอว์"
        if overcards == 1:
            return BoardTexture.C, \
                "One overcard only", \
                "โอเวอร์การ์ดหนึ่งใบเท่านั้น"
        return BoardTexture.C, \
            "Complete air - nothing", \
            "ไม่มีอะไรเลย - อากาศล้วนๆ"

    return BoardTexture.C, \
        f"{hand_rank_name(ranking)} - weak relative to board", \
        f"{hand_rank_name(ranking)} - อ่อนเมื่อเทียบกับบอร์ด"


# =============================================================================
# Helper functions
# =============================================================================

def _rank_name(value: int) -> str:
    names = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "T"}
    return names.get(value, str(value))


def _has_overpair(hero: list[Card], board: list[Card]) -> bool:
    if hero[0].rank != hero[1].rank:
        return False
    return hero[0].rank.value > max(c.rank.value for c in board)


def _has_top_pair(hero: list[Card], board: list[Card]) -> bool:
    top_board_rank = max(c.rank.value for c in board)
    return any(c.rank.value == top_board_rank for c in hero)


def _has_top_kicker(hero: list[Card], board: list[Card]) -> bool:
    top_board_rank = max(c.rank.value for c in board)
    for c in hero:
        if c.rank.value == top_board_rank:
            other = [h for h in hero if h != c]
            if other and other[0].rank.value >= Rank.JACK.value:
                return True
    return False


def _pair_type(hero: list[Card], board: list[Card]) -> str:
    """Returns 'top', 'middle', 'bottom', or 'none'."""
    board_ranks = sorted([c.rank.value for c in board], reverse=True)
    for h in hero:
        if h.rank.value == board_ranks[0]:
            return "top"
    for h in hero:
        if h.rank.value in board_ranks[1:-1]:
            return "middle"
    for h in hero:
        if h.rank.value == board_ranks[-1]:
            return "bottom"
    return "none"


def _set_type(hero: list[Card], board: list[Card]) -> str:
    """If hero has a set, returns 'top', 'middle', or 'bottom'."""
    if hero[0].rank != hero[1].rank:
        return "none"
    pair_rank = hero[0].rank.value
    board_ranks = sorted([c.rank.value for c in board], reverse=True)
    if pair_rank == board_ranks[0]:
        return "top"
    elif pair_rank == board_ranks[-1]:
        return "bottom"
    else:
        return "middle"


def _is_top_two_pair(hero: list[Card], board: list[Card]) -> bool:
    board_ranks = sorted([c.rank.value for c in board], reverse=True)
    hero_ranks = {c.rank.value for c in hero}
    top_two_board = set(board_ranks[:2])
    return hero_ranks == top_two_board or (
        hero_ranks.issubset(set(board_ranks)) and
        max(hero_ranks) == board_ranks[0]
    )


def _has_flush_draw(hero: list[Card], board: list[Card]) -> bool:
    all_cards = hero + board
    suit_counts = Counter(c.suit for c in all_cards)
    for suit, count in suit_counts.items():
        if count == 4:
            hero_of_suit = [c for c in hero if c.suit == suit]
            if hero_of_suit:
                return True
    return False


def _has_nut_flush_draw(hero: list[Card], board: list[Card]) -> bool:
    all_cards = hero + board
    suit_counts = Counter(c.suit for c in all_cards)
    for suit, count in suit_counts.items():
        if count == 4:
            hero_of_suit = [c for c in hero if c.suit == suit]
            if hero_of_suit:
                hero_max = max(c.rank.value for c in hero_of_suit)
                board_of_suit = [c for c in board if c.suit == suit]
                all_of_suit_ranks = [c.rank.value for c in hero_of_suit + board_of_suit]
                # Nut flush draw = we have the ace of that suit (or highest missing)
                if hero_max == Rank.ACE.value:
                    return True
                # Check if ace is on board
                if Rank.ACE.value in [c.rank.value for c in board_of_suit]:
                    if hero_max == Rank.KING.value:
                        return True
    return False


def _is_nut_flush(hero: list[Card], board: list[Card]) -> bool:
    all_cards = hero + board
    suit_counts = Counter(c.suit for c in all_cards)
    for suit, count in suit_counts.items():
        if count >= 5:
            hero_of_suit = [c for c in hero if c.suit == suit]
            if hero_of_suit:
                hero_max = max(c.rank.value for c in hero_of_suit)
                board_of_suit = [c for c in board if c.suit == suit]
                # Hero has ace of flush suit
                if hero_max == Rank.ACE.value:
                    return True
    return False


def _is_nut_straight(hero: list[Card], board: list[Card]) -> bool:
    """Check if hero's straight is the best possible straight."""
    all_cards = hero + board
    all_ranks = set(c.rank.value for c in all_cards)
    board_ranks = set(c.rank.value for c in board)
    hero_ranks = set(c.rank.value for c in hero)

    # Find the highest straight possible using at least one hero card
    # and the board cards, then check if better exists with other hole cards
    from .evaluator import evaluate_hand
    hero_ranking, hero_kickers = evaluate_hand(all_cards)
    if hero_ranking != HandRanking.STRAIGHT:
        return False

    hero_straight_high = hero_kickers[0]

    # Check if a higher straight is possible with any two cards from remaining deck
    for r1 in range(2, 15):
        for r2 in range(r1, 15):
            test_ranks = board_ranks | {r1, r2}
            test_sorted = sorted(test_ranks, reverse=True)
            for i in range(len(test_sorted) - 4):
                window = test_sorted[i:i+5]
                if window[0] - window[4] == 4:
                    if window[0] > hero_straight_high:
                        # Need at least one of r1,r2 to not be on board
                        if r1 not in board_ranks or r2 not in board_ranks:
                            return False
            # Check wheel
            if {14, 5, 4, 3, 2}.issubset(test_ranks) and hero_straight_high < 6:
                pass  # wheel can't beat hero if hero has higher

    return True


def _count_straight_outs(hero: list[Card], board: list[Card]) -> int:
    """Count approximate straight draw outs."""
    all_ranks = sorted(set(c.rank.value for c in hero + board))
    # Add ace as 1 for wheel
    if 14 in all_ranks:
        all_ranks = [1] + all_ranks

    # Count gaps that completing would make a straight
    outs = 0
    for target in range(2, 15):
        if target in [c.rank.value for c in hero + board]:
            continue
        test_ranks = sorted(set(all_ranks + [target]))
        # Check if adding this card creates a 5-card straight
        for i in range(len(test_ranks) - 4):
            window = test_ranks[i:i+5]
            if window[4] - window[0] == 4 and len(set(window)) == 5:
                # Make sure hero contributes to the straight
                hero_in = any(r in [c.rank.value for c in hero] for r in window)
                if hero_in:
                    outs += 4  # 4 suits
                    break

    # This overcounts, normalize
    return min(outs // 4 * 4, 20)  # cap
