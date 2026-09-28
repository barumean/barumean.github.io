"""Model B — 3:3 순차 시뮬레이션(엔진 재사용, 코드 수정 없음: 이 프로세스 안에서만 engine._side·Field·_setup_field 를 감싼다).

정책(이게 없으면 Model B 는 정의되지 않는다):
  전략      (3마리 조합, 선봉) — 한쪽 60개. 양쪽이 동시에(상대 선출을 모른 채) 고른다.
  대면 구간  engine.simulate 로 한쪽이 쓰러질 때까지. 확률 모드(rng: 명중·난수·급소·마비·잠듦 턴).
            구간 시작마다 '현재 상태'에서 plan_matrix(결정적 모드)의 계획 게임을 풀고, 균형 혼합에서 계획을 뽑는다.
  이월      생존자: HP·상태이상(+잠듦·맹독 카운터)·랭크·PP·소모한 도구·탈·구애 고정·혼란·도발·앙코르·씨뿌리기·턴 수.
            (구간이 바뀌면 속박은 풀리고, 계획 표지(상태이상·필드 1회)는 새 계획으로 다시 쓴다.)
            새로 나온 쪽: 새 Side(만피, 속이기 가능). 등장 특성(위협·트레이스·날씨·필드)은 새로 나온 쪽만 발동.
            필드(날씨·필드·남은 턴)는 이어진다. 벽(리플렉터·빛의장막)은 팀 단위로 이어진다.
            마무리 포켓몬(총대장·성묘)의 '쓰러진 동료 수'는 실제 수.
  기절 교대  쓰러진 쪽은 남은 포켓몬 중 '상대 필드 포켓몬(현재 상태)과의 결정적 1:1 값(duel, branch=False)'이 가장 큰 쪽을 낸다.
            양쪽이 같은 턴에 쓰러지면 서로 상대 새 포켓몬을 모르므로 '상대 남은 포켓몬(만피)에 대한 평균 duel 값'이 가장 큰 쪽을 동시에 낸다.
  교체      자발적 교체 없음(대면한 포켓몬이 끝까지 싸운다; 유턴류도 교체 없음). ← Model B 의 가장 큰 단순화
  종료      한쪽 3마리가 모두 쓰러지면 끝. 한 구간이 60턴 안에 안 끝나면 그 판은 무승부(0).
  보수      A 승 = +0.5 + 0.5 × (A 생존 HP 비율 합 / 3),  A 패 = −(0.5 + 0.5 × B 생존 HP 비율 합 / 3),  무승부 0.
            마지막 두 마리가 같은 턴에 쓰러지면 simulate 의 '먼저 쓰러진 쪽이 진다' 규칙(±0.5).
"""
import copy
import random

import numpy as np

import _common  # noqa: F401
from champions import engine
from champions.engine import (plan_matrix, simulate, is_closer, INTIM_BLOCK, NO_TRACE, WEATHER_AB, TERRAIN_AB,
                              WEATHER_ROCK)
from champions.game import solve

_ORIG = {"side": engine._side, "field": engine.Field, "setup": engine._setup_field}
_LIST_ATTRS = ("boost", "pp", "miss", "sec", "used", "types", "stats")


def copy_side(s):
    c = copy.copy(s)
    for k in _LIST_ATTRS:
        v = getattr(s, k)
        if isinstance(v, (list, dict, set)):
            setattr(c, k, type(v)(v))
    return c


class Env:
    """이월 상태를 simulate 에 주입하는 환경. carry: id(Build) → 템플릿 Side, field: 템플릿 Field,
    fainted: id(Build) → 그 팀의 쓰러진 수(새 Side 용), screens: id(Build) → (scr_p, scr_s)."""

    def __init__(self):
        self.carry, self.field, self.fainted, self.screens = {}, None, {}, {}
        self.record, self.created, self.fields = False, [], []

    def _side(self, X, Y, hp):
        t = self.carry.get(id(X))
        if t is not None:
            s = copy_side(t)
        else:
            s = _ORIG["side"](X, Y, hp)
            if is_closer(X):
                s.fainted = self.fainted.get(id(X), 0)
            sc = self.screens.get(id(X))
            if sc:
                s.scr_p, s.scr_s = sc
        if self.record:
            self.created.append(s)
        return s

    def _field(self):
        f = copy.copy(self.field) if self.field is not None else _ORIG["field"]()
        if self.record:
            self.fields.append(f)
        return f

    @staticmethod
    def _setup(a, b, field):
        if a.turn == 0 and b.turn == 0:
            return _ORIG["setup"](a, b, field)
        new, old = (a, b) if a.turn == 0 else (b, a)
        if new.turn != 0:
            return None
        ent = new.b.entry_ability
        if ent == "trace" and old.ability not in NO_TRACE:
            ent = old.ability
            if not new.b.mega:
                new.ability = old.ability
        if ent == "intimidate" and old.ability not in INTIM_BLOCK and old.item != "clear-amulet":
            ey = old.ability
            if ey == "guard-dog":
                old.boost[1] = min(6, old.boost[1] + 1)
            elif ey == "mirror-armor":
                new.boost[1] = max(-6, new.boost[1] - 1)
            else:
                old.boost[1] = max(-6, min(6, old.boost[1] + (-1 if ey != "contrary" else 1)))
                if ey == "defiant":
                    old.boost[1] = min(6, old.boost[1] + 2)
                if ey == "competitive":
                    old.boost[3] = min(6, old.boost[3] + 2)
                if ey == "rattled":
                    old.boost[5] = min(6, old.boost[5] + 1)
        w = WEATHER_AB.get(new.ability)
        if w:
            field.weather, field.wturns = w, (8 if new.item == WEATHER_ROCK.get(w) else 5)
        t = TERRAIN_AB.get(new.ability)
        if t:
            field.terrain, field.tturns = t, (8 if new.item == "terrain-extender" else 5)
        field.aura = "fairy-aura" in (new.ability, old.ability)
        return None

    def __enter__(self):
        engine._side, engine.Field, engine._setup_field = self._side, self._field, self._setup
        return self

    def __exit__(self, *a):
        engine._side, engine.Field, engine._setup_field = _ORIG["side"], _ORIG["field"], _ORIG["setup"]


def _eq_plans(A, B):
    O, _ = plan_matrix(A, B, branch=False)
    O = np.asarray(O, float)
    if O.shape == (1, 1):
        return np.array([1.0]), np.array([1.0]), float(O[0, 0])
    v, x, y = solve(O)
    return np.clip(x, 0, None) / np.clip(x, 0, None).sum(), np.clip(y, 0, None) / np.clip(y, 0, None).sum(), v


def _duel_value(env, X, Y):
    O, _ = plan_matrix(X, Y, branch=False)
    return solve(np.asarray(O, float))[0] if len(O) * len(O[0]) > 1 else float(O[0][0])


def battle(env, TA, TB, leadA, leadB, rng, trace=None):
    """TA, TB: Build 3개씩. 반환 (A 입장 보수, A 승=1/패=0/무=0.5)."""
    aliveA, aliveB = [True] * 3, [True] * 3
    hpA, hpB = [1.0] * 3, [1.0] * 3
    curA, curB = leadA, leadB
    bA, bB = list(TA), list(TB)                 # 현재 빌드(메타몽은 변신한 빌드로 바뀐다)
    env.carry, env.field, env.screens = {}, None, {}
    team_scr = {"A": (0, 0), "B": (0, 0)}
    for _ in range(12):
        env.fainted = {id(bA[i]): 3 - sum(aliveA) for i in range(3)}
        env.fainted.update({id(bB[i]): 3 - sum(aliveB) for i in range(3)})
        env.screens = {id(bA[i]): team_scr["A"] for i in range(3)}
        env.screens.update({id(bB[i]): team_scr["B"] for i in range(3)})
        A, B = bA[curA], bB[curB]
        x, y, _ = _eq_plans(A, B)
        pa, pb = engine.plans_vs(A, B), engine.plans_vs(B, A)
        # plan_matrix 는 carry 가 있으면 이월 상태로 계산된다(_side 가 복사본을 준다)
        i = int(rng.choices(range(len(x)), weights=x)[0]); j = int(rng.choices(range(len(y)), weights=y)[0])
        env.record, env.created, env.fields = True, [], []
        v = simulate(A, B, pa[i], pb[j], rng=rng)
        env.record = False
        sa, sb = env.created[0], env.created[1]
        field = env.fields[0]
        if trace is not None:
            trace.append((A.D.name(A.form), A.D.name(B.form), round(sa.hp / sa.maxhp, 3), round(sb.hp / sb.maxhp, 3), v))
        a_dead, b_dead = sa.hp <= 0, sb.hp <= 0
        if not a_dead and not b_dead:
            return 0.0, 0.5                           # 한 구간이 60턴 — 무승부
        hpA[curA], hpB[curB] = max(0.0, sa.hp / sa.maxhp), max(0.0, sb.hp / sb.maxhp)
        team_scr["A"], team_scr["B"] = (sa.scr_p, sa.scr_s), (sb.scr_p, sb.scr_s)
        env.field = field
        env.carry = {}
        if a_dead:
            aliveA[curA] = False
        else:
            sa.bound, sa.status_done, sa.field_done = 0, False, False
            bA[curA] = sa.b                           # 메타몽: 변신한 빌드로 계속
            env.carry[id(sa.b)] = sa
        if b_dead:
            aliveB[curB] = False
        else:
            sb.bound, sb.status_done, sb.field_done = 0, False, False
            bB[curB] = sb.b
            env.carry[id(sb.b)] = sb
        if not any(aliveA) or not any(aliveB):
            if not any(aliveA) and not any(aliveB):
                return (0.5, 1.0) if v > 0 else (-0.5, 0.0) if v < 0 else (0.0, 0.5)
            if not any(aliveB):
                return 0.5 + 0.5 * sum(h for h, al in zip(hpA, aliveA) if al) / 3, 1.0
            return -(0.5 + 0.5 * sum(h for h, al in zip(hpB, aliveB) if al) / 3), 0.0
        # 교대 정책
        if a_dead and b_dead:
            remA = [k for k in range(3) if aliveA[k]]; remB = [k for k in range(3) if aliveB[k]]
            env.carry = {}
            curA = max(remA, key=lambda k: np.mean([_duel_value(env, bA[k], bB[m]) for m in remB]))
            curB = max(remB, key=lambda m: np.mean([_duel_value(env, bB[m], bA[k]) for k in remA]))
        elif a_dead:
            env.fainted = {id(bA[i]): 3 - sum(aliveA) for i in range(3)}
            curA = max((k for k in range(3) if aliveA[k]), key=lambda k: _duel_value(env, bA[k], bB[curB]))
        else:
            env.fainted = {id(bB[i]): 3 - sum(aliveB) for i in range(3)}
            curB = max((m for m in range(3) if aliveB[m]), key=lambda m: _duel_value(env, bB[m], bA[curA]))
    return 0.0, 0.5


STRATS = [(t, l) for t in [(0, 1, 2), (0, 1, 3), (0, 1, 4), (0, 1, 5), (0, 2, 3), (0, 2, 4), (0, 2, 5), (0, 3, 4), (0, 3, 5),
                           (0, 4, 5), (1, 2, 3), (1, 2, 4), (1, 2, 5), (1, 3, 4), (1, 3, 5), (1, 4, 5), (2, 3, 4), (2, 3, 5),
                           (2, 4, 5), (3, 4, 5)] for l in range(3)]      # (조합, 조합 안의 선봉 위치) — TRI 순서와 같다


# ── 병렬 작업자 ──────────────────────────────────────────────────
_W = {}


def _init(my_specs, opp_specs, n_runs, seed, opp_variant_specs=None):
    from champions.data import load
    from champions.engine import Build
    D = load()
    _W["my"] = [Build(D, **s) for s in my_specs]
    _W["opp"] = [Build(D, **s) for s in opp_specs]
    _W["var"] = None
    if opp_variant_specs:
        _W["var"] = [[(Build(D, **s), p) for s, p in vs] if vs else None for vs in opp_variant_specs]
    _W["n"], _W["seed"] = n_runs, seed
    _W["env"] = Env()


def row(sa):
    """내 전략 sa(0..59) 한 행: 상대 60 전략 × n_runs → (값 배열 (60, n), 승 배열 (60, n))."""
    tri_a, la = STRATS[sa]
    env = _W["env"]
    vals = np.zeros((60, _W["n"])); wins = np.zeros((60, _W["n"]))
    with env:
        for sb, (tri_b, lb) in enumerate(STRATS):
            TA = [_W["my"][i] for i in tri_a]
            for r in range(_W["n"]):
                rng = random.Random(_W["seed"] * 1000003 + r)
                if _W["var"]:
                    TB = []
                    for j in tri_b:
                        vs = _W["var"][j]
                        TB.append(_W["opp"][j] if not vs else rng.choices([b for b, _ in vs], weights=[p for _, p in vs])[0])
                else:
                    TB = [_W["opp"][j] for j in tri_b]
                vals[sb, r], wins[sb, r] = battle(env, TA, TB, la, lb, rng)
    return vals, wins


def model_b(my_builds, opp_builds, n_runs=16, seed=20260927, workers=3, opp_variants=None):
    """(60, 60, n) 보수 표본과 승 표본."""
    from concurrent.futures import ProcessPoolExecutor
    my_specs = [b.spec() for b in my_builds]
    opp_specs = [b.spec() for b in opp_builds]
    ovs = None
    if opp_variants:
        ovs = [[(b.spec(), p) for b, p in vs] if vs else None for vs in opp_variants]
    if workers <= 1:
        _init(my_specs, opp_specs, n_runs, seed, ovs)
        res = [row(s) for s in range(60)]
    else:
        with ProcessPoolExecutor(workers, initializer=_init, initargs=(my_specs, opp_specs, n_runs, seed, ovs)) as ex:
            res = list(ex.map(row, range(60)))
    return np.stack([r[0] for r in res]), np.stack([r[1] for r in res])


# ── 결정적 Model B(기대값 모드 + 계획 혼합의 확률 가중 트리, 경로 캐시) ─────────────
def _eff(X, Y):
    """plan_matrix 와 같은 시작 동률 판정(빌드 스피드 × 스카프)."""
    return (Y.stats[5] if X.ability == "imposter" else X.stats[5]) * (1.5 if (X.item == "choice-scarf" and not X.mega) else 1.0)


class DetCtx:
    """경로(지금까지 나온 포켓몬과 구간 결과의 순서)가 상태를 결정하므로 구간 결과·교대 선택을 경로로 캐시한다(정확)."""

    def __init__(self, my, opp):
        self.my, self.opp = my, opp
        self.env = Env()
        self.seg, self.repl = {}, {}

    def segment(self, key, A, B, carry, field, fainted, screens):
        r = self.seg.get(key)
        if r is not None:
            return r
        env = self.env
        env.carry, env.field, env.fainted, env.screens = carry, field, fainted, screens
        x, y, _ = _eq_plans(A, B)
        pa, pb = engine.plans_vs(A, B), engine.plans_vs(B, A)
        tie = (not carry) and _eff(A, B) == _eff(B, A)
        orders = [(True, 0.5), (False, 0.5)] if tie else [(True, 1.0)]
        out = []
        for i in np.nonzero(x > 1e-9)[0]:
            for j in np.nonzero(y > 1e-9)[0]:
                for taf, po in orders:
                    env.record, env.created, env.fields = True, [], []
                    v = simulate(A, B, pa[i], pb[j], tie_a_first=taf)
                    env.record = False
                    out.append((float(x[i] * y[j] * po), env.created[0], env.created[1], env.fields[0], v))
        self.seg[key] = out
        return out


def battle_det(ctx, triA, triB, la, lb):
    """결정적 Model B 한 칸: (기대 보수, 승률(무승부 ½)). triA/triB 는 파티 인덱스 3개, la/lb 는 조합 안 선봉 위치."""
    st = {"aliveA": (True,) * 3, "aliveB": (True,) * 3, "hpA": (1.0,) * 3, "hpB": (1.0,) * 3,
          "curA": la, "curB": lb, "bA": tuple(ctx.my[i] for i in triA), "bB": tuple(ctx.opp[j] for j in triB),
          "carry": {}, "field": None, "scrA": (0, 0), "scrB": (0, 0)}
    return _rec(ctx, triA, triB, st, ())


def _rec(ctx, triA, triB, st, path):
    env = ctx.env
    aliveA, aliveB, bA, bB = st["aliveA"], st["aliveB"], st["bA"], st["bB"]
    curA, curB = st["curA"], st["curB"]
    A, B = bA[curA], bB[curB]
    fainted = {id(bA[i]): 3 - sum(aliveA) for i in range(3)}
    fainted.update({id(bB[i]): 3 - sum(aliveB) for i in range(3)})
    screens = {id(bA[i]): st["scrA"] for i in range(3)}
    screens.update({id(bB[i]): st["scrB"] for i in range(3)})
    gA, gB = triA[curA], triB[curB]
    key = path + ((gA, gB),)
    outs = ctx.segment(key, A, B, st["carry"], st["field"], fainted, screens)
    EV = EW = 0.0
    for k, (p, sa0, sb0, fld0, v) in enumerate(outs):
        sa, sb, fld = copy_side(sa0), copy_side(sb0), copy.copy(fld0)
        a_dead, b_dead = sa.hp <= 0, sb.hp <= 0
        if not a_dead and not b_dead:
            EW += p * 0.5
            continue                                  # 60턴 무승부
        hpA, hpB = list(st["hpA"]), list(st["hpB"])
        alA, alB = list(aliveA), list(aliveB)
        nbA, nbB = list(bA), list(bB)
        hpA[curA], hpB[curB] = max(0.0, sa.hp / sa.maxhp), max(0.0, sb.hp / sb.maxhp)
        carry = {}
        if a_dead:
            alA[curA] = False
        else:
            sa.bound, sa.status_done, sa.field_done = 0, False, False
            nbA[curA] = sa.b
            carry[id(sa.b)] = sa
        if b_dead:
            alB[curB] = False
        else:
            sb.bound, sb.status_done, sb.field_done = 0, False, False
            nbB[curB] = sb.b
            carry[id(sb.b)] = sb
        if not any(alA) or not any(alB):
            if not any(alA) and not any(alB):
                pv, pw = ((0.5, 1.0) if v > 0 else (-0.5, 0.0) if v < 0 else (0.0, 0.5))
            elif not any(alB):
                pv, pw = 0.5 + 0.5 * sum(h for h, al in zip(hpA, alA) if al) / 3, 1.0
            else:
                pv, pw = -(0.5 + 0.5 * sum(h for h, al in zip(hpB, alB) if al) / 3), 0.0
            EV += p * pv; EW += p * pw
            continue
        sub = path + ((gA, gB, k),)
        nA, nB = curA, curB
        remA = tuple(i for i in range(3) if alA[i]); remB = tuple(i for i in range(3) if alB[i])
        rk = (sub, tuple(triA[i] for i in remA), tuple(triB[i] for i in remB))
        if rk in ctx.repl:
            nA, nB = ctx.repl[rk]
        else:
            fa = {id(nbA[i]): 3 - sum(alA) for i in range(3)}
            fa.update({id(nbB[i]): 3 - sum(alB) for i in range(3)})
            env.fainted, env.field, env.screens = fa, fld, {}
            if a_dead and b_dead:
                env.carry = {}
                nA = max(remA, key=lambda i: np.mean([_duel_value(env, nbA[i], nbB[m]) for m in remB]))
                nB = max(remB, key=lambda m: np.mean([_duel_value(env, nbB[m], nbA[i]) for i in remA]))
            elif a_dead:
                env.carry = carry
                nA = max(remA, key=lambda i: _duel_value(env, nbA[i], nbB[curB]))
            else:
                env.carry = carry
                nB = max(remB, key=lambda m: _duel_value(env, nbB[m], nbA[curA]))
            ctx.repl[rk] = (nA, nB)
        st2 = {"aliveA": tuple(alA), "aliveB": tuple(alB), "hpA": tuple(hpA), "hpB": tuple(hpB), "curA": nA, "curB": nB,
               "bA": tuple(nbA), "bB": tuple(nbB), "carry": carry, "field": fld,
               "scrA": (sa.scr_p, sa.scr_s), "scrB": (sb.scr_p, sb.scr_s)}
        sv, sw = _rec(ctx, triA, triB, st2, sub)
        EV += p * sv; EW += p * sw
    return EV, EW


def model_b_det(my, opp, log=None):
    """(60, 60) 기대 보수 M 과 승률 W. 단일 프로세스(경로 캐시를 공유해야 빠르다)."""
    ctx = DetCtx(my, opp)
    M, W = np.zeros((60, 60)), np.zeros((60, 60))
    with ctx.env:
        for sa, (ta, la) in enumerate(STRATS):
            for sb, (tb, lb) in enumerate(STRATS):
                M[sa, sb], W[sa, sb] = battle_det(ctx, ta, tb, la, lb)
            if log and sa % 12 == 11:
                log(f"    Model B 행 {sa + 1}/60 (구간 캐시 {len(ctx.seg)})")
    return M, W
