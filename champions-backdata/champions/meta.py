"""상대 메타 모델.

- modal_build   op.gg 싱글 통계에서 가장 많이 쓰는 특성·도구·성격·스탯포인트·기술 4개로 만든 대표 세트
- opponents     실제로 만날 상대 목록(개체 = 포켓몬 × 메가 여부)과 조우 가중치
                가중치 = 레플리카 싱글 팀에서의 등장 빈도 + 티어 순위 사전값
- mega_prob     그 포켓몬이 스톤을 들고 나올 확률(op.gg 도구 채용률)
"""
import math
from collections import Counter

from .engine import Build, classify, usable

MIN_MOVE_PCT = 3.0


def stones_of(D, key):
    """그 포켓몬의 메가 스톤들, 채용률 높은 순."""
    megas = D.MEGAS.get(key, [])
    st = [(D.DEX[m]["item"], D.usage_pct(key, "items", D.DEX[m]["item"])) for m in megas]
    return [s for s, _ in sorted(st, key=lambda x: -x[1])]


def mega_prob(D, key):
    return sum(D.usage_pct(key, "items", s) for s in stones_of(D, key)) / 100.0


def top_moves(D, key, n=4):
    u = D.USAGE.get(key)
    if not u:
        return []
    out = []
    for m, p in u["moves"]:
        if m in D.MOVES and p >= MIN_MOVE_PCT and classify(D.MOVES[m]) != "none":
            out.append(m)
    # 값이 없는 기술(방어·스텔스록 등)을 빼고 남은 상위 4개. 공격기가 하나도 없으면 도감에서 보충.
    return out[:n]


_SPK = ("hp", "attack", "defense", "spAtk", "spDef", "speed")


def _mode(xs):
    return Counter(xs).most_common(1)[0][0] if xs else None


def modal_build(D, key, mega=False, slots=(), stone=None):
    """대표 세트 + (값을 못 매기는 기술이 있으면) 그 칸을 공격기로 바꾼 변형을 .alt 로 붙인다."""
    b = _modal_build(D, key, mega, slots, stone)
    if b is not None:
        b.alt = make_alt(D, b)
    return b


def _modal_build(D, key, mega=False, slots=(), stone=None):
    """대표 세트. 레플리카 팀에 그 개체(메가 여부까지) 빌드가 3개 이상 있으면 성격·스탯포인트·도구·기술을
    거기서 최빈값으로 가져오고(실제 한 벌의 세트라 일관성이 있다), 아니면 op.gg 통계 최빈값을 쓴다.
    stone 을 주면 그 스톤의 메가(리자몽 X/Y 등)로 고정."""
    u = D.USAGE.get(key)
    if not slots:
        slots = [s for t in D.TEAMS for s in t["slots"] if s["pokemon"] in D.DEX and D.base_of(s["pokemon"]) == key
                 and ((s.get("item") in D.STONE) == bool(mega)) and (not stone or s.get("item") == stone)]
    slots = list(slots or ())
    if not u and not slots:
        return None
    stones = [stone] if stone else stones_of(D, key)
    good = [s for s in slots if s.get("customStats") and sum(s["customStats"].values()) >= 60
            and len([m for m in (s.get("moves") or []) if m in D.MOVES]) >= 3]
    if len(good) >= 3 or (not u and good):
        # 항목별 최빈값을 따로 뽑으면 아무도 안 쓰는 조합이 된다(성격·배분·도구·기술이 서로 다른 세트에서 옴).
        # → 실제 빌드 중 나머지와 가장 닮은 한 벌(메도이드)을 통째로 쓴다.
        def sig(s):
            return (s.get("nature"), tuple(s["customStats"][k] for k in _SPK), s.get("item"), s.get("ability"),
                    frozenset(m for m in s.get("moves") or [] if m in D.MOVES))

        sigs = [sig(s) for s in good]

        def sim(a, b):
            return (a[0] == b[0]) + (a[1] == b[1]) + (a[2] == b[2]) + 0.5 * (a[3] == b[3]) + 2 * len(a[4] & b[4]) / 4

        best = max(range(len(good)), key=lambda i: sum(sim(sigs[i], t) for t in sigs))
        s = good[best]
        item = s.get("item") or None
        if mega and item not in D.STONE:
            item = stones[0] if stones else item
        return Build(D, key, [m for m in s["moves"] if m in D.MOVES], item, s.get("ability"), s.get("nature") or "serious",
                     list(sig(s)[1]), label="meta")
    if not u:
        return None
    if mega and stones:
        item = stones[0]
    else:
        item = next((i for i, _ in u["items"] if i not in D.STONE), None)
    ability = u["abilities"][0][0] if u["abilities"] else None
    sp = u["training"][0][0] if u["training"] else [2, 32, 0, 0, 0, 32]
    moves = top_moves(D, key)
    # op.gg 는 성격·배분 분포를 따로만 준다 → 최다 배분에 '맞는' 성격 중 최다를 짝지운다
    from .sets import spread_fits, role_of
    cats = [D.MOVES[m]["cat"] for m in moves if classify(D.MOVES[m]) == "attack"]
    arch = "mixed" if len(set(cats)) > 1 else (cats[0] if cats else "physical")
    nats = [n for n, _ in u["natures"]]
    nature = next((n for n in nats if spread_fits(n, sp, arch) and role_of(n, sp, arch)), nats[0] if nats else "serious")
    return Build(D, key, moves, item, ability, nature, sp, label="meta")


def make_alt(D, b):
    """시뮬이 값을 못 매기는 기술(classify 'none': 스텔스록·압정·길동무·트릭룸 등) 칸을 op.gg 채용 순 다음 공격기로
    바꾼 변형. 바꿀 칸이 없거나 메타몽이면 None."""
    if b is None or b.ability == "imposter":
        return None
    dead = [m for m in b.moves if b.kinds[m] == "none"]
    if not dead:
        return None
    u = D.USAGE.get(b.key) or {"moves": []}
    repl = [m for m, p in u["moves"] if m in D.MOVES and m not in b.moves and classify(D.MOVES[m]) == "attack"]
    if not repl:
        return None
    moves = [m for m in b.moves if m not in dead] + repl[:len(dead)]
    return Build(D, b.key, moves, b.item, b.entry_ability, b.nature, b.sp, label="meta-alt")


def entity_id(key, mega):
    return key + ("@mega" if mega else "")


def opponents(D, prior_top=None, prior_weight=2.0):
    """[(eid, Build, weight)] — weight 합 = 1.
    레플리카 팀 등장 횟수 + 싱글 순위 사전값(전 종, 순위가 낮을수록 지수적으로 작아짐).
    드문 포켓몬도 빠지지 않고 작은 가중치로 들어간다."""
    cnt = Counter()
    slots = {}
    for t in D.TEAMS:
        for s in t["slots"]:
            k = s["pokemon"]
            if k not in D.DEX:
                continue
            base = D.base_of(k)
            mega = D.DEX[k]["base_key"] is not None or (s.get("item") in D.STONE and D.DEX[D.STONE[s["item"]]]["base_key"] == base)
            e = (base, mega)
            cnt[e] += 1
            slots.setdefault(e, []).append(s)
    for r in (D.TIER if prior_top is None else D.TIER[:prior_top]):
        k = r["key"]
        if k not in D.DEX:
            continue
        p = mega_prob(D, k)
        w = prior_weight * math.exp(-(r["rank"] - 1) / 25) + 0.02   # 바닥값: 최하위도 0 이 되지 않게
        cnt[(k, False)] += w * (1 - p)
        if p > 0:
            cnt[(k, True)] += w * p
    out = []
    for (k, mega), w in cnt.items():
        if w <= 0:
            continue
        b = modal_build(D, k, mega, slots.get((k, mega)))
        if b is None or not usable(b):
            continue
        out.append((entity_id(k, mega), b, w))
    tot = sum(w for _, _, w in out)
    out.sort(key=lambda x: -x[2])
    return [(e, b, w / tot) for e, b, w in out]


def team_entities(D, team):
    """레플리카 팀 1개 → [(key, mega)]"""
    out = []
    for s in team["slots"]:
        k = s["pokemon"]
        if k not in D.DEX:
            continue
        base = D.base_of(k)
        mega = D.DEX[k]["base_key"] is not None or (s.get("item") in D.STONE and D.DEX[D.STONE[s["item"]]]["base_key"] == base)
        out.append((base, mega))
    return out
