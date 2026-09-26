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

# ── 메타몽 ──
from .engine import plans_vs, _side, speed
dit = Build(D, "ditto", ["transform"], "choice-scarf", "imposter", "relaxed", (32, 0, 17, 0, 17, 0))
dn = mk("dragonite", ["dragon-dance", "extreme-speed", "earthquake", "outrage"], "multiscale", None, "jolly")
check("메타몽은 변신한 기술로 계획(용의춤 쌓기 포함)", ("setup", "dragon-dance", 1) in plans_vs(dit, dn))
check("스카프 메타몽은 변신 상대보다 빠르다", speed(_side(dit, dn, 1.0), F) > speed(Side(dn), F))

# ── 추가 특성 ──
pr = mk("primarina", ["hydro-pump"], "torrent", None, "modest", (2, 0, 0, 32, 0, 32))
tg = mk("garchomp", ["earthquake"], "rough-skin")
p_full, p_low = Side(pr), Side(pr)
p_low.hp = p_low.maxhp / 3
check("급류: HP 1/3 이하 물 기술 ×1.5",
      abs(damage(p_low, Side(tg), M["hydro-pump"], F) / damage(p_full, Side(tg), M["hydro-pump"], F) - 1.5) < 0.05)
st_ = Side(mk("archaludon", ["body-press"], "stamina", None, "impish", (32, 0, 32, 0, 2, 0)))
act(Side(tg), st_, M["earthquake"], F, None)
check("지구력: 맞으면 방어 +1", st_.boost[2] == 1, str(st_.boost[2]))
sv = Side(mk("serperior", ["leaf-storm"], "contrary", None, "timid", (2, 0, 0, 32, 0, 32)))
act(sv, Side(tg), M["leaf-storm"], F, None)
check("심술꾸러기: 리프스톰 뒤 특공 +2", sv.boost[3] == 2, str(sv.boost[3]))
gv = Side(mk("gardevoir", ["moonblast"], "trace", None, "timid", (2, 0, 0, 32, 0, 32)))
gy = Side(mk("gyarados", ["waterfall"], "intimidate", None, "adamant"))
_setup_field(gv, gy, Field())
check("트레이스로 복사한 위협도 발동", gv.ability == "intimidate" and gy.boost[1] == -1 and gv.boost[1] == -1,
      f"{gv.ability} {gy.boost[1]} {gv.boost[1]}")

# ── 챔피언스 룰(GAME_RULES_REVIEW) ──
from .engine import PAR_SKIP, simulate, crit_rate
check("마비 행동 불가 12.5%", PAR_SKIP == 0.125)
bl1 = mk("hippowdon", ["slack-off"], "sand-stream", None, "bold", (32, 0, 32, 0, 2, 0))
check("끝나지 않은 대결은 무승부 0", simulate(bl1, bl1, max_turns=3) == 0.0)
check("급소율 단계: 기본 1/24, 스톤에지 1/8, +초점렌즈 1/2",
      abs(crit_rate(Side(tg), M["earthquake"]) - 1 / 24) < 1e-12
      and abs(crit_rate(Side(tg), M["stone-edge"]) - 1 / 8) < 1e-12
      and abs(crit_rate(Side(mk("garchomp", ["stone-edge"], item="scope-lens")), M["stone-edge"]) - 1 / 2) < 1e-12)
kg = Side(mk("kangaskhan", ["double-edge"], None, "kangaskhanite", "adamant"))
sash = Side(mk("meowscarada", ["flower-trick"], "protean", "focus-sash", "jolly"))
act(kg, sash, M["double-edge"], F, None)
check("부자유친: 두 번째 타격이 기합의띠를 뚫는다", sash.hp <= 0, f"{sash.hp:.1f}")
check("문포스 특공 하락은 설명문 10%", D.MOVES["moonblast"]["meta"].get("statChance") == 10)
check("외형 변형(찌르호크 암컷)은 기본 종으로", D.mon("staraptor-female") == "staraptor")

# ── 역할 분류 ──
from .meta import classify_build, modal_build
slot = lambda n, spv, mv: {"nature": n, "customStats": dict(zip(("hp", "attack", "defense", "spAtk", "spDef", "speed"), spv)),
                            "moves": mv}
check("역할 분류: 물리 공격·특수 공격·물리막이",
      classify_build(D, slot("jolly", (2, 32, 0, 0, 0, 32), ["dragon-darts", "u-turn", "phantom-force", "sucker-punch"])) == "physical:attacker"
      and classify_build(D, slot("timid", (2, 0, 0, 32, 0, 32), ["draco-meteor", "shadow-ball", "flamethrower", "u-turn"])) == "special:attacker"
      and classify_build(D, slot("impish", (32, 0, 32, 0, 2, 0), ["earthquake", "slack-off", "stealth-rock", "yawn"])) == "phys-wall")
hp_ = modal_build(D, "hippowdon")
check("역할이 갈리는 종은 역할별 세트를 확률과 함께 가진다",
      hp_.roles is not None and len(hp_.roles) >= 2 and abs(sum(p for _, p in hp_.variants) - 1) < 1e-9)

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
