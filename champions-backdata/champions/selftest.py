"""엔진 회귀 테스트(M9) — 손으로 확인한 규칙이 코드 수정으로 깨지지 않았는지 본다.

python -m champions.selftest      (통과하면 'N개 모두 통과', 실패하면 항목과 값을 출력하고 종료 코드 1)

각 항목은 검토 과정에서 실제로 버그였거나 손계산으로 확인한 규칙이다.
"""
import sys

from .data import load
from .engine import (Build, Side, Field, act, damage, roll_hit, _chance, outcome, duel, value, value_vs,
                     duel_bayes, _setup_field)
from .game import solve, solve_bayes

D = load()
M = D.MOVES
F = Field()
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def mk(key, moves, ability=None, item=None, nature="serious", sp=(2, 32, 0, 0, 0, 32)):
    return Build(D, key, moves, item, ability, nature, sp)


# ── 명중·확률 누적 ──
s = Side(mk("hydreigon", ["draco-meteor"]))
seq = "".join("O" if roll_hit(s, "draco-meteor", 0.9) else "x" for _ in range(10))
check("명중 90%는 5번째에 처음 빗나감(부동소수점)", seq == "OOOOxOOOOO", seq)
s = Side(mk("garchomp", ["earthquake"]))
seq = "".join("O" if _chance(s, "t", 30) else "." for _ in range(10))
check("30% 부가효과는 2번째에 처음, 10회 중 3회", seq.count("O") == 3 and seq[1] == "O", seq)

# ── 빗나감 후처리 ──
a = Side(mk("hydreigon", ["draco-meteor"], "levitate", None, "modest", (2, 0, 0, 32, 0, 32)))
o = Side(mk("archaludon", ["flash-cannon"]))
a.miss["draco-meteor"] = 0.45
hp = o.hp
act(a, o, M["draco-meteor"], F, None)
check("빗나간 용성군은 피해·특공 하락 없음", o.hp == hp and a.boost[3] == 0, f"hp {hp}->{o.hp}, spa {a.boost[3]}")

# ── 특성 ──
sb = mk("gengar", ["shadow-ball"], None, None, "timid", (2, 0, 0, 32, 0, 32))
bp = mk("chesnaught", ["tackle"], "bulletproof")
check("방탄은 섀도볼 무효", damage(Side(sb), Side(bp), M["shadow-ball"], F) == 0)

# ── 연속기 × 멀티스케일: 첫 타만 반감 ──
m = Side(mk("meowscarada", ["triple-axel"], "protean", None, "jolly"))
dn_full = Side(mk("dragonite", ["extreme-speed"], "multiscale", None, "impish", (32, 0, 32, 0, 2, 0)))
dn_hurt = Side(mk("dragonite", ["extreme-speed"], "multiscale", None, "impish", (32, 0, 32, 0, 2, 0)))
dn_hurt.hp -= 1
d_full, d_hurt = damage(m, dn_full, M["triple-axel"], F), damage(m, dn_hurt, M["triple-axel"], F)
check("트리플악셀 × 멀티스케일은 첫 타(1/6)만 반감", abs(d_full / d_hurt - (1 - 0.5 / 6)) < 0.02, f"{d_full:.1f}/{d_hurt:.1f}")

# ── 급소 랭크 ──
mc = Side(mk("meowscarada", ["flower-trick"], "protean", None, "jolly"))
t0, tu, td = (Side(mk("hippowdon", ["earthquake"], "sand-stream", None, "impish", (32, 0, 32, 0, 2, 0))) for _ in range(3))
tu.boost[2], td.boost[2] = 2, -2
d0, du, dd = (damage(mc, t, M["flower-trick"], F) for t in (t0, tu, td))
check("확정 급소기는 방어 상승 무시, 하락은 반영", abs(d0 - du) < 1e-9 and dd > d0 * 1.5, f"{d0:.0f}/{du:.0f}/{dd:.0f}")

# ── 킹실드 ──
ks = Side(mk("aegislash", ["kings-shield"], "stance-change"))
g = Side(mk("garchomp", ["dragon-claw"], "rough-skin"))
act(ks, g, M["kings-shield"], F, None)
act(g, ks, M["dragon-claw"], F, ("move", M["kings-shield"]))
check("킹실드에 접촉하면 공격 −1", g.boost[1] == -1, str(g.boost[1]))

# ── 결과 판정 ──
check("60턴 미결(|v|<0.5)은 승이 아님", outcome(0.3) == 0.5 and outcome(0.6) == 1.0 and outcome(-0.5) == 0.0)

# ── 반대칭 ──
from .meta import opponents
bs, seen = [], set()
for e, b, w in opponents(D):
    if b.key not in seen:
        seen.add(b.key); bs.append(b)
bs = bs[:8]
worst = max(abs(value(a, b) + value(b, a)) for i, a in enumerate(bs) for b in bs[i + 1:])
check("1:1 값 반대칭 value(A,B) = −value(B,A)", worst < 1e-9, f"최대 {worst:.2e}")

# ── 게임 풀이 ──
import numpy as np
v, x, y = solve([[0, -1, 1], [1, 0, -1], [-1, 1, 0]])
check("가위바위보 값 0", abs(v) < 1e-9)
rng = np.random.default_rng(1)
Ms = [rng.normal(size=(5, 3)), rng.normal(size=(5, 4))]
import itertools
cols = list(itertools.product(range(3), range(4)))
R = np.array([[0.3 * Ms[0][i, c[0]] + 0.7 * Ms[1][i, c[1]] for c in cols] for i in range(5)])
check("베이지안 게임 이중 오라클 = 곱 게임", abs(solve_bayes(Ms, [0.3, 0.7])[0] - solve(R)[0]) < 1e-7)
A_, B_ = bs[0], bs[1]
check("같은 세트 두 유형의 베이지안 값 = 원래 값", abs(duel_bayes(A_, [B_, B_], [0.5, 0.5]) - duel(A_, B_)) < 1e-9)

# ── 출력 ──
bad = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(("✓ " if ok else "✗ ") + name + (f"  ({detail})" if detail and not ok else ""))
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
sys.exit(1 if bad else 0)
