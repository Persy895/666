# Poker Decision Training Simulator

ระบบฝึกตัดสินใจโป๊กเกอร์แบบ Human-in-the-Loop

## Overview

Interactive poker training tool that simulates NLH cash game hands and coaches you through every street using the **S/B/C Board Texture Classification Model**.

### S/B/C Model

| Code | Meaning | Thai | Description |
|------|---------|------|-------------|
| **S** | Nut | สัมพันธ์กับไพ่ที่ดีที่สุด | Top set, nut flush/straight, full house+ |
| **B** | Good | ดีแต่ไม่ใช่ nut | Overpair, TPTK, strong draws, 2nd nut |
| **C** | Unconnected | ไม่สัมพันธ์กับบอร์ด | Air, bottom pair, gutshot only |

**Street progression:**
- Flop: 3 categories → `S`, `B`, `C`
- Turn: 9 categories → `SS`, `SB`, `SC`, `BS`, `BB`, `BC`, `CS`, `CB`, `CC`
- River: 27 categories → `SSS` through `CCC`

## Features

- **Human-in-the-loop**: Stops at each street and asks for YOUR decision
- **Math-based critique**: Uses pot odds, outs (rule of 2/4), MDF, SPR, EV — not solver jargon
- **Realistic villains**: TAG, LAG, NIT, Fish, Calling Station, Maniac with real stat profiles
- **Bilingual**: Analysis in both English and Thai
- **No "betting for information"**: Corrects flawed reasoning patterns
- **Equity calculator**: Monte Carlo equity vs estimated villain ranges

## Game Setup

- Stakes: $1/$3 NLH Cash
- Effective stack: $500 (default)
- Max players: 9
- Hero VPIP range: ~15%

## Usage

```bash
python -m poker_simulator
```

### In-game commands
- `fold` or `f` — Fold
- `check` or `x` — Check
- `call` or `c` — Call
- `bet 20` or `b 20` — Bet $20
- `raise 45` or `r 45` — Raise to $45
- `allin` or `shove` — All-in

## Running Tests

```bash
python -m poker_simulator.tests
```

## Architecture

```
poker_simulator/
├── __init__.py       # Package info
├── __main__.py       # Entry point
├── models.py         # Card, HandState, VillainProfile, enums
├── evaluator.py      # Hand evaluation, equity (Monte Carlo), outs
├── classifier.py     # S/B/C board texture classification
├── opponents.py      # Villain profiles, ranges, action generation
├── analysis.py       # Decision critique engine (EV, pot odds, MDF, SPR)
├── scenarios.py      # Hand scenario generator, display formatting
├── simulator.py      # Interactive CLI (human-in-the-loop)
└── tests.py          # Unit tests
```

## Decision Analysis

At each street, the simulator provides:

1. **Pot size, Effective stack, SPR**
2. **S/B/C classification** with reasoning
3. **Pot odds** (when facing a bet)
4. **Hand equity** vs villain's estimated range
5. **Outs** and equity from draws (rule of 2 and 4)
6. **MDF** (Minimum Defense Frequency)
7. **EV calculation** of your chosen action
8. **Recommendation** with reasoning (EN + TH)
9. **Corrections** if your reasoning is flawed
