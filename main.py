#!/usr/bin/env python3
"""
Poker Decision Training Simulator - Entry Point

Run with:
  python main.py
  python -m poker_simulator
"""

import sys
import os

# Add project root to path so imports work when running directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from poker_simulator.simulator import main

if __name__ == "__main__":
    main()
