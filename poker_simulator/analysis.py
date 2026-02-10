"""
Decision analysis engine.
Critiques hero's decisions using EV, range logic, SPR, pot odds, MDF.
NO solver jargon - simple math only.
"""

from .models import (
    HandState, ActionType, BoardTexture, PlayerType,
    VillainProfile, Street, Card,
)
from .evaluator import (
    evaluate_hand, hand_rank_name, estimate_equity_vs_range,
    count_outs, outs_to_equity_rule,
)
from .classifier import classify_hand_vs_board
from .opponents import build_range_cards, describe_range_text


class DecisionAnalyzer:
    """Analyzes and critiques hero decisions at each street."""

    def __init__(self, hand_state: HandState):
        self.state = hand_state

    def full_analysis(self) -> dict:
        """Generate complete analysis of current situation."""
        board = self.state.board_cards
        hero = self.state.hero_cards

        result = {
            "pot": self.state.pot,
            "effective_stack": self.state.effective_stack,
            "spr": self.state.spr,
            "street": self.state.current_street.value,
            "texture_path": self.state.texture_code,
        }

        # Hand evaluation
        if board:
            ranking, kickers = evaluate_hand(hero + board)
            result["hand_ranking"] = hand_rank_name(ranking)

            # S/B/C classification
            texture, reason_en, reason_th = classify_hand_vs_board(hero, board)
            result["classification"] = texture.value
            result["classification_reason_en"] = reason_en
            result["classification_reason_th"] = reason_th

            # Outs (if not river)
            if self.state.current_street != Street.RIVER:
                num_outs, out_descriptions = count_outs(hero, board)
                street_name = "flop" if self.state.current_street == Street.FLOP else "turn"
                result["outs"] = num_outs
                result["outs_equity"] = outs_to_equity_rule(num_outs, street_name)
                result["outs_details"] = out_descriptions[:10]  # limit output

        # Equity vs villain range(s)
        if self.state.active_villains and board:
            equities = {}
            for v_name in self.state.active_villains:
                villain = next((v for v in self.state.villains if v.name == v_name), None)
                if villain:
                    v_range = build_range_cards(villain.player_type, villain.position)
                    equity = estimate_equity_vs_range(hero, board, v_range, simulations=3000)
                    equities[v_name] = {
                        "equity": round(equity, 1),
                        "range_desc": describe_range_text(villain.player_type, villain.position),
                    }
            result["equity_vs_villains"] = equities

        return result

    def critique_action(
        self,
        hero_action: ActionType,
        hero_amount: float = 0.0,
        facing_bet: float = 0.0,
    ) -> dict:
        """
        Critique hero's chosen action.
        Returns analysis with EV reasoning, not intuition.
        """
        analysis = self.full_analysis()
        critique = {
            "action": hero_action.value,
            "amount": hero_amount,
            "is_correct": True,
            "feedback": [],
            "corrections": [],
            "ev_analysis": "",
            "recommendation": "",
            "recommendation_th": "",
        }

        pot = self.state.pot
        spr = self.state.spr
        eff_stack = self.state.effective_stack
        texture = analysis.get("classification", "C")
        avg_equity = 50.0

        if "equity_vs_villains" in analysis:
            equities = [v["equity"] for v in analysis["equity_vs_villains"].values()]
            if equities:
                avg_equity = sum(equities) / len(equities)

        # =====================================================================
        # SPR-based framework
        # =====================================================================
        spr_guidance = self._spr_guidance(spr, texture)
        critique["spr_guidance"] = spr_guidance

        # =====================================================================
        # Pot odds check (for calls)
        # =====================================================================
        if hero_action == ActionType.CALL and facing_bet > 0:
            pot_odds = self.state.pot_odds(facing_bet)
            critique["pot_odds"] = round(pot_odds, 1)
            critique["equity_needed"] = round(pot_odds, 1)

            outs_equity = analysis.get("outs_equity", 0)
            hand_equity = max(avg_equity, outs_equity)

            if hand_equity >= pot_odds:
                critique["feedback"].append(
                    f"CALL is mathematically justified. "
                    f"You need {pot_odds:.1f}% equity, you have ~{hand_equity:.1f}%."
                )
            else:
                critique["feedback"].append(
                    f"WARNING: CALL needs {pot_odds:.1f}% equity but you have ~{hand_equity:.1f}%. "
                    f"This call is -EV purely on math."
                )
                # Check implied odds
                if spr > 3 and outs_equity > pot_odds * 0.7:
                    critique["feedback"].append(
                        f"However, with SPR={spr:.1f}, implied odds may make this call +EV "
                        f"if villain pays off when you hit."
                    )
                else:
                    critique["is_correct"] = False
                    critique["corrections"].append(
                        "Consider folding. The math doesn't support calling here."
                    )

        # =====================================================================
        # Bet/raise sizing analysis
        # =====================================================================
        if hero_action in (ActionType.BET, ActionType.RAISE) and hero_amount > 0:
            pot_pct = hero_amount / pot if pot > 0 else 0
            mdf = self.state.mdf(hero_amount)
            critique["bet_pot_pct"] = round(pot_pct * 100, 1)
            critique["mdf_for_villain"] = round(mdf, 1)

            if texture == "S":
                # Nut hand - size for value
                if pot_pct < 0.5:
                    critique["feedback"].append(
                        f"You have a strong hand (S classification) but bet only {pot_pct*100:.0f}% pot. "
                        f"Consider betting larger (67-100% pot) to extract maximum value."
                    )
                elif pot_pct >= 0.5:
                    critique["feedback"].append(
                        f"Good sizing at {pot_pct*100:.0f}% pot with a strong hand. "
                        f"Villain must defend {mdf:.0f}% of range (MDF)."
                    )
            elif texture == "B":
                if pot_pct > 0.75:
                    critique["feedback"].append(
                        f"You have a good-but-not-nut hand (B classification). "
                        f"Betting {pot_pct*100:.0f}% pot is large. "
                        f"Consider 40-60% pot - you want calls from worse hands, "
                        f"not to only get action from better hands."
                    )
                else:
                    critique["feedback"].append(
                        f"Reasonable bet size ({pot_pct*100:.0f}% pot) for a B-tier hand. "
                        f"Good for getting value from worse while controlling pot size."
                    )
            elif texture == "C":
                # Bluffing or semi-bluffing
                outs = analysis.get("outs", 0)
                if outs >= 8:
                    critique["feedback"].append(
                        f"Semi-bluff with {outs} outs ({analysis.get('outs_equity',0):.0f}% equity). "
                        f"This bet has fold equity + draw equity. Mathematically sound."
                    )
                elif outs >= 4:
                    critique["feedback"].append(
                        f"Thin semi-bluff with only {outs} outs. "
                        f"Relies heavily on fold equity. Make sure villain folds enough."
                    )
                elif outs < 4 and pot_pct > 0.5:
                    critique["feedback"].append(
                        f"Pure bluff with {outs} outs and {pot_pct*100:.0f}% pot sizing. "
                        f"Villain must fold {100-mdf:.0f}% for this to be +EV. "
                        f"Consider: does this villain fold that often?"
                    )
                    # Check against specific villain types
                    for v_name in self.state.active_villains:
                        villain = next((v for v in self.state.villains if v.name == v_name), None)
                        if villain and villain.player_type == PlayerType.CALLING_STATION:
                            critique["is_correct"] = False
                            critique["corrections"].append(
                                f"STOP: {v_name} is a Calling Station (fold to cbet ~{villain.fold_to_cbet:.0f}%). "
                                f"Bluffing a calling station is burning money."
                            )

        # =====================================================================
        # Check analysis
        # =====================================================================
        if hero_action == ActionType.CHECK:
            if texture == "S" and spr < 4:
                critique["feedback"].append(
                    f"You have a nut-tier hand (S) with low SPR ({spr:.1f}). "
                    f"Checking gives up value. With low SPR you should be building a pot "
                    f"to get stacks in by river."
                )
                critique["is_correct"] = False
                critique["corrections"].append(
                    "Bet for value. You have a strong hand and low SPR means "
                    "you can get all-in by river with natural pot growth."
                )
            elif texture == "S" and spr >= 4:
                critique["feedback"].append(
                    f"Check with a nut hand and high SPR ({spr:.1f}) can be a trap play. "
                    f"Valid if villain is aggressive and will bet into you. "
                    f"But generally betting for value is better than trapping."
                )
            elif texture == "C":
                critique["feedback"].append(
                    "Checking with an unconnected hand (C) is fine. "
                    "No point in betting without equity or a credible story."
                )

        # =====================================================================
        # Fold analysis
        # =====================================================================
        if hero_action == ActionType.FOLD:
            if facing_bet > 0:
                pot_odds = self.state.pot_odds(facing_bet)
                if avg_equity > pot_odds * 1.1:
                    critique["is_correct"] = False
                    critique["corrections"].append(
                        f"You're folding with {avg_equity:.1f}% equity vs villain's range, "
                        f"but you only need {pot_odds:.1f}% to call. "
                        f"This fold is -EV. You should at minimum call."
                    )
                else:
                    critique["feedback"].append(
                        f"Fold is acceptable. Equity ({avg_equity:.1f}%) is close to or below "
                        f"pot odds requirement ({pot_odds:.1f}%)."
                    )
            else:
                # Folding when not facing a bet
                if texture in ("S", "B"):
                    critique["is_correct"] = False
                    critique["corrections"].append(
                        "You're folding a decent hand when you're not even facing a bet. "
                        "At minimum check and see a free card."
                    )

        # =====================================================================
        # Common reasoning errors to correct
        # =====================================================================
        critique["reasoning_warnings"] = self._check_reasoning_errors(
            hero_action, texture, spr, avg_equity
        )

        # Final recommendation
        rec, rec_th = self._generate_recommendation(
            texture, spr, avg_equity, facing_bet, analysis
        )
        critique["recommendation"] = rec
        critique["recommendation_th"] = rec_th
        critique["ev_analysis"] = self._ev_summary(
            hero_action, hero_amount, facing_bet, pot, avg_equity, spr, texture
        )

        return critique

    def _spr_guidance(self, spr: float, texture: str) -> str:
        """SPR-based strategic guidance."""
        if spr <= 2:
            return (
                f"SPR = {spr:.1f} (Very Low). "
                f"Commit-or-fold territory. With strong hands (S/B), look to get all-in. "
                f"With weak hands (C), fold to aggression unless drawing."
            )
        elif spr <= 4:
            return (
                f"SPR = {spr:.1f} (Low). "
                f"One-pair hands are strong enough to stack off. "
                f"Plan for 2 streets of value (bet-bet-shove or bet-shove)."
            )
        elif spr <= 8:
            return (
                f"SPR = {spr:.1f} (Medium). "
                f"Need two-pair+ to comfortably stack off. "
                f"One-pair hands should exercise pot control. "
                f"Plan for 3 streets of action."
            )
        elif spr <= 15:
            return (
                f"SPR = {spr:.1f} (High). "
                f"Need very strong hands to stack off. Draws gain implied odds value. "
                f"Position and hand reading become critical."
            )
        else:
            return (
                f"SPR = {spr:.1f} (Very High). "
                f"Set-mining and drawing hands gain huge implied odds. "
                f"Big pairs are more vulnerable. Play cautiously without the nuts."
            )

    def _check_reasoning_errors(
        self, action: ActionType, texture: str, spr: float, equity: float,
    ) -> list[str]:
        """Flag common reasoning mistakes."""
        warnings = []

        # "Betting for information" is not a valid reason
        if action in (ActionType.BET, ActionType.RAISE) and texture == "C":
            warnings.append(
                "REMINDER: 'Betting for information' is NOT a valid reason to bet. "
                "Every bet needs to be either for VALUE (getting called by worse) "
                "or as a BLUFF (getting better hands to fold). "
                "If your bet accomplishes neither, it's a mistake."
            )

        return warnings

    def _generate_recommendation(
        self, texture: str, spr: float, equity: float,
        facing_bet: float, analysis: dict,
    ) -> tuple[str, str]:
        """Generate action recommendation."""
        pot = self.state.pot

        if facing_bet > 0:
            pot_odds = self.state.pot_odds(facing_bet)
            if texture == "S":
                return (
                    f"RAISE for value. You have the nuts/near-nuts. "
                    f"Raise to ~{facing_bet * 3:.0f} (3x) to build the pot.",
                    f"RAISE เพื่อดึงค่า คุณมีมือที่แข็งที่สุด "
                    f"Raise ไปที่ ~${facing_bet * 3:.0f} (3 เท่า) เพื่อสร้าง pot"
                )
            elif texture == "B":
                if equity > pot_odds + 10:
                    return (
                        f"CALL. Good hand but raising builds a pot you may not want. "
                        f"Equity ({equity:.0f}%) comfortably beats pot odds ({pot_odds:.0f}%).",
                        f"CALL ไพ่ดีแต่ raise จะทำให้ pot ใหญ่เกินไป "
                        f"Equity ({equity:.0f}%) > pot odds ({pot_odds:.0f}%)"
                    )
                else:
                    return (
                        f"Marginal spot. CALL if SPR supports it, FOLD if pot is too big.",
                        f"สถานการณ์ 50/50. CALL ถ้า SPR สนับสนุน, FOLD ถ้า pot ใหญ่เกินไป"
                    )
            else:  # C
                if equity >= pot_odds:
                    return (
                        f"CALL on equity. You have {equity:.0f}% vs needed {pot_odds:.0f}%.",
                        f"CALL ตาม equity มี {equity:.0f}% vs ต้องการ {pot_odds:.0f}%"
                    )
                else:
                    return (
                        f"FOLD. Equity ({equity:.0f}%) < pot odds ({pot_odds:.0f}%). Save your chips.",
                        f"FOLD. Equity ({equity:.0f}%) < pot odds ({pot_odds:.0f}%). เก็บชิปไว้"
                    )
        else:
            # Not facing a bet
            if texture == "S":
                bet_rec = pot * 0.67
                return (
                    f"BET for value ~${bet_rec:.0f} (67% pot). "
                    f"You have the best hand - extract value.",
                    f"BET เพื่อดึงค่า ~${bet_rec:.0f} (67% pot). "
                    f"คุณมีมือที่ดีที่สุด - ดึงค่าจากฝ่ายตรงข้าม"
                )
            elif texture == "B":
                bet_rec = pot * 0.5
                return (
                    f"BET for thin value ~${bet_rec:.0f} (50% pot). "
                    f"Or CHECK to control pot with medium-strength hand.",
                    f"BET ดึงค่าบาง ~${bet_rec:.0f} (50% pot). "
                    f"หรือ CHECK เพื่อคุมขนาด pot กับมือระดับกลาง"
                )
            else:  # C
                outs = analysis.get("outs", 0)
                if outs >= 8:
                    bet_rec = pot * 0.5
                    return (
                        f"BET as semi-bluff ~${bet_rec:.0f} (50% pot). "
                        f"{outs} outs gives you backup equity if called.",
                        f"BET เป็น semi-bluff ~${bet_rec:.0f} (50% pot). "
                        f"{outs} outs ให้ equity สำรองถ้าถูก call"
                    )
                else:
                    return (
                        "CHECK. No value to extract, not enough equity to semi-bluff.",
                        "CHECK. ไม่มีค่าจะดึง ไม่มี equity พอจะ semi-bluff"
                    )

    def _ev_summary(
        self,
        action: ActionType,
        amount: float,
        facing_bet: float,
        pot: float,
        equity: float,
        spr: float,
        texture: str,
    ) -> str:
        """Simple EV calculation summary."""
        if action == ActionType.CALL and facing_bet > 0:
            # EV of call = (equity * (pot + facing_bet)) - ((1 - equity/100) * facing_bet)
            ev = (equity / 100) * (pot + facing_bet) - ((1 - equity / 100) * facing_bet)
            return (
                f"EV(call) = ({equity:.0f}% x ${pot + facing_bet:.0f}) - "
                f"({100 - equity:.0f}% x ${facing_bet:.0f}) = ${ev:.1f}\n"
                f"{'Positive EV - call is profitable' if ev > 0 else 'Negative EV - call loses money long-term'}"
            )
        elif action in (ActionType.BET, ActionType.RAISE) and amount > 0:
            # Simplified: if villain folds X% of time
            fold_equity_breakeven = amount / (pot + amount) * 100
            return (
                f"Break-even fold equity needed: {fold_equity_breakeven:.1f}%\n"
                f"If villain folds more than {fold_equity_breakeven:.0f}% of the time, "
                f"this bet is immediately profitable regardless of equity."
            )
        elif action == ActionType.FOLD:
            if facing_bet > 0:
                pot_odds = facing_bet / (pot + facing_bet) * 100
                return (
                    f"Pot odds: {pot_odds:.1f}% (need {pot_odds:.1f}% equity to call)\n"
                    f"Your equity: ~{equity:.0f}%\n"
                    f"{'Fold saves money' if equity < pot_odds else 'Folding gives up +EV!'}"
                )
            return "Check is free - folding when not facing a bet is almost never correct."
        else:
            return f"SPR={spr:.1f}, Equity={equity:.0f}%, Pot=${pot:.0f}"


def format_analysis_display(analysis: dict, critique: dict) -> str:
    """Format the analysis and critique for display."""
    lines = []
    lines.append("=" * 65)
    lines.append("  ANALYSIS / วิเคราะห์")
    lines.append("=" * 65)

    # Current situation
    lines.append(f"\n  Pot: ${analysis['pot']:.0f}  |  "
                 f"Effective Stack: ${analysis['effective_stack']:.0f}  |  "
                 f"SPR: {analysis['spr']:.1f}")
    lines.append(f"  Street: {analysis['street']}  |  "
                 f"Texture Path: [{analysis['texture_path']}]")

    if "hand_ranking" in analysis:
        lines.append(f"\n  Your Hand: {analysis['hand_ranking']}")
        lines.append(f"  Classification: [{analysis['classification']}] "
                     f"{analysis['classification_reason_en']}")
        lines.append(f"  (TH): [{analysis['classification']}] "
                     f"{analysis['classification_reason_th']}")

    if "outs" in analysis:
        lines.append(f"\n  Outs: {analysis['outs']} "
                     f"(~{analysis['outs_equity']:.0f}% equity from outs)")

    if "equity_vs_villains" in analysis:
        lines.append("\n  Equity vs Villain Range(s):")
        for name, data in analysis["equity_vs_villains"].items():
            lines.append(f"    vs {name}: {data['equity']:.1f}%")
            lines.append(f"      Range: {data['range_desc']}")

    # SPR guidance
    if "spr_guidance" in critique:
        lines.append(f"\n  SPR Guide: {critique['spr_guidance']}")

    # Pot odds (if applicable)
    if "pot_odds" in critique:
        lines.append(f"\n  Pot Odds: {critique['pot_odds']:.1f}% "
                     f"(need {critique['equity_needed']:.1f}% equity to call)")

    if "bet_pot_pct" in critique:
        lines.append(f"  Bet Size: {critique['bet_pot_pct']:.0f}% of pot")
        lines.append(f"  Villain MDF: {critique['mdf_for_villain']:.0f}% "
                     f"(villain must defend this % of range)")

    # Feedback
    if critique["feedback"]:
        lines.append("\n  " + "-" * 40)
        lines.append("  FEEDBACK:")
        for fb in critique["feedback"]:
            lines.append(f"    > {fb}")

    # Corrections
    if critique["corrections"]:
        lines.append("\n  *** CORRECTIONS ***")
        for corr in critique["corrections"]:
            lines.append(f"    ! {corr}")

    # Reasoning warnings
    if critique.get("reasoning_warnings"):
        lines.append("\n  *** REASONING WARNINGS ***")
        for warn in critique["reasoning_warnings"]:
            lines.append(f"    !! {warn}")

    # EV analysis
    if critique["ev_analysis"]:
        lines.append(f"\n  EV: {critique['ev_analysis']}")

    # Recommendation
    lines.append("\n  " + "-" * 40)
    lines.append(f"  RECOMMENDATION: {critique['recommendation']}")
    lines.append(f"  (TH): {critique['recommendation_th']}")

    grade = "GOOD" if critique["is_correct"] else "NEEDS IMPROVEMENT"
    lines.append(f"\n  Overall: [{grade}]")
    lines.append("=" * 65)

    return "\n".join(lines)
