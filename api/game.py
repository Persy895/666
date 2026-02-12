"""
Vercel serverless function for Poker Decision Training Simulator.
Stateless API — all game state is passed as JSON in request/response.

Endpoints (via query param ?action=):
  POST /api/game?action=new_hand   → Start a new hand
  POST /api/game?action=hero_act   → Submit hero's action, get critique + advance
"""

import json
import random
from http.server import BaseHTTPRequestHandler
from itertools import combinations
from collections import Counter
from urllib.parse import parse_qs, urlparse


# =============================================================================
# CARD / HAND EVALUATION (inlined for Vercel compatibility)
# =============================================================================

SUITS = ["h", "d", "c", "s"]
SUIT_SYMBOLS = {"h": "\u2665", "d": "\u2666", "c": "\u2663", "s": "\u2660"}
RANKS = ["2","3","4","5","6","7","8","9","T","J","Q","K","A"]
RANK_VALUES = {r: i+2 for i, r in enumerate(RANKS)}  # 2=2 .. A=14

HAND_RANKINGS = [
    "High Card", "One Pair", "Two Pair", "Three of a Kind",
    "Straight", "Flush", "Full House", "Four of a Kind",
    "Straight Flush", "Royal Flush"
]


def card_rank(c):
    return RANK_VALUES[c[:-1]]

def card_suit(c):
    return c[-1]

def card_display(c):
    return c[:-1] + SUIT_SYMBOLS.get(c[-1], c[-1])

def cards_display(cards):
    return " ".join(card_display(c) for c in cards)


def evaluate_five(cards):
    """Evaluate 5 cards → (ranking_index, kickers)"""
    ranks = sorted([card_rank(c) for c in cards], reverse=True)
    suits = [card_suit(c) for c in cards]
    rc = Counter(ranks)
    is_flush = len(set(suits)) == 1

    unique = sorted(set(ranks), reverse=True)
    is_straight = False
    straight_high = 0
    if len(unique) >= 5:
        for i in range(len(unique) - 4):
            w = unique[i:i+5]
            if w[0] - w[4] == 4:
                is_straight = True
                straight_high = w[0]
                break
    if not is_straight and {14,5,4,3,2}.issubset(set(unique)):
        is_straight = True
        straight_high = 5

    if is_flush and is_straight:
        return (9 if straight_high == 14 else 8, [straight_high])
    fours = [r for r,cnt in rc.items() if cnt == 4]
    if fours:
        k = [r for r in ranks if r != fours[0]][0]
        return (7, [fours[0], k])
    threes = [r for r,cnt in rc.items() if cnt == 3]
    pairs = [r for r,cnt in rc.items() if cnt == 2]
    if threes and pairs:
        return (6, [max(threes), max(pairs)])
    if is_flush:
        return (5, ranks)
    if is_straight:
        return (4, [straight_high])
    if threes:
        ks = sorted([r for r in ranks if r != threes[0]], reverse=True)
        return (3, [threes[0]] + ks[:2])
    if len(pairs) == 2:
        hp, lp = max(pairs), min(pairs)
        k = [r for r in ranks if r not in pairs][0]
        return (2, [hp, lp, k])
    if len(pairs) == 1:
        ks = sorted([r for r in ranks if r != pairs[0]], reverse=True)
        return (1, [pairs[0]] + ks[:3])
    return (0, ranks)


def evaluate_hand(cards):
    """Best 5-card hand from 5-7 cards."""
    best = None
    for combo in combinations(cards, 5):
        ev = evaluate_five(list(combo))
        if best is None or ev > best:
            best = ev
    return best


def make_deck(exclude=None):
    exclude = set(exclude or [])
    return [r+s for s in SUITS for r in RANKS if r+s not in exclude]


# =============================================================================
# EQUITY CALCULATOR (Monte Carlo)
# =============================================================================

def estimate_equity(hero, board, villain_range, sims=2000):
    known = set(hero + board)
    valid = [vh for vh in villain_range if not any(c in known for c in vh)]
    if not valid:
        return 50.0
    remaining = 5 - len(board)
    wins = ties = total = 0
    for _ in range(sims):
        vh = random.choice(valid)
        deck = [c for c in make_deck(known | set(vh))]
        random.shuffle(deck)
        fb = board + deck[:remaining]
        he = evaluate_hand(hero + fb)
        ve = evaluate_hand(vh + fb)
        if he > ve: wins += 1
        elif he == ve: ties += 1
        total += 1
    return (wins + ties * 0.5) / max(total, 1) * 100


# =============================================================================
# OUTS COUNTER
# =============================================================================

def count_outs(hero, board):
    if not board:
        return 0, []
    current = evaluate_hand(hero + board)
    hero_ranks = {card_rank(c) for c in hero}
    hero_suits = [card_suit(c) for c in hero]
    known = set(hero + board)
    deck = make_deck(known)
    outs = []
    for card in deck:
        new_board = board + [card]
        new_ev = evaluate_hand(hero + new_board)
        if new_ev[0] <= current[0]:
            continue
        cr = card_rank(card)
        cs = card_suit(card)
        connected = False
        reason = ""
        if cr in hero_ranks:
            connected = True
            reason = "pairs hole card"
        elif new_ev[0] == 5:  # flush
            sc = Counter(card_suit(c) for c in hero + new_board)
            for suit, cnt in sc.items():
                if cnt >= 5 and suit in hero_suits:
                    connected = True
                    reason = "completes flush"
                    break
        elif new_ev[0] == 4:  # straight
            all_r = sorted(set(card_rank(c) for c in hero + new_board), reverse=True)
            if 14 in all_r:
                all_r_ext = sorted(set(all_r + [1]), reverse=True)
            else:
                all_r_ext = all_r
            for i in range(len(all_r_ext) - 4):
                w = all_r_ext[i:i+5]
                if w[0] - w[4] == 4:
                    hv = {card_rank(c) for c in hero}
                    if 1 in set(w) and 14 in hv:
                        hv.add(1)
                    if hv & set(w):
                        connected = True
                        reason = "completes straight"
                        break
        elif new_ev[0] >= 3 and current[0] >= 1:
            connected = True
            reason = f"improves to {HAND_RANKINGS[new_ev[0]]}"
        elif new_ev[0] == 2 and cr in hero_ranks:
            connected = True
            reason = "makes two pair"
        if connected:
            outs.append({"card": card, "result": HAND_RANKINGS[new_ev[0]], "reason": reason})
    return len(outs), outs[:10]


# =============================================================================
# S/B/C CLASSIFIER
# =============================================================================

def classify_sbc(hero, board):
    if not board:
        return "B", "Preflop", "พรีฟลอบ"
    all_cards = hero + board
    ranking = evaluate_hand(all_cards)[0]
    board_ranks = sorted([card_rank(c) for c in board], reverse=True)
    hero_ranks = sorted([card_rank(c) for c in hero], reverse=True)
    hero_suits_list = [card_suit(c) for c in hero]

    has_overpair = hero_ranks[0] == hero_ranks[1] if len(hero) == 2 else False
    if has_overpair:
        has_overpair = hero_ranks[0] > board_ranks[0]

    has_top_pair = any(card_rank(c) == board_ranks[0] for c in hero)
    has_top_kicker = False
    if has_top_pair:
        other = [card_rank(c) for c in hero if card_rank(c) != board_ranks[0]]
        has_top_kicker = bool(other and other[0] >= 11)

    # Flush draw check
    all_suit_counts = Counter(card_suit(c) for c in all_cards)
    has_flush_draw = False
    has_nut_flush_draw = False
    for suit, cnt in all_suit_counts.items():
        if cnt == 4 and suit in hero_suits_list:
            has_flush_draw = True
            hero_of_suit = [card_rank(c) for c in hero if card_suit(c) == suit]
            if hero_of_suit and max(hero_of_suit) == 14:
                has_nut_flush_draw = True

    pair_type = "none"
    for h in hero:
        if card_rank(h) == board_ranks[0]:
            pair_type = "top"; break
    if pair_type == "none":
        for h in hero:
            if card_rank(h) in board_ranks[1:-1]:
                pair_type = "middle"; break
    if pair_type == "none":
        for h in hero:
            if card_rank(h) == board_ranks[-1]:
                pair_type = "bottom"; break

    set_type = "none"
    if len(hero) == 2 and hero_ranks[0] == hero_ranks[1]:
        pr = hero_ranks[0]
        if pr == board_ranks[0]: set_type = "top"
        elif pr == board_ranks[-1]: set_type = "bottom"
        elif pr in board_ranks: set_type = "middle"

    is_nut_flush = False
    if ranking == 5:
        for suit, cnt in all_suit_counts.items():
            if cnt >= 5 and suit in hero_suits_list:
                hero_of_suit = [card_rank(c) for c in hero if card_suit(c) == suit]
                if hero_of_suit and max(hero_of_suit) == 14:
                    is_nut_flush = True

    # S tier
    if ranking >= 6:
        return "S", HAND_RANKINGS[ranking], f"{HAND_RANKINGS[ranking]} - มือสุดแกร่ง"
    if ranking == 5 and is_nut_flush:
        return "S", "Nut flush", "Nut flush - ฟลัชที่ดีที่สุด"
    if ranking == 3 and set_type == "top":
        return "S", "Top set", "Top set - เซ็ตสูงสุด"
    if ranking == 2:
        if len(hero) == 2 and set(hero_ranks) == set(board_ranks[:2]):
            return "S", "Top two pair", "Top two pair - ทูแพร์สูงสุด"
    if has_overpair and hero_ranks[0] >= 13 and board_ranks[0] <= 10:
        nm = {14:"A",13:"K"}.get(hero_ranks[0], str(hero_ranks[0]))
        return "S", f"Premium overpair ({nm}{nm})", f"โอเวอร์แพร์พรีเมียม ({nm}{nm})"
    if has_nut_flush_draw and len(board) == 3:
        overcards = sum(1 for r in hero_ranks if r > board_ranks[0])
        if overcards >= 1:
            return "S", "Nut flush draw + overcard(s)", "Nut flush draw + โอเวอร์การ์ด"

    # B tier
    if ranking == 5:
        return "B", "Non-nut flush", "ฟลัชไม่ใช่ nut"
    if ranking == 4:
        return "B", "Straight", "สเตรท"
    if ranking == 3:
        return "B", f"{set_type.title()} set / Trips", f"{set_type} set / ทริปส์"
    if ranking == 2:
        return "B", "Two pair", "ทูแพร์"
    if has_overpair:
        nm = {14:"A",13:"K",12:"Q",11:"J",10:"T"}.get(hero_ranks[0], str(hero_ranks[0]))
        return "B", f"Overpair ({nm}{nm})", f"โอเวอร์แพร์ ({nm}{nm})"
    if has_top_pair and has_top_kicker:
        return "B", "TPTK (Top Pair Top Kicker)", "ท็อปแพร์ท็อปคิกเกอร์"
    if has_top_pair:
        return "B", "Top pair", "ท็อปแพร์"
    if has_flush_draw and _count_straight_draws(hero, board) >= 8:
        return "B", "Combo draw", "คอมโบดรอว์"
    if has_nut_flush_draw:
        return "B", "Nut flush draw", "Nut flush draw"
    if has_flush_draw:
        return "B", "Flush draw", "ฟลัชดรอว์"
    if _count_straight_draws(hero, board) >= 8:
        return "B", "OESD (Open-ended straight draw)", "สเตรทดรอว์ปลายเปิด"
    if pair_type == "middle":
        return "B", "Middle pair", "มิดเดิลแพร์"

    # C tier
    if pair_type == "bottom":
        return "C", "Bottom pair", "บอตทอมแพร์"
    if _count_straight_draws(hero, board) >= 4:
        return "C", "Gutshot draw", "กัตช็อต"
    overcards = sum(1 for r in hero_ranks if r > board_ranks[0])
    if overcards >= 2:
        return "C", "Two overcards (no pair, no draw)", "โอเวอร์การ์ดสองใบ (ไม่มีแพร์ ไม่มีดรอว์)"
    if overcards == 1:
        return "C", "One overcard only", "โอเวอร์การ์ดหนึ่งใบ"
    return "C", "Air (nothing)", "ไม่มีอะไรเลย (อากาศ)"


def _count_straight_draws(hero, board):
    all_r = sorted(set(card_rank(c) for c in hero + board))
    if 14 in all_r:
        all_r = [1] + all_r
    outs = 0
    known_ranks = set(card_rank(c) for c in hero + board)
    hero_r = set(card_rank(c) for c in hero)
    for target in range(2, 15):
        if target in known_ranks:
            continue
        test = sorted(set(all_r + [target]))
        for i in range(len(test) - 4):
            w = test[i:i+5]
            if w[4] - w[0] == 4 and len(set(w)) == 5:
                if hero_r & set(w):
                    outs += 1
                    break
    return outs


# =============================================================================
# VILLAIN PROFILES + RANGES
# =============================================================================

VILLAIN_TEMPLATES = {
    "TAG":  {"vpip":22,"pfr":18,"af":3.0,"ftcb":45,"3b":8,"wtsd":26},
    "LAG":  {"vpip":30,"pfr":25,"af":4.0,"ftcb":35,"3b":12,"wtsd":28},
    "NIT":  {"vpip":12,"pfr":10,"af":2.0,"ftcb":60,"3b":4,"wtsd":22},
    "FISH": {"vpip":45,"pfr":10,"af":1.0,"ftcb":55,"3b":3,"wtsd":35},
    "CALLING_STATION": {"vpip":40,"pfr":8,"af":0.7,"ftcb":30,"3b":2,"wtsd":42},
    "MANIAC":{"vpip":50,"pfr":35,"af":5.5,"ftcb":25,"3b":18,"wtsd":30},
}

VILLAIN_NOTES = {
    "TAG": "Tight-Aggressive: เล่นน้อยมือ แต่เมื่อเล่นจะก้าวร้าว",
    "LAG": "Loose-Aggressive: เล่นหลายมือ ก้าวร้าวมาก 3-bet บ่อย",
    "NIT": "Nit: เล่นแน่นมาก รอแต่มือพรีเมียม raise = มือแข็ง",
    "FISH": "Fish: เล่นมากมือ limp บ่อย ให้ value เมื่อเราแข็ง",
    "CALLING_STATION": "Calling Station: call ทุกอย่าง ห้ามบลัฟ! Value bet หนัก",
    "MANIAC": "Maniac: raise/re-raise บ่อย Range กว้างมาก Trap ด้วยมือแข็ง",
}

HAND_TIERS = {
    1: ["AA","KK"], 2: ["QQ","JJ","AKs"], 3: ["AKo","TT","AQs"],
    4: ["AQo","AJs","99","KQs"], 5: ["ATs","KJs","88","KQo","QJs"],
    6: ["AJo","KTs","QTs","JTs","77","A9s","A8s"],
    7: ["ATo","KJo","66","55","A7s","A6s","A5s","K9s","Q9s","J9s","T9s"],
    8: ["A4s","A3s","A2s","K8s","K7s","44","33","22","QJo","98s","87s","76s"],
    9: ["KTo","QTo","JTo","97s","86s","75s","65s","54s"],
}

POSITIONS = ["UTG","UTG1","UTG2","LJ","HJ","CO","BTN","SB","BB"]

def _tier_limit(vtype, pos):
    base = {"NIT":3,"TAG":5,"LAG":8,"FISH":9,"CALLING_STATION":9,"MANIAC":10}.get(vtype, 6)
    adj = {"UTG":-2,"UTG1":-2,"UTG2":-1,"LJ":-1,"HJ":0,"CO":0,"BTN":1,"SB":0,"BB":1}.get(pos,0)
    return max(1, min(10, base + adj))

def build_range_hands(vtype, pos):
    limit = _tier_limit(vtype, pos)
    hands = []
    for t in range(1, limit+1):
        for h in HAND_TIERS.get(t, []):
            if len(h) == 2:  # pair
                r = h[0]
                for i in range(4):
                    for j in range(i+1, 4):
                        hands.append([r+SUITS[i], r+SUITS[j]])
            elif h.endswith("s"):
                r1, r2 = h[0], h[1]
                for s in SUITS:
                    hands.append([r1+s, r2+s])
            else:
                r1, r2 = h[0], h[1]
                for s1 in SUITS:
                    for s2 in SUITS:
                        if s1 != s2:
                            hands.append([r1+s1, r2+s2])
    return hands

def describe_range(vtype, pos):
    limit = _tier_limit(vtype, pos)
    hands = []
    for t in range(1, limit+1):
        hands.extend(HAND_TIERS.get(t, []))
    return ", ".join(hands[:15]) + ("..." if len(hands) > 15 else "")


# =============================================================================
# VILLAIN ACTION GENERATION
# =============================================================================

def gen_villain_preflop(villain, facing_raise, raise_amount):
    roll = random.random() * 100
    if facing_raise:
        fold_pct = 100 - villain["vpip"]
        call_pct = villain["vpip"] - villain["3b"]
        if roll < fold_pct:
            return {"type": "fold", "amount": 0}
        elif roll < fold_pct + call_pct:
            return {"type": "call", "amount": raise_amount}
        else:
            return {"type": "raise", "amount": raise_amount * 3}
    else:
        fold_pct = 100 - villain["vpip"]
        limp_pct = villain["vpip"] - villain["pfr"]
        if roll < fold_pct:
            return {"type": "fold", "amount": 0}
        elif roll < fold_pct + limp_pct:
            return {"type": "call", "amount": 3}
        else:
            return {"type": "raise", "amount": random.choice([8,9,10,12])}

def gen_villain_postflop(villain, pot, facing_bet, bet_amount):
    roll = random.random() * 100
    if facing_bet:
        fold_base = villain["ftcb"]
        if villain["type"] == "CALLING_STATION": fold_base *= 0.5
        elif villain["type"] == "MANIAC": fold_base *= 0.3
        elif villain["type"] == "FISH": fold_base *= 0.7
        if bet_amount > pot * 0.75: fold_base *= 1.2
        elif bet_amount < pot * 0.4: fold_base *= 0.7
        raise_pct = villain["af"] * 3
        if villain["type"] in ("CALLING_STATION","FISH"): raise_pct = max(2, raise_pct * 0.3)
        call_pct = 100 - fold_base - raise_pct
        if roll < fold_base:
            return {"type": "fold", "amount": 0}
        elif roll < fold_base + call_pct:
            return {"type": "call", "amount": bet_amount}
        else:
            return {"type": "raise", "amount": min(bet_amount * 2.5, villain["stack"])}
    else:
        check_pct = 100 - villain["af"] * 10
        if villain["type"] in ("CALLING_STATION","FISH"): check_pct = 80
        elif villain["type"] == "MANIAC": check_pct = 30
        check_pct = max(20, min(90, check_pct))
        if roll < check_pct:
            return {"type": "check", "amount": 0}
        else:
            sz = pot * random.choice([0.33, 0.5, 0.67, 0.75])
            return {"type": "bet", "amount": min(round(sz, 0), villain["stack"])}


# =============================================================================
# ANALYSIS / CRITIQUE ENGINE
# =============================================================================

def analyze_action(state, hero_action, hero_amount, facing_bet):
    hero = state["hero_cards"]
    board = state["board"]
    pot = state["pot"]
    eff = state["effective_stack"]
    spr = eff / pot if pot > 0 else 999

    classification, reason_en, reason_th = classify_sbc(hero, board)
    ranking = evaluate_hand(hero + board) if board else (0, [])
    hand_name = HAND_RANKINGS[ranking[0]] if board else "N/A"

    # Equity
    equity = 50.0
    equity_details = {}
    for v in state["villains"]:
        if v["active"]:
            vr = build_range_hands(v["type"], v["position"])
            eq = estimate_equity(hero, board, vr, sims=1500)
            equity_details[v["name"]] = {"equity": round(eq, 1), "range": describe_range(v["type"], v["position"])}
            equity = eq

    # Outs
    num_outs = 0
    outs_eq = 0
    if board and state["street"] != "river":
        num_outs, _ = count_outs(hero, board)
        multiplier = 4 if state["street"] == "flop" else 2
        outs_eq = min(num_outs * multiplier, 100)

    # SPR guidance
    if spr <= 2: spr_guide = f"SPR={spr:.1f} (Very Low). Commit or fold. Strong hands → get all-in."
    elif spr <= 4: spr_guide = f"SPR={spr:.1f} (Low). One-pair hands can stack off. Plan bet-bet-shove."
    elif spr <= 8: spr_guide = f"SPR={spr:.1f} (Medium). Need two-pair+ to stack off. Pot control with one pair."
    elif spr <= 15: spr_guide = f"SPR={spr:.1f} (High). Need strong hands to stack off. Draws have good implied odds."
    else: spr_guide = f"SPR={spr:.1f} (Very High). Draws and set-mining very profitable. Play cautiously."

    feedback = []
    corrections = []
    is_correct = True

    # Pot odds
    pot_odds_val = None
    if facing_bet > 0:
        pot_odds_val = round(facing_bet / (pot + facing_bet) * 100, 1)

    hand_eq = max(equity, outs_eq)

    if hero_action == "call" and facing_bet > 0:
        if hand_eq >= pot_odds_val:
            feedback.append(f"CALL justified: need {pot_odds_val}% equity, you have ~{hand_eq:.0f}%.")
        else:
            feedback.append(f"WARNING: need {pot_odds_val}% equity but you have ~{hand_eq:.0f}%. Call is -EV on math.")
            if spr > 3 and outs_eq > pot_odds_val * 0.7:
                feedback.append(f"However SPR={spr:.1f} gives implied odds — may be +EV if villain pays off.")
            else:
                is_correct = False
                corrections.append("Consider folding. Math doesn't support calling.")

    if hero_action in ("bet", "raise") and hero_amount > 0:
        pot_pct = hero_amount / pot * 100 if pot > 0 else 0
        mdf = pot / (pot + hero_amount) * 100
        if classification == "S":
            if pot_pct < 50:
                feedback.append(f"Strong hand [S] but only {pot_pct:.0f}% pot. Bet bigger (67-100%) to extract max value.")
            else:
                feedback.append(f"Good sizing ({pot_pct:.0f}% pot) with strong hand. Villain MDF: {mdf:.0f}%.")
        elif classification == "B":
            if pot_pct > 75:
                feedback.append(f"Good-not-nut [B] but {pot_pct:.0f}% pot is large. Consider 40-60% — get calls from worse, not just better.")
            else:
                feedback.append(f"Reasonable sizing ({pot_pct:.0f}% pot) for [B] hand. Good value/control balance.")
        else:
            if num_outs >= 8:
                feedback.append(f"Semi-bluff with {num_outs} outs ({outs_eq:.0f}% draw equity). Has fold equity + draw equity.")
            elif num_outs >= 4:
                feedback.append(f"Thin semi-bluff with {num_outs} outs. Relies heavily on fold equity.")
            else:
                be_fold = hero_amount / (pot + hero_amount) * 100
                feedback.append(f"Pure bluff with {num_outs} outs. Villain must fold >{be_fold:.0f}% for this to be +EV.")
                for v in state["villains"]:
                    if v["active"] and v["type"] == "CALLING_STATION":
                        is_correct = False
                        corrections.append(f"STOP: {v['name']} is a Calling Station (fold to cbet ~{v['ftcb']:.0f}%). Bluffing burns money.")

    if hero_action == "check":
        if classification == "S" and spr < 4:
            is_correct = False
            corrections.append("Bet for value! Strong hand + low SPR = build pot to stack off by river.")
            feedback.append(f"Checking [S] hand with SPR={spr:.1f} gives up value.")
        elif classification == "C":
            feedback.append("Check with [C] is fine. No value to extract, no credible bluff story.")

    if hero_action == "fold":
        if facing_bet > 0 and equity > pot_odds_val * 1.1:
            is_correct = False
            corrections.append(f"Folding with {equity:.0f}% equity but only need {pot_odds_val}% to call. This fold is -EV.")
        elif facing_bet == 0 and classification in ("S", "B"):
            is_correct = False
            corrections.append("Folding without facing a bet? At minimum check for a free card.")

    # Reasoning warnings
    warnings = []
    if hero_action in ("bet","raise") and classification == "C":
        warnings.append("REMINDER: 'Betting for information' is NOT valid. Bets must be for VALUE (called by worse) or as a BLUFF (better hands fold).")

    # Recommendation
    rec_en, rec_th = _recommend(classification, spr, equity, facing_bet, pot, num_outs, outs_eq, state)

    # EV
    ev_text = ""
    if hero_action == "call" and facing_bet > 0:
        ev = (equity/100)*(pot+facing_bet) - ((1-equity/100)*facing_bet)
        ev_text = f"EV(call) = ({equity:.0f}% × ${pot+facing_bet:.0f}) - ({100-equity:.0f}% × ${facing_bet:.0f}) = ${ev:.1f}"
    elif hero_action in ("bet","raise") and hero_amount > 0:
        be = hero_amount / (pot + hero_amount) * 100
        ev_text = f"Break-even fold equity: {be:.1f}%. If villain folds >{be:.0f}%, bet is immediately profitable."

    return {
        "hand_name": hand_name,
        "classification": classification,
        "reason_en": reason_en,
        "reason_th": reason_th,
        "texture_path": state.get("texture_path", ""),
        "pot": pot,
        "effective_stack": eff,
        "spr": round(spr, 1),
        "spr_guide": spr_guide,
        "outs": num_outs,
        "outs_equity": round(outs_eq, 1),
        "equity_vs_villains": equity_details,
        "pot_odds": pot_odds_val,
        "feedback": feedback,
        "corrections": corrections,
        "warnings": warnings,
        "is_correct": is_correct,
        "recommendation_en": rec_en,
        "recommendation_th": rec_th,
        "ev_text": ev_text,
        "grade": "GOOD" if is_correct else "NEEDS IMPROVEMENT",
    }


def _recommend(cls, spr, equity, facing, pot, outs, outs_eq, state):
    if facing > 0:
        po = facing / (pot + facing) * 100
        if cls == "S":
            return (f"RAISE for value. Raise to ~${facing*3:.0f} (3x).", f"RAISE ดึงค่า ~${facing*3:.0f}")
        elif cls == "B":
            if equity > po + 10:
                return (f"CALL. Equity ({equity:.0f}%) > pot odds ({po:.0f}%).", f"CALL Equity ({equity:.0f}%) > pot odds ({po:.0f}%)")
            return ("Marginal. CALL if SPR ok, FOLD if pot too big.", "50/50 CALL ถ้า SPR ดี FOLD ถ้า pot ใหญ่เกิน")
        else:
            if equity >= po:
                return (f"CALL on equity ({equity:.0f}% vs {po:.0f}% needed).", f"CALL ตาม equity ({equity:.0f}% vs ต้องการ {po:.0f}%)")
            return ("FOLD. Save chips.", "FOLD เก็บชิปไว้")
    else:
        if cls == "S":
            b = pot * 0.67
            return (f"BET ${b:.0f} (67% pot) for value.", f"BET ${b:.0f} (67% pot) ดึงค่า")
        elif cls == "B":
            b = pot * 0.5
            return (f"BET ${b:.0f} (50% pot) thin value or CHECK to control.", f"BET ${b:.0f} (50% pot) หรือ CHECK คุม pot")
        else:
            if outs >= 8:
                b = pot * 0.5
                return (f"BET ${b:.0f} semi-bluff ({outs} outs).", f"BET ${b:.0f} semi-bluff ({outs} outs)")
            return ("CHECK. No value, not enough equity to bluff.", "CHECK ไม่มีค่าดึง ไม่มี equity พอบลัฟ")


# =============================================================================
# GAME STATE MANAGEMENT
# =============================================================================

def create_new_hand(body):
    hero_pos = body.get("position", random.choice(POSITIONS))
    hero_cards_input = body.get("cards", None)
    num_villains = int(body.get("num_villains", random.randint(1, 3)))
    num_villains = max(1, min(4, num_villains))

    if hero_cards_input and len(hero_cards_input) == 2:
        hero_cards = hero_cards_input
        deck = make_deck(hero_cards)
    else:
        deck = make_deck()
        random.shuffle(deck)
        hero_cards = [deck.pop(), deck.pop()]

    random.shuffle(deck)

    available_pos = [p for p in POSITIONS if p != hero_pos]
    random.shuffle(available_pos)

    villains = []
    for i in range(min(num_villains, len(available_pos))):
        vpos = available_pos[i]
        vtype = random.choice(["TAG","LAG","NIT","FISH","CALLING_STATION","MANIAC"])
        tmpl = VILLAIN_TEMPLATES[vtype]
        stack_var = random.uniform(0.7, 1.5)
        v = {
            "name": f"Villain_{vpos}",
            "position": vpos,
            "type": vtype,
            "stack": round(500 * stack_var),
            "vpip": tmpl["vpip"],
            "pfr": tmpl["pfr"],
            "af": tmpl["af"],
            "ftcb": tmpl["ftcb"],
            "3b": tmpl["3b"],
            "wtsd": tmpl["wtsd"],
            "notes": VILLAIN_NOTES.get(vtype, ""),
            "active": True,
        }
        villains.append(v)

    pot = 4.0  # SB + BB
    invested = {}
    for v in villains:
        if v["position"] == "SB": invested[v["name"]] = 1
        elif v["position"] == "BB": invested[v["name"]] = 3
        else: invested[v["name"]] = 0
    if hero_pos == "SB": invested["Hero"] = 1
    elif hero_pos == "BB": invested["Hero"] = 3
    else: invested["Hero"] = 0

    # Generate preflop villain actions before hero
    hero_idx = POSITIONS.index(hero_pos)
    actions_before = []
    current_raise = 3
    has_raise = False

    for pos in POSITIONS:
        if pos == hero_pos:
            break
        v = next((vv for vv in villains if vv["position"] == pos and vv["active"]), None)
        if not v:
            continue
        act = gen_villain_preflop(v, has_raise, current_raise)
        already_in = invested.get(v["name"], 0)
        if act["type"] == "fold":
            v["active"] = False
            actions_before.append({"actor": v["name"], "action": "fold", "amount": 0})
        elif act["type"] == "call":
            additional = max(0, act["amount"] - already_in)
            pot += additional
            v["stack"] -= additional
            invested[v["name"]] = act["amount"]
            actions_before.append({"actor": v["name"], "action": "call", "amount": additional})
        elif act["type"] == "raise":
            additional = max(0, act["amount"] - already_in)
            pot += additional
            v["stack"] -= additional
            invested[v["name"]] = act["amount"]
            current_raise = act["amount"]
            has_raise = True
            actions_before.append({"actor": v["name"], "action": "raise", "amount": act["amount"]})

    facing = current_raise
    pot_odds = round(facing / (pot + facing) * 100, 1) if facing > 0 else 0

    eff_stack = 500
    active_v_stacks = [v["stack"] for v in villains if v["active"]]
    if active_v_stacks:
        eff_stack = min(500, min(active_v_stacks))

    state = {
        "hero_cards": hero_cards,
        "hero_position": hero_pos,
        "hero_stack": 500,
        "board": [],
        "pot": pot,
        "effective_stack": eff_stack,
        "street": "preflop",
        "facing_bet": facing,
        "villains": villains,
        "deck": deck,
        "invested": invested,
        "texture_path": "",
        "actions_log": actions_before,
    }

    return {
        "state": state,
        "display": {
            "street": "PREFLOP",
            "hero_cards": cards_display(hero_cards),
            "hero_cards_raw": hero_cards,
            "hero_position": hero_pos,
            "hero_stack": 500,
            "hero_stack_bb": round(500/3, 1),
            "effective_stack": eff_stack,
            "effective_stack_bb": round(eff_stack/3, 1),
            "spr": round(eff_stack / pot, 1) if pot > 0 else 999,
            "pot": pot,
            "facing_bet": facing,
            "pot_odds": pot_odds,
            "board": "",
            "board_raw": [],
            "villains": [{
                "name": v["name"], "position": v["position"],
                "type": v["type"], "stack": v["stack"],
                "vpip": v["vpip"], "pfr": v["pfr"],
                "three_bet": v["3b"], "af": v["af"],
                "ftcb": v["ftcb"], "wtsd": v["wtsd"],
                "notes": v["notes"], "active": v["active"],
            } for v in villains],
            "actions_before": actions_before,
            "texture_path": "",
            "options": _get_options(facing),
        }
    }


def process_hero_action(body):
    state = body["state"]
    hero_action = body["action"]  # "fold","check","call","bet","raise"
    hero_amount = float(body.get("amount", 0))

    hero = state["hero_cards"]
    board = state["board"]
    pot = state["pot"]
    facing = state["facing_bet"]
    deck = state["deck"]
    invested = state["invested"]

    # Auto-convert bet to raise when facing
    if hero_action == "bet" and facing > 0:
        hero_action = "raise"

    if hero_action == "call":
        hero_amount = facing

    if hero_action in ("bet", "raise") and hero_amount <= 0:
        hero_amount = pot * 0.67

    # --- FOLD ---
    if hero_action == "fold":
        analysis = None
        if board:
            analysis = analyze_action(state, hero_action, 0, facing)
        return {"state": state, "result": "fold", "analysis": analysis,
                "message": "You fold. Hand over.", "hand_complete": True}

    # Apply hero action to pot
    hero_in = invested.get("Hero", 0)
    if hero_action == "call":
        additional = max(0, hero_amount - hero_in)
        state["pot"] += additional
        state["hero_stack"] -= additional
        invested["Hero"] = hero_amount
    elif hero_action in ("bet", "raise"):
        additional = max(0, hero_amount - hero_in)
        state["pot"] += additional
        state["hero_stack"] -= additional
        invested["Hero"] = hero_amount
    # check = no money

    # Run analysis/critique
    analysis = None
    if board:
        analysis = analyze_action(state, hero_action, hero_amount, facing)

    # Villain responses
    villain_responses = []
    if hero_action in ("bet", "raise"):
        for v in state["villains"]:
            if not v["active"]:
                continue
            if state["street"] == "preflop":
                resp = gen_villain_preflop(v, True, hero_amount)
            else:
                resp = gen_villain_postflop(v, state["pot"], True, hero_amount)
            v_in = invested.get(v["name"], 0)
            if resp["type"] == "fold":
                v["active"] = False
                villain_responses.append({"actor": v["name"], "action": "fold", "amount": 0})
            elif resp["type"] == "call":
                add = max(0, resp["amount"] - v_in)
                state["pot"] += add
                v["stack"] -= add
                invested[v["name"]] = resp["amount"]
                villain_responses.append({"actor": v["name"], "action": "call", "amount": add})
            elif resp["type"] == "raise":
                add = max(0, resp["amount"] - v_in)
                state["pot"] += add
                v["stack"] -= add
                invested[v["name"]] = resp["amount"]
                villain_responses.append({"actor": v["name"], "action": "raise", "amount": resp["amount"]})

    # Check if all villains folded
    if not any(v["active"] for v in state["villains"]):
        return {"state": state, "result": "win", "analysis": analysis,
                "villain_responses": villain_responses,
                "message": f"All villains fold! You win ${state['pot']:.0f}.", "hand_complete": True}

    # Advance to next street
    return _advance_street(state, deck, invested, analysis, villain_responses)


def _advance_street(state, deck, invested, analysis, villain_responses):
    current = state["street"]
    hero = state["hero_cards"]

    # Reset invested for new street
    invested_reset = {k: 0 for k in invested}
    state["invested"] = invested_reset

    if current == "preflop":
        # Deal flop
        flop = [deck.pop() for _ in range(3)]
        state["board"] = flop
        state["street"] = "flop"
        state["deck"] = deck
        cls, _, _ = classify_sbc(hero, flop)
        state["texture_path"] = cls
    elif current == "flop":
        turn = deck.pop()
        state["board"].append(turn)
        state["street"] = "turn"
        state["deck"] = deck
        cls, _, _ = classify_sbc(hero, state["board"])
        state["texture_path"] += cls
    elif current == "turn":
        river = deck.pop()
        state["board"].append(river)
        state["street"] = "river"
        state["deck"] = deck
        cls, _, _ = classify_sbc(hero, state["board"])
        state["texture_path"] += cls
    elif current == "river":
        # Showdown
        return _showdown(state, analysis, villain_responses)

    # Generate villain action on new street (before hero)
    pot = state["pot"]
    villain_street_actions = []
    facing = 0
    for v in state["villains"]:
        if not v["active"]:
            continue
        act = gen_villain_postflop(v, pot, facing > 0, facing)
        if act["type"] == "fold":
            v["active"] = False
            villain_street_actions.append({"actor": v["name"], "action": "fold", "amount": 0})
        elif act["type"] == "check":
            villain_street_actions.append({"actor": v["name"], "action": "check", "amount": 0})
        elif act["type"] == "bet":
            state["pot"] += act["amount"]
            v["stack"] -= act["amount"]
            facing = act["amount"]
            villain_street_actions.append({"actor": v["name"], "action": "bet", "amount": act["amount"]})
        elif act["type"] == "call":
            state["pot"] += act["amount"]
            v["stack"] -= act["amount"]
            villain_street_actions.append({"actor": v["name"], "action": "call", "amount": act["amount"]})
        elif act["type"] == "raise":
            state["pot"] += act["amount"]
            v["stack"] -= act["amount"]
            facing = act["amount"]
            villain_street_actions.append({"actor": v["name"], "action": "raise", "amount": act["amount"]})

    if not any(v["active"] for v in state["villains"]):
        return {"state": state, "result": "win", "analysis": analysis,
                "villain_responses": villain_responses,
                "villain_street_actions": villain_street_actions,
                "message": f"All villains fold! You win ${state['pot']:.0f}.", "hand_complete": True}

    state["facing_bet"] = facing

    board = state["board"]
    cls, reason_en, reason_th = classify_sbc(hero, board)
    ranking = evaluate_hand(hero + board)
    hand_name = HAND_RANKINGS[ranking[0]]
    num_outs, _ = count_outs(hero, board) if state["street"] != "river" else (0, [])
    mult = 4 if state["street"] == "flop" else 2
    outs_eq = min(num_outs * mult, 100) if state["street"] != "river" else 0

    eff = state["effective_stack"]
    active_v = [v["stack"] for v in state["villains"] if v["active"]]
    if active_v:
        eff = min(state["hero_stack"], min(active_v))
    state["effective_stack"] = eff

    pot_odds_val = round(facing / (state["pot"] + facing) * 100, 1) if facing > 0 else 0
    spr = round(eff / state["pot"], 1) if state["pot"] > 0 else 999

    return {
        "state": state,
        "result": "continue",
        "analysis": analysis,
        "villain_responses": villain_responses,
        "display": {
            "street": state["street"].upper(),
            "hero_cards": cards_display(hero),
            "hero_cards_raw": hero,
            "board": cards_display(board),
            "board_raw": board,
            "hand_name": hand_name,
            "classification": cls,
            "reason_en": reason_en,
            "reason_th": reason_th,
            "texture_path": state["texture_path"],
            "pot": state["pot"],
            "effective_stack": eff,
            "spr": spr,
            "facing_bet": facing,
            "pot_odds": pot_odds_val,
            "outs": num_outs,
            "outs_equity": outs_eq,
            "hero_stack": state["hero_stack"],
            "villain_street_actions": villain_street_actions,
            "villains": [{
                "name": v["name"], "position": v["position"],
                "type": v["type"], "stack": v["stack"],
                "vpip": v["vpip"], "pfr": v["pfr"],
                "three_bet": v["3b"], "af": v["af"],
                "ftcb": v["ftcb"], "wtsd": v["wtsd"],
                "notes": v["notes"], "active": v["active"],
            } for v in state["villains"]],
            "options": _get_options(facing),
        },
        "hand_complete": False,
    }


def _showdown(state, analysis, villain_responses):
    hero = state["hero_cards"]
    board = state["board"]
    hero_ev = evaluate_hand(hero + board)
    hero_hand = HAND_RANKINGS[hero_ev[0]]

    results = []
    for v in state["villains"]:
        if not v["active"]:
            continue
        vr = build_range_hands(v["type"], v["position"])
        known = set(hero + board)
        valid = [h for h in vr if not any(c in known for c in h)]
        if valid:
            vh = random.choice(valid)
            vev = evaluate_hand(vh + board)
            vhand = HAND_RANKINGS[vev[0]]
            if hero_ev > vev:
                outcome = "WIN"
            elif hero_ev == vev:
                outcome = "TIE"
            else:
                outcome = "LOSE"
            results.append({
                "name": v["name"], "cards": cards_display(vh), "cards_raw": vh,
                "hand": vhand, "outcome": outcome,
            })

    cls, _, _ = classify_sbc(hero, board)
    state["texture_path"] = state.get("texture_path", "") + cls if state["street"] == "river" else state.get("texture_path", "")

    return {
        "state": state,
        "result": "showdown",
        "analysis": analysis,
        "villain_responses": villain_responses,
        "showdown": {
            "hero_cards": cards_display(hero),
            "hero_hand": hero_hand,
            "board": cards_display(board),
            "pot": state["pot"],
            "texture_path": state.get("texture_path", ""),
            "results": results,
        },
        "hand_complete": True,
    }


def _get_options(facing):
    if facing > 0:
        return ["fold", "call", "raise"]
    return ["check", "bet"]


# =============================================================================
# VERCEL HANDLER
# =============================================================================

class handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            action = params.get("action", [""])[0]

            content_length = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_length) if content_length > 0 else b""
            body = json.loads(body_raw) if body_raw else {}

            if action == "new_hand":
                result = create_new_hand(body)
            elif action == "hero_act":
                result = process_hero_action(body)
            else:
                result = {"error": f"Unknown action: '{action}'. Use ?action=new_hand or ?action=hero_act"}

            self._send_json(result)
        except Exception as e:
            import traceback
            self._send_json({"error": str(e), "traceback": traceback.format_exc()}, 500)

    def do_OPTIONS(self):
        self._send_json({})

    def do_GET(self):
        self._send_json({
            "name": "Poker Decision Training Simulator",
            "version": "1.0.0",
            "status": "ok",
            "endpoints": {
                "POST /api/game?action=new_hand": "Start a new hand",
                "POST /api/game?action=hero_act": "Submit action + get critique",
            }
        })
