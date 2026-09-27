"""1:1 한 판을 턴별로 재생한다 (엔진 점검용).

python -m champions.trace 킬라플로르 더시마사리
python -m champions.trace 메가팬텀 대검귀 --plan-a status:will-o-wisp
"""
import argparse
import sys

from .data import load
from .engine import duel, plans_vs, simulate
from .meta import opponents


def meta_build(D, name):
    k = D.mon(name)
    mega = D.DEX[k]["base_key"] is not None
    base = D.base_of(k)
    for e, b, w in opponents(D):
        if b.key == base and b.mega == mega:
            return b
    raise SystemExit(f"메타 대표 세트에 없음: {name}")


def show(D, A, B):
    print(f"A: {A}  실능 {A.stats}  특성 {A.ability}")
    print(f"B: {B}  실능 {B.stats}  특성 {B.ability}")
    print(f"duel(A,B) = {duel(A, B):+.3f}\n")
    pa, pb = plans_vs(A, B), plans_vs(B, A)
    print("계획 행렬 (행 A, 열 B):")
    for x in pa:
        print(f"  {str(x[0]) + ':' + str(x[1]):<28}", " ".join(f"{simulate(A, B, x, y):+.2f}" for y in pb))
    print("  열:", [f"{y[0]}:{y[1]}" for y in pb])
    for x in pa:
        for y in pb:
            t = []
            v = simulate(A, B, x, y, trace=t)
            print(f"\n── A {x[0]}:{x[1]} / B {y[0]}:{y[1]} → {v:+.3f}")
            print("\n".join(t))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    a = ap.parse_args()
    D = load()
    show(D, meta_build(D, a.a), meta_build(D, a.b))


if __name__ == "__main__":
    main()
