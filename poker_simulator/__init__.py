"""
Poker Decision Training Simulator
==================================
ระบบจำลองการฝึกตัดสินใจโป๊กเกอร์แบบ Human-in-the-Loop

NLH Cash Game Only - No Tournament ICM

Board Texture Classification (S/B/C Model):
  Flop:  S / B / C                    (3 categories)
  Turn:  SS / SB / SC / ... / CC      (9 categories)
  River: SSS / SSB / SSC / ... / CCC  (27 categories)

S = Nut: ฟลอบสัมพันธ์กับไพ่ที่เรามีที่ดีที่สุดที่เป็นไปได้
B = Good: ฟลอบที่ดีแต่ผู้เล่นอื่นยังมีโอกาสได้ดีกว่า (2nd/3rd nut)
C = Unconnected: ฟลอบไม่สัมพันธ์กับไพ่ที่เรามี
"""

__version__ = "1.0.0"
