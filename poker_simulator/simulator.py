"""
Interactive Poker Decision Training Simulator.
Human-in-the-loop: stops at each street for hero's decision.
"""

import sys

from .models import (
    Card, Street, ActionType, PlayerAction, HandState, PlayerType, Position,
)
from .scenarios import (
    ScenarioGenerator, format_preflop_display, format_postflop_display,
    format_hand_summary, format_cards, format_board_display,
)
from .analysis import DecisionAnalyzer, format_analysis_display
from .classifier import classify_hand_vs_board
from .evaluator import evaluate_hand, hand_rank_name


BANNER = r"""
================================================================
  POKER DECISION TRAINING SIMULATOR
  ระบบฝึกตัดสินใจโป๊กเกอร์
================================================================
  $1/$3 NLH Cash Game  |  9-max
  Board Classification: S/B/C Model
  Mode: Human-in-the-Loop (you decide, I critique)
================================================================
"""


def parse_hero_action(input_str: str, state: HandState) -> tuple[ActionType, float]:
    """Parse hero's input into (ActionType, amount)."""
    parts = input_str.strip().lower().split()
    if not parts:
        raise ValueError("Empty input")

    action_str = parts[0]
    amount = 0.0

    if len(parts) > 1:
        try:
            amount = float(parts[1].replace("$", ""))
        except ValueError:
            pass

    action_map = {
        "fold": ActionType.FOLD,
        "f": ActionType.FOLD,
        "check": ActionType.CHECK,
        "x": ActionType.CHECK,
        "call": ActionType.CALL,
        "c": ActionType.CALL,
        "bet": ActionType.BET,
        "b": ActionType.BET,
        "raise": ActionType.RAISE,
        "r": ActionType.RAISE,
        "all-in": ActionType.ALL_IN,
        "allin": ActionType.ALL_IN,
        "ai": ActionType.ALL_IN,
        "shove": ActionType.ALL_IN,
    }

    action_type = action_map.get(action_str)
    if action_type is None:
        raise ValueError(f"Unknown action: {action_str}")

    # Default amounts
    if action_type == ActionType.CALL:
        amount = state.current_bet

    if action_type == ActionType.ALL_IN:
        amount = state.hero_stack
        action_type = ActionType.RAISE

    if action_type in (ActionType.BET, ActionType.RAISE) and amount <= 0:
        # Default bet = 2/3 pot
        amount = state.pot * 0.67

    return action_type, amount


def run_hand(
    hero_position: Position = None,
    hero_cards: list[Card] = None,
    num_villains: int = 0,
    villain_types: list[PlayerType] = None,
):
    """Run a single hand interactively."""
    gen = ScenarioGenerator(
        stakes=(1.0, 3.0),
        effective_stack=500.0,
        hero_vpip_range=15.0,
    )

    # Generate hand
    state = gen.generate_hand(
        hero_position=hero_position,
        hero_cards=hero_cards,
        num_villains=num_villains,
        villain_types=villain_types,
    )

    # =========================================================================
    # PREFLOP
    # =========================================================================
    preflop_actions = gen.generate_preflop_action(state)
    print(format_preflop_display(state, preflop_actions))

    # If all villains folded preflop
    if not state.active_villains:
        print("  Everyone folds! You win the blinds.\n")
        return

    # Get hero preflop action
    hero_action, hero_amount = _get_hero_action(state, "Preflop")

    # Process hero action
    if hero_action == ActionType.FOLD:
        print("\n  You fold. Hand over.\n")
        return

    if hero_action == ActionType.CALL:
        state.pot += hero_amount
        state.hero_stack -= hero_amount
    elif hero_action in (ActionType.RAISE, ActionType.BET):
        state.pot += hero_amount
        state.hero_stack -= hero_amount
        state.current_bet = hero_amount

    state.action_history.append(
        PlayerAction("Hero", hero_action, hero_amount, Street.PREFLOP)
    )

    # Villain responses to hero's preflop action (players after hero)
    if hero_action in (ActionType.RAISE, ActionType.BET):
        from .opponents import generate_villain_preflop_action
        for v in state.villains:
            if v.name not in state.active_villains:
                continue
            # Only villains who haven't acted or need to respond
            resp = generate_villain_preflop_action(
                v, state, facing_raise=True, raise_amount=hero_amount,
            )
            state.action_history.append(resp)
            if resp.action_type == ActionType.FOLD:
                state.active_villains.remove(v.name)
                print(f"  {resp}")
            elif resp.action_type == ActionType.CALL:
                state.pot += resp.amount
                v.stack -= resp.amount
                print(f"  {resp}")
            elif resp.action_type == ActionType.RAISE:
                state.pot += resp.amount
                v.stack -= resp.amount
                print(f"  {resp}")
                # Simplified: hero gets one more action vs 3bet
                print(f"\n  Facing 3-bet to ${resp.amount:.0f}")
                print(f"  Pot: ${state.pot:.0f}")
                state.current_bet = resp.amount
                h_act, h_amt = _get_hero_action(state, "Preflop (vs 3bet)")
                if h_act == ActionType.FOLD:
                    print("\n  You fold to the 3-bet. Hand over.\n")
                    return
                elif h_act == ActionType.CALL:
                    state.pot += h_amt
                    state.hero_stack -= h_amt
                elif h_act in (ActionType.RAISE, ActionType.BET):
                    state.pot += h_amt
                    state.hero_stack -= h_amt

    if not state.active_villains:
        print("\n  All villains fold! You win the pot of ${:.0f}.\n".format(state.pot))
        return

    # =========================================================================
    # FLOP
    # =========================================================================
    flop = gen.deal_flop(state)
    state.current_bet = 0.0

    # Villain postflop action (those OOP to hero)
    villain_flop_actions = gen.generate_villain_postflop_actions(state, hero_acted=False)
    print(format_postflop_display(state, "Flop", villain_flop_actions))

    if not state.active_villains:
        print("  All villains fold on the flop! You win.\n")
        return

    hero_action, hero_amount = _get_hero_action(state, "Flop")

    # Analyze and critique
    _analyze_and_critique(state, hero_action, hero_amount, state.current_bet)

    if hero_action == ActionType.FOLD:
        print("\n  You fold on the flop. Hand over.\n")
        return

    # Process hero action
    if hero_action == ActionType.CHECK:
        pass
    elif hero_action == ActionType.CALL:
        state.pot += hero_amount
        state.hero_stack -= hero_amount
    elif hero_action in (ActionType.BET, ActionType.RAISE):
        state.pot += hero_amount
        state.hero_stack -= hero_amount
        # Villain responses
        resp_actions = gen.generate_villain_postflop_actions(
            state, hero_acted=True, hero_bet=hero_amount,
        )
        for a in resp_actions:
            print(f"  {a}")

    state.action_history.append(
        PlayerAction("Hero", hero_action, hero_amount, Street.FLOP)
    )

    if not state.active_villains:
        print(f"\n  All villains fold! You win the pot of ${state.pot:.0f}.\n")
        return

    # =========================================================================
    # TURN
    # =========================================================================
    turn = gen.deal_turn(state)
    state.current_bet = 0.0

    villain_turn_actions = gen.generate_villain_postflop_actions(state, hero_acted=False)
    print(format_postflop_display(state, "Turn", villain_turn_actions))

    if not state.active_villains:
        print("  All villains fold on the turn! You win.\n")
        return

    hero_action, hero_amount = _get_hero_action(state, "Turn")
    _analyze_and_critique(state, hero_action, hero_amount, state.current_bet)

    if hero_action == ActionType.FOLD:
        print("\n  You fold on the turn. Hand over.\n")
        return

    if hero_action == ActionType.CHECK:
        pass
    elif hero_action == ActionType.CALL:
        state.pot += hero_amount
        state.hero_stack -= hero_amount
    elif hero_action in (ActionType.BET, ActionType.RAISE):
        state.pot += hero_amount
        state.hero_stack -= hero_amount
        resp_actions = gen.generate_villain_postflop_actions(
            state, hero_acted=True, hero_bet=hero_amount,
        )
        for a in resp_actions:
            print(f"  {a}")

    state.action_history.append(
        PlayerAction("Hero", hero_action, hero_amount, Street.TURN)
    )

    if not state.active_villains:
        print(f"\n  All villains fold! You win the pot of ${state.pot:.0f}.\n")
        return

    # =========================================================================
    # RIVER
    # =========================================================================
    river = gen.deal_river(state)
    state.current_bet = 0.0

    villain_river_actions = gen.generate_villain_postflop_actions(state, hero_acted=False)
    print(format_postflop_display(state, "River", villain_river_actions))

    if not state.active_villains:
        print("  All villains fold on the river! You win.\n")
        return

    hero_action, hero_amount = _get_hero_action(state, "River")
    _analyze_and_critique(state, hero_action, hero_amount, state.current_bet)

    if hero_action == ActionType.FOLD:
        print("\n  You fold on the river. Hand over.\n")
        return

    if hero_action == ActionType.CHECK:
        pass
    elif hero_action == ActionType.CALL:
        state.pot += hero_amount
        state.hero_stack -= hero_amount
    elif hero_action in (ActionType.BET, ActionType.RAISE):
        state.pot += hero_amount
        state.hero_stack -= hero_amount
        resp_actions = gen.generate_villain_postflop_actions(
            state, hero_acted=True, hero_bet=hero_amount,
        )
        for a in resp_actions:
            print(f"  {a}")

    state.action_history.append(
        PlayerAction("Hero", hero_action, hero_amount, Street.RIVER)
    )

    # =========================================================================
    # SHOWDOWN
    # =========================================================================
    _showdown(state)


def _get_hero_action(state: HandState, street_name: str) -> tuple[ActionType, float]:
    """Get hero's action from stdin."""
    while True:
        try:
            raw = input(f"  [{street_name}] Your action > ").strip()
            if not raw:
                continue
            action, amount = parse_hero_action(raw, state)

            # Validate
            if action == ActionType.CHECK and state.current_bet > 0:
                print("  Cannot check - there's a bet to you. Choose call/raise/fold.")
                continue
            if action in (ActionType.BET,) and state.current_bet > 0:
                print("  There's already a bet. Use 'raise [amount]' instead.")
                continue

            return action, amount

        except ValueError as e:
            print(f"  Invalid input: {e}")
            print("  Use: fold / check / call / bet [amount] / raise [amount] / allin")
        except EOFError:
            print("\n  Exiting...")
            sys.exit(0)


def _analyze_and_critique(
    state: HandState,
    hero_action: ActionType,
    hero_amount: float,
    facing_bet: float,
):
    """Run analysis and print critique."""
    analyzer = DecisionAnalyzer(state)
    analysis = analyzer.full_analysis()
    critique = analyzer.critique_action(hero_action, hero_amount, facing_bet)
    print(format_analysis_display(analysis, critique))


def _showdown(state: HandState):
    """Handle showdown."""
    print("\n" + "=" * 65)
    print("  SHOWDOWN / โชว์ดาวน์")
    print("=" * 65)

    hero_cards = state.hero_cards
    board = state.board_cards
    hero_ranking, hero_kickers = evaluate_hand(hero_cards + board)

    print(f"\n  Your Hand: [{format_cards(hero_cards)}]")
    print(f"  Board: {format_board_display(state)}")
    print(f"  You have: {hand_rank_name(hero_ranking)}")
    print(f"  Texture Path: [{state.texture_code}]")
    print(f"  Final Pot: ${state.pot:.0f}")

    # Generate villain showdown hands (simplified)
    import random
    from .opponents import build_range_cards

    for v in state.villains:
        if v.name in state.active_villains:
            v_range = build_range_cards(v.player_type, v.position)
            # Filter out cards already dealt
            known = {(c.rank, c.suit) for c in hero_cards + board}
            valid = [h for h in v_range if not any((c.rank, c.suit) in known for c in h)]
            if valid:
                v_hand = random.choice(valid)
                v_ranking, v_kickers = evaluate_hand(v_hand + board)
                print(f"\n  {v.name}: [{format_cards(v_hand)}]")
                print(f"  {v.name} has: {hand_rank_name(v_ranking)}")

                hero_score = (hero_ranking.value, hero_kickers)
                v_score = (v_ranking.value, v_kickers)

                if hero_score > v_score:
                    print(f"\n  >>> YOU WIN! +${state.pot:.0f} <<<")
                elif hero_score == v_score:
                    print(f"\n  >>> SPLIT POT <<<")
                else:
                    print(f"\n  >>> YOU LOSE. -{state.pot:.0f} <<<")

    print("\n" + "=" * 65)
    print("  HAND COMPLETE / จบมือ")
    print("=" * 65)

    # Final summary
    print(f"\n  Hand Path: [{state.texture_code}]")
    print("  This means:")
    for i, t in enumerate(state.texture_path):
        street_names = ["Flop", "Turn", "River"]
        if i < len(street_names):
            tex_desc = {
                "S": "Nut (สัมพันธ์กับไพ่ที่ดีที่สุด)",
                "B": "Good (ดีแต่ไม่ใช่ nut)",
                "C": "Unconnected (ไม่สัมพันธ์)",
            }
            print(f"    {street_names[i]}: [{t.value}] = {tex_desc.get(t.value, t.value)}")

    print()


# =============================================================================
# Entry point
# =============================================================================

def main():
    """Main entry point for the simulator."""
    print(BANNER)

    while True:
        print("\n  OPTIONS:")
        print("  1. Deal a random hand")
        print("  2. Specify your cards and position")
        print("  3. Quit")

        try:
            choice = input("\n  Choose > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye!")
            break

        if choice == "1":
            run_hand()
        elif choice == "2":
            try:
                pos_input = input("  Position (UTG/UTG+1/UTG+2/LJ/HJ/CO/BTN/SB/BB) > ").strip().upper()
                pos_map = {
                    "UTG": Position.UTG, "UTG+1": Position.UTG1, "UTG+2": Position.UTG2,
                    "LJ": Position.LJ, "HJ": Position.HJ, "CO": Position.CO,
                    "BTN": Position.BTN, "SB": Position.SB, "BB": Position.BB,
                }
                hero_pos = pos_map.get(pos_input, Position.BTN)

                cards_input = input("  Your cards (e.g., 'Ah Kd') > ").strip()
                card_strs = cards_input.split()
                hero_cards = [Card.from_str(s) for s in card_strs[:2]]

                num_v = input("  Number of villains (1-4, default=2) > ").strip()
                num_villains = int(num_v) if num_v else 2
                num_villains = max(1, min(4, num_villains))

                run_hand(
                    hero_position=hero_pos,
                    hero_cards=hero_cards,
                    num_villains=num_villains,
                )
            except (ValueError, IndexError) as e:
                print(f"  Error: {e}. Try again.")
        elif choice in ("3", "q", "quit", "exit"):
            print("\n  Goodbye! ขอบคุณที่ฝึกซ้อม!")
            break
        else:
            print("  Invalid choice. Try 1, 2, or 3.")


if __name__ == "__main__":
    main()
