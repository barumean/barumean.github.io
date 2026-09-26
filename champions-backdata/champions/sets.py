"""세트(기술 4개 · 도구 · 성격/스탯포인트) 추천.

점수 = 메타 상대(조우 가중)와 1:1 을 끝까지 돌린 값의 가중 평균.
탐색 = 실채용 최다 세트에서 출발해 "한 칸 바꾸기"를 개선이 없을 때까지 반복(국소 탐색),
       그다음 도구 → 성격·스탯포인트 → 기술 한 번 더.

규칙
- 후보 기술: op.gg 채용 3% 이상 + 배울 수 있는 공격기 중 타입별 최강 1개(주 공격 분류 기준)
- 채용 70% 이상 기술은 고정(--free 로 해제). 모델이 값을 못 매기는 기술(스텔스록·방어·유턴의 교체 이득 등)을
  지키기 위한 장치다.
- 쌓기·회복·상태이상 기술은 op.gg 채용 10% 이상인 것만 후보로 넣는다.
"""
from .engine import Build, classify, duel, value, value_vs
from .meta import stones_of

LOCK_PCT = 70.0
UTIL_MIN_PCT = 10.0
GENERIC_ITEMS = ["life-orb", "choice-scarf", "focus-sash", "leftovers", "sitrus-berry", "expert-belt", "lum-berry", "rocky-helmet"]


# ── 공격 유형 (물리형·특수형·쌍두형) ─────────────────────────────
# 세트는 유형을 먼저 정하고, 성격·스탯포인트·공격기·쌓기기가 그 유형과 맞아야만 후보가 된다.
ARCH_KO = {"physical": "물리형", "special": "특수형", "mixed": "쌍두형"}
_NI = {"atk": 1, "def": 2, "spa": 3, "spd": 4, "spe": 5}


def _setup_stats(mv):
    k = mv["key"]
    if k in ("belly-drum", "curse"):
        return {1}
    from .engine import _SK
    return {_SK[c["stat"]] for c in mv["stat_changes"] if c["change"] > 0 and c["stat"] in _SK}


def move_fits(D, m, arch):
    """기술이 유형과 맞는가. 공격기는 분류로, 쌓기기는 올리는 공격 스탯으로 판정."""
    mv = D.MOVES[m]
    k = classify(mv)
    if k == "attack":
        return arch == "mixed" or mv["cat"] == arch
    if k == "setup":
        up = _setup_stats(mv) & {1, 3}
        if not up or arch == "mixed":
            return True                               # 방어·스피드만 올리는 쌓기는 어느 유형이든
        return (1 in up) if arch == "physical" else (3 in up)
    return True                                      # 회복·상태이상·흑안개


def spread_fits(nature, sp, arch):
    from .scrape import NATURES
    n = NATURES.get(nature)
    inc, dec = (_NI[n[0]], _NI[n[1]]) if n else (None, None)
    if arch == "physical":
        return dec != 1 and inc != 3 and sp[3] <= 4
    if arch == "special":
        return dec != 3 and inc != 1 and sp[1] <= 4
    return dec not in (1, 3) and sp[1] >= 8 and sp[3] >= 8


def moves_fit(D, moves, arch):
    if not all(move_fits(D, m, arch) for m in moves):
        return False
    if arch == "mixed":
        cats = {D.MOVES[m]["cat"] for m in moves if classify(D.MOVES[m]) == "attack"}
        return {"physical", "special"} <= cats
    return any(classify(D.MOVES[m]) == "attack" for m in moves)


# ── 역할 (공격형·내구형) ─────────────────────────────────────────
# 공격 분류(물리/특수/쌍두)와 별개로, 스탯포인트·성격이 '때리는 쪽'인지 '버티는 쪽'인지 정한다.
ROLE_KO = {"attacker": "공격형", "tank": "내구형"}
ATTACKER_ITEMS = {"life-orb", "choice-scarf", "focus-sash", "expert-belt", "muscle-band", "wise-glasses"}
TANK_ITEMS = {"rocky-helmet"}                       # 울퉁불퉁멧: 물리 방어 투자가 있는 내구형만


def role_of(nature, sp, arch):
    """(성격, 스탯포인트) 가 이 공격 분류에서 공격형/내구형 중 무엇인가. 어느 쪽도 아니면 None."""
    from .scrape import NATURES
    n = NATURES.get(nature)
    inc, dec = (_NI[n[0]], _NI[n[1]]) if n else (None, None)
    atk_sp = {"physical": sp[1], "special": sp[3], "mixed": min(sp[1], sp[3])}[arch]
    atk_i = {"physical": {1}, "special": {3}, "mixed": {1, 3}}[arch]
    if (atk_sp >= 16 or (arch == "mixed" and atk_sp >= 8)) and (inc is None or inc in atk_i | {5}):
        return "attacker"
    if arch != "mixed" and atk_sp < 16 and sp[0] + max(sp[2], sp[4]) >= 40 and inc in (2, 4) and dec not in (2, 4):
        return "tank"
    return None


def item_moves_ok(D, item, moves):
    """구애스카프는 기술이 하나로 고정된다 → 쌓기·회복·변화기와 같이 쓰지 않는다."""
    if item == "choice-scarf":
        return all(classify(D.MOVES[m]) == "attack" for m in moves)
    return True


def item_fits(item, role, nature, sp):
    from .engine import TYPE_ITEM
    from .scrape import NATURES
    if item in ATTACKER_ITEMS or item in TYPE_ITEM:
        return role == "attacker"
    if item in TANK_ITEMS:
        n = NATURES.get(nature)
        return role == "tank" and (sp[2] >= 16 or (n is not None and n[0] == "def"))
    return True


def type_label(key):
    """'physical:tank' → '물리 내구형'"""
    a, _, r = key.partition(":")
    if a == "imposter":
        return "변신형"
    return f"{ARCH_KO.get(a, a)[:2]} {ROLE_KO.get(r, '(역할 자유)')}"


def arch_of(b):
    """완성된 세트의 유형 판정(표시용): '물리 공격형' 등. 투자·기술·도구가 어긋나면 '비정형(…)'."""
    D = b.D
    if b.ability == "imposter":
        return "변신형"
    for a in ("physical", "special", "mixed"):
        if spread_fits(b.nature, b.sp, a) and moves_fit(D, b.moves, a):
            r = role_of(b.nature, b.sp, a)
            if r and (b.mega or item_fits(b.item, r, b.nature, b.sp)) and item_moves_ok(D, b.item, b.moves):
                return f"{ARCH_KO[a][:2]} {ROLE_KO[r]}"
            return f"비정형({ARCH_KO[a][:2]})"
    return "비정형(투자 불일치)"


def archetypes_to_try(D, key, form=None):
    """종족값이나 op.gg 채용으로 보아 말이 되는 유형들."""
    st = D.DEX[form or key]["stats"]
    hi = max(st[1], st[3])
    u = D.USAGE.get(key) or {"moves": []}
    use = {"physical": 0.0, "special": 0.0}
    for m, p in u["moves"]:
        if m in D.MOVES and classify(D.MOVES[m]) == "attack":
            use[D.MOVES[m]["cat"]] = use.get(D.MOVES[m]["cat"], 0) + p
    ok = {"physical": st[1] >= 0.8 * hi or use["physical"] >= 25,
          "special": st[3] >= 0.8 * hi or use["special"] >= 25}
    ok["physical" if st[1] >= st[3] else "special"] = True     # 높은 쪽은 항상
    out = [a for a in ("physical", "special") if ok[a]]
    if ok["physical"] and ok["special"]:
        out.append("mixed")
    return out


def main_category(D, key, form=None):
    s = D.DEX[form or key]["stats"]
    if form and form != key:                  # 메가는 기본형과 분류가 다를 수 있다(메가한카리아스Z = 특수)
        return "physical" if s[1] >= s[3] else "special"
    u = D.USAGE.get(key)
    if u:
        ph = sum(p for m, p in u["moves"] if m in D.MOVES and D.MOVES[m]["cat"] == "physical")
        sp = sum(p for m, p in u["moves"] if m in D.MOVES and D.MOVES[m]["cat"] == "special")
        if abs(ph - sp) > 30:
            return "physical" if ph > sp else "special"
    return "physical" if s[1] >= s[3] else "special"


def candidate_moves(D, key, form=None):
    u = D.USAGE.get(key) or {"moves": []}
    pct = {m: p for m, p in u["moves"]}
    cands = []
    for m, p in u["moves"]:
        if m not in D.MOVES:
            continue
        k = classify(D.MOVES[m])
        if k == "attack" and p >= 3.0 or k in ("setup", "heal", "status", "phaze", "protect", "field", "encore") and p >= UTIL_MIN_PCT:
            cands.append(m)
    cats = {"physical", "special"}                      # 유형별 거르기는 optimize 에서
    learn = D.DEX[key]["learnset"] | D.DEX[form or key]["learnset"]
    best = {}
    for m in learn:
        mv = D.MOVES.get(m)
        if not mv or not mv["available"] or classify(mv) != "attack" or mv["cat"] not in cats:
            continue
        if m in ("fake-out", "first-impression") or (mv["priority"] or 0) < 0:
            continue
        pw = (mv["power"] or 0) * (mv["acc"] or 100) / 100
        lo, hi = mv["meta"].get("minHits"), mv["meta"].get("maxHits")
        if lo and hi:
            pw *= hi if lo == hi else 3.1
        if (mv["priority"] or 0) > 0:
            pw *= 1.5  # 선공기는 위력이 낮아도 후보로 남긴다
        t = (mv["type"], mv["cat"])
        if pw > best.get(t, (None, 0))[1]:
            best[t] = (m, pw)
    for m, _ in best.values():
        if m not in cands:
            cands.append(m)
    locked = [m for m in cands if pct.get(m, 0) >= LOCK_PCT]
    return cands, locked


def candidate_items(D, key):
    u = D.USAGE.get(key) or {"items": []}
    items = [i for i, p in u["items"] if p >= 3.0 and i not in D.STONE and i in D.ITEMS]
    for i in GENERIC_ITEMS:
        if i not in items and i in D.ITEMS:
            items.append(i)
    return items


CANON_SPREADS = {
    ("physical", "attacker"): [("adamant", (2, 32, 0, 0, 0, 32)), ("jolly", (2, 32, 0, 0, 0, 32)), ("adamant", (32, 32, 2, 0, 0, 0))],
    ("special", "attacker"): [("modest", (2, 0, 0, 32, 0, 32)), ("timid", (2, 0, 0, 32, 0, 32)), ("modest", (32, 0, 2, 32, 0, 0))],
    ("mixed", "attacker"): [("naive", (0, 17, 0, 17, 0, 32)), ("hasty", (0, 17, 0, 17, 0, 32)),
                            ("lonely", (2, 32, 0, 32, 0, 0)), ("mild", (2, 32, 0, 32, 0, 0))],
    ("physical", "tank"): [("impish", (32, 0, 32, 0, 2, 0)), ("careful", (32, 0, 2, 0, 32, 0))],
    ("special", "tank"): [("bold", (32, 0, 32, 0, 2, 0)), ("calm", (32, 0, 2, 0, 32, 0))],
}
_SPK = ("hp", "attack", "defense", "spAtk", "spDef", "speed")


def replica_spreads(D, key):
    """레플리카 팀에 실제로 있는 (성격, 스탯포인트) 짝 — 함께 쓰인 조합이라 일관성이 있다."""
    from collections import Counter
    c = Counter()
    for t in D.TEAMS:
        for s in t["slots"]:
            if s["pokemon"] in D.DEX and D.base_of(s["pokemon"]) == key and s.get("nature") and s.get("customStats"):
                sp = tuple(s["customStats"][k] for k in _SPK)
                if sum(sp) >= 60:
                    c[(s["nature"], sp)] += 1
    return [x for x, _ in c.most_common()]


def roles_to_try(D, key, arch, cands):
    """공격형은 항상. 내구형은 회복기가 후보에 있거나 실제 내구형 배분이 관측될 때만(쌍두형은 공격형만)."""
    if arch == "mixed":
        return ["attacker"]
    heal = any(classify(D.MOVES[m]) == "heal" for m in cands)
    u = D.USAGE.get(key) or {"training": [], "natures": []}
    seen = any(role_of(n, tuple(s), arch) == "tank" for n in [x for x, _ in u["natures"][:5]]
               for s, p in u["training"][:6] if p >= 3) or any(role_of(n, s, arch) == "tank" for n, s in replica_spreads(D, key))
    return ["attacker", "tank"] if (heal or seen) else ["attacker"]


def candidate_spreads(D, key, arch, role="attacker"):
    """[(nature, sp)] — 이 (공격 분류, 역할)에 맞는 것만.
    ① 레플리카 팀의 실제 짝  ② op.gg 성격 × op.gg 배분 조합 중 규칙을 통과하는 것  ③ 정석 배분."""
    def ok(n, s):
        return spread_fits(n, s, arch) and role_of(n, s, arch) == role
    u = D.USAGE.get(key) or {"natures": [], "training": []}
    out = [x for x in replica_spreads(D, key) if ok(*x)][:3]
    nats = [n for n, p in u["natures"][:5]]
    sps = [tuple(s) for s, p in u["training"][:6]]
    out += [(n, s) for n in nats for s in sps if ok(n, s)][:3]
    out += CANON_SPREADS[(arch, role)]
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


class Evaluator:
    """상대 목록에 대한 세트 점수. fast=정면 1:1 만(기술 탐색용), full=교체 등장까지 섞은 value()."""

    def __init__(self, opps, top=80):
        opps = sorted(opps, key=lambda x: -x[2])[:top]
        tot = sum(w for _, _, w in opps)
        self.opps = [(e, b, w / tot) for e, b, w in opps]
        self.cache = {}

    def score(self, b, full=False, branch=False):
        sig = (full, branch, b.key, b.item, b.entry_ability, b.nature, b.sp, tuple(sorted(b.moves)))
        v = self.cache.get(sig)
        if v is None:
            f = value if full else duel
            # 세트 탐색은 평가가 수십만 번이라 결정적 모드(branch=False). 최종 후보 비교와 상성 행렬·선출은 분기 모드.
            v = sum(w * value_vs(b, ob, branch=branch, f=f) for e, ob, w in self.opps if ob.key != b.key)
            self.cache[sig] = v
        return v

    def detail(self, b):
        return [(e, w, value(b, ob)) for e, ob, w in self.opps if ob.key != b.key]


def _mk(D, key, moves, item, ability, nature, sp):
    return Build(D, key, list(moves), item, ability, nature, sp)


def optimize(D, key, ev, item=None, mega=None, ability=None, nature=None, sp=None, fixed_moves=(), free=False,
             fix_item=False, fix_spread=False, log=None, arch=None):
    """key 한 마리의 최적 세트. mega=True 면 스톤 고정, False 면 스톤 제외, None 이면 둘 다 보고 좋은 쪽.
    arch(물리형 physical / 특수형 special / 쌍두형 mixed) 를 주면 그 유형만, 없으면 말이 되는 유형을 전부 보고 최고.
    결과의 arch_scores 에 유형별 최고 점수가 들어 있다."""
    u0 = D.USAGE.get(key) or {}
    if (ability or (u0.get("abilities") or [[None]])[0][0]) == "imposter":
        return _optimize_imposter(D, key, ev, item, fix_item)
    if mega is None and stones_of(D, key) and not item:
        a = optimize(D, key, ev, mega=True, ability=ability, nature=nature, sp=sp, fixed_moves=fixed_moves, free=free, log=log, arch=arch)
        b = optimize(D, key, ev, mega=False, ability=ability, nature=nature, sp=sp, fixed_moves=fixed_moves, free=free, log=log, arch=arch)
        return a if a["score"] >= b["score"] else b
    stones = stones_of(D, key)
    if mega and stones:
        item, fix_item = item or stones[0], True
    form = D.STONE.get(item) if item in D.STONE else None
    if arch:
        archs = [arch]
    elif nature and sp:                                  # 입력한 성격·스탯포인트가 유형을 정한다
        archs = [a for a in ("physical", "special", "mixed") if spread_fits(nature, sp, a)] or ["mixed"]
    else:
        archs = archetypes_to_try(D, key, form)
    res = {}
    cands0 = candidate_moves(D, key, form)[0]
    force_role = None
    if arch and ":" in arch:                             # 'physical:tank' 처럼 역할까지 지정
        a0, force_role = arch.split(":")
        archs = [a0]
    for a in archs:
        if nature and sp:                                # 입력한 배분이 역할을 정한다(규칙 밖이면 역할 제약 없음)
            roles = [role_of(nature, sp, a)]
        elif force_role:
            roles = [force_role]
        else:
            roles = roles_to_try(D, key, a, cands0)
        for ro in roles:
            r = _optimize_arch(D, key, ev, a, item, form, ability, nature, sp, fixed_moves, free, fix_item, fix_spread, role=ro)
            if r:
                res[f"{a}:{ro}"] = r
    if not res:                                          # 고정 기술·도구가 어느 유형과도 안 맞으면 제약 없이
        res["mixed:None"] = _optimize_arch(D, key, ev, "mixed", item, form, ability, nature, sp, fixed_moves, free,
                                           fix_item, fix_spread, force=True, role=None)
    # 유형·역할별 최종 후보는 분기 모드(명중·문턱 갈래)로 다시 채점해서 고른다 — 탐색의 결정적 모드와
    # 상성 행렬의 분기 모드가 어긋나 최종 선택이 옛 계산에 기대던 문제(ASTRA 3)
    for r in res.values():
        r["score_det"] = r["score"]
        r["score"] = ev.score(r["build"], True, branch=True)
    best = max(res.values(), key=lambda r: r["score"])
    best["arch_scores"] = {a: r["score"] for a, r in res.items()}
    return best


def _optimize_imposter(D, key, ev, item=None, fix_item=False):
    """괴짜(메타몽): 상대를 복사하므로 기술·공격 투자는 의미가 없다. HP 만 투자하고 도구만 고른다."""
    u = D.USAGE.get(key) or {"items": [], "moves": []}
    items = [item] if (item and fix_item) else list(dict.fromkeys(
        ([item] if item else []) + [i for i, p in u["items"] if p >= 3.0 and i in D.ITEMS]
        + ["choice-scarf", "focus-sash", "sitrus-berry", "leftovers"]))
    sp = (32, 0, 17, 0, 17, 0)
    scored = []
    for it in items:
        b = _mk(D, key, ["transform"], it, "imposter", "bold", sp)
        scored.append((it, ev.score(b, True), b))
    scored.sort(key=lambda x: -x[1])
    it, v, b = scored[0]
    return {"build": b, "arch": "imposter:None", "score": v, "moves": [], "real_top4": ["transform"],
            "real_score": v, "cands": ["transform"], "items": [(i, s) for i, s, _ in scored],
            "arch_scores": {"imposter:None": v}}


def _optimize_arch(D, key, ev, arch, item, form, ability, nature, sp, fixed_moves, free, fix_item, fix_spread,
                   force=False, role="attacker"):
    u = D.USAGE.get(key) or {"moves": [], "abilities": []}
    ability = ability or (u["abilities"][0][0] if u.get("abilities") else D.DEX[key]["abilities"][0])
    spreads = candidate_spreads(D, key, arch, role) if role else CANON_SPREADS[(arch, "attacker")]
    if nature and sp:
        spreads, fix_spread = [(nature, tuple(sp))], True
    mega_item = item in D.STONE

    def it_ok(it, n, s):
        return role is None or mega_item or item_fits(it, role, n, s)

    if item and fix_item and not force and not any(it_ok(item, n, s) for n, s in spreads):
        return None                                      # 고정 도구(예: 울퉁불퉁멧)가 이 역할과 안 맞음
    nat, spv = spreads[0]
    cands, locked = candidate_moves(D, key, form)
    fixed = list(dict.fromkeys(list(fixed_moves) + ([] if free else locked)))[:4]
    if not force and not all(move_fits(D, m, arch) for m in fixed):
        return None                                      # 고정 기술(채용 70%↑·--keep)이 이 유형과 충돌
    for m in fixed:
        if m not in cands:
            cands.append(m)
    cands = [m for m in cands if m in fixed or move_fits(D, m, arch) or force]
    if arch != "mixed" and not any(classify(D.MOVES[m]) == "attack" for m in cands):
        return None
    items = [item] if (item and fix_item) else ([item] + candidate_items(D, key) if item else candidate_items(D, key))
    items = list(dict.fromkeys(items))
    if item and fix_item:
        spreads = [x for x in spreads if it_ok(item, *x)] or spreads
        nat, spv = spreads[0]
    cur_item = next((i for i in items if it_ok(i, nat, spv) and i != "choice-scarf"), items[0])  # 스카프는 기술을 정한 뒤 도구 단계에서

    def ok(mv):
        return force or (moves_fit(D, mv, arch) and item_moves_ok(D, cur_item, mv))

    # 출발점: 고정 + 채용 순. 쌍두형은 물리·특수 최고 채용기를 하나씩 먼저 넣는다.
    pct = {m: p for m, p in u["moves"]}
    order = sorted(cands, key=lambda m: -pct.get(m, 0))
    seed = list(fixed)
    if arch == "mixed":
        for c in ("physical", "special"):
            if not any(D.MOVES[m]["cat"] == c and classify(D.MOVES[m]) == "attack" for m in seed):
                pick = next((m for m in order if classify(D.MOVES[m]) == "attack" and D.MOVES[m]["cat"] == c), None)
                if pick:
                    seed.append(pick)
    moves = (seed + [m for m in order if m not in seed])[:4]
    if not any(classify(D.MOVES[m]) == "attack" for m in moves):
        atk = [m for m in cands if classify(D.MOVES[m]) == "attack"]
        moves = (moves[:3] + atk[:1]) if atk else moves
    if not ok(moves):
        return None

    def sc(mv, it, n, s, full=False):
        return ev.score(_mk(D, key, mv, it, ability, n, s), full)

    best = sc(moves, cur_item, nat, spv)

    def move_pass(moves, best, full=False):
        improved = True
        while improved:
            improved = False
            for i in range(len(moves)):
                if moves[i] in fixed:
                    continue
                for c in cands:
                    if c in moves:
                        continue
                    trial = moves[:i] + [c] + moves[i + 1:]
                    if not ok(trial):
                        continue
                    v = sc(trial, cur_item, nat, spv, full)
                    if v > best + 1e-9:
                        moves, best, improved = trial, v, True
            if len(moves) < 4:
                for c in cands:
                    if c not in moves and ok(moves + [c]):
                        v = sc(moves + [c], cur_item, nat, spv, full)
                        if v > best:
                            moves, best, improved = moves + [c], v, True
                            break
        return moves, best

    moves, best = move_pass(moves, best)
    # 도구·성격은 교체 등장까지 섞은 값으로 고른다(기합의띠 과대평가 방지)
    fb = sc(moves, cur_item, nat, spv, True)
    item_scores = []
    if not fix_item:
        for it in items:
            if not it_ok(it, nat, spv) or not item_moves_ok(D, it, moves):   # 역할·기술과 안 맞는 도구
                continue
            v = sc(moves, it, nat, spv, True)
            item_scores.append((it, v))
            if v > fb + 1e-9:
                cur_item, fb = it, v
    if not fix_spread:
        for n, s in spreads:                                # 전부 이 유형·역할에 맞는 성격·스탯포인트
            if not it_ok(cur_item, n, s):
                continue
            v = sc(moves, cur_item, n, s, True)
            if v > fb + 1e-9:
                nat, spv, fb = n, s, v
    best = sc(moves, cur_item, nat, spv)
    moves, best = move_pass(moves, best)
    # 마무리: 도구·성격과 같은 목표(교체 등장 포함 value)로 기술을 한 번 더 다듬는다 — 목표 불일치 제거
    moves, best = move_pass(moves, sc(moves, cur_item, nat, spv, True), full=True)
    b = _mk(D, key, moves, cur_item, ability, nat, spv)
    # 칸별 기여: 그 기술을 빼고 최선의 대체로 바꿨을 때 점수 하락
    contrib = []
    for i, m in enumerate(moves):
        alt_v, alt_m = -9, None
        for c in cands:
            trial = moves[:i] + [c] + moves[i + 1:]
            if c in moves or not ok(trial):
                continue
            v = sc(trial, cur_item, nat, spv, True)
            if v > alt_v:
                alt_v, alt_m = v, c
        contrib.append({"move": m, "drop": best - alt_v if alt_m else None, "alt": alt_m,
                        "pct": pct.get(m, 0.0), "fixed": m in fixed})
    real = [m for m, p in u["moves"] if m in D.MOVES][:4]
    real_b = _mk(D, key, real, cur_item, ability, nat, spv) if real else None
    return {"build": b, "arch": f"{arch}:{role}", "score": ev.score(b, True), "moves": contrib, "real_top4": real,
            "real_score": ev.score(real_b, True) if real_b else None, "cands": cands,
            "items": sorted(item_scores, key=lambda x: -x[1])}
