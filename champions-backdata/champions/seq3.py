"""3:3 순차 평가 — 상태를 이어 가며 1:1 엔진을 이어 붙인다(tests/model_b.py 의 결정적 Model B 를 옮긴 것).

정책
  대면 구간  engine.simulate 로 한쪽이 쓰러질 때까지(결정적 모드). 구간마다 '현재 상태'에서 계획 게임을 풀고,
            균형 혼합의 계획 쌍을 확률 가중 트리로 전개한다.
  이월      생존자의 HP·상태이상·랭크·PP·소모한 도구·탈·구애 고정·혼란·도발·앙코르·씨뿌리기·턴 수, 날씨·필드, 팀 단위 벽.
            새로 나온 쪽만 등장 특성(위협·트레이스·날씨·필드)이 발동한다.
  기절 교대  쓰러진 쪽은 남은 포켓몬 중 '지금 상대와의 1:1 값'이 가장 큰 쪽을 낸다. 동시에 쓰러지면 상대 남은 포켓몬과의
            평균 값이 가장 큰 쪽을 동시에 낸다.
  교체 등장  pre='A' 면 내 선봉이 교체로 들어와 상대 선봉의 공짜 한 방을 맞고 시작, 'B' 면 그 반대.
  보수      이기면 +0.5 + 0.5·(남은 HP 합 / 3), 지면 반대, 한 구간이 60턴이면 0.

속도: 같은 상태(양쪽 현재 포켓몬의 이월 상태·필드)에 이르면 경로가 달라도 구간 결과를 다시 쓴다(상태 캐시).
tests/model_b.py 는 경로로만 캐시해서 선봉 턴 교체까지 넣으면 한 상대 팀에 3~9분 걸렸다. 상태 캐시에 더해
구간 하나를 한 번만 시뮬하고(계획 게임·이월 상태·기절 교대 판단이 같은 계산을 쓴다), 한 턴 안의 best_attack 중복을
메모로 없애 같은 계산이 8~19초다. Model B 대비 칸 평균 차이 0.002~0.02(경기 중 스피드 동률을 번갈아 대신 50:50 으로
나누고, 기절 교대 판단에 필드의 벽을 넣은 차이), 반대칭은 정확(1e-15).

엔진 코드는 바꾸지 않는다(바꾸면 세트·행렬 캐시가 전부 다시 계산된다). 계산하는 동안만 engine 의
_side·Field·_setup_field·best_attack·act·end_of_turn·simulate 를 감싸고 끝나면 되돌린다(단일 스레드).
"""
import copy

import numpy as np

from . import engine
from .engine import is_closer, INTIM_BLOCK, NO_TRACE, WEATHER_AB, TERRAIN_AB, WEATHER_ROCK
from .game import solve

_ORIG = {"side": engine._side, "field": engine.Field, "setup": engine._setup_field, "best": engine.best_attack,
         "act": engine.act, "eot": engine.end_of_turn, "sim": engine.simulate}
_MUTABLE = ("boost", "pp", "miss", "sec", "used", "types", "stats")


def copy_side(s):
    c = copy.copy(s)
    for k in _MUTABLE:
        v = getattr(s, k)
        if isinstance(v, (list, dict, set)):
            setattr(c, k, type(v)(v))
    return c


class Env:
    """이월 상태를 simulate 에 넣는 환경. carry: id(Build) → 이어 갈 Side, field: 이어 갈 Field,
    fainted: id(Build) → 그 팀에서 쓰러진 수(마무리 포켓몬용), screens: id(Build) → (리플렉터, 빛의장막) 남은 턴."""

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

    # 한 턴 안에서는 행동 전까지 상태가 바뀌지 않는데 best_attack 을 같은 인자로 여러 번 부른다(양쪽 choose 가
    # 'KO 만', '상대 최선', '최종'을 각각 계산). 상태가 바뀌는 act·end_of_turn·새 simulate 마다 비우는 메모로 줄인다.
    # KO 가 있으면 전체 호출과 'KO 만' 호출의 결과가 같다(둘 다 같은 KO 수를 돌려준다) — 값은 비트 단위로 같다.
    def _bump(self, f):
        memo = self.memo

        def g(*a, **k):
            memo.clear()
            return f(*a, **k)
        return g

    def _best(self, s, o, field, can_ko_only=False, avoid=()):
        memo = self.memo
        key = (id(s), id(o), bool(avoid))
        ko = memo.get(("ko",) + key, False)
        if can_ko_only:
            if ko is False:
                ko = _ORIG["best"](s, o, field, True, avoid)
                memo[("ko",) + key] = ko
            return ko
        full = memo.get(("full",) + key)
        if full is None:
            full = ko if (ko is not False and ko is not None) else _ORIG["best"](s, o, field, False, avoid)
            memo[("full",) + key] = full
        return full

    def __enter__(self):
        self.memo = {}
        engine._side, engine.Field, engine._setup_field = self._side, self._field, self._setup
        engine.best_attack = self._best
        engine.act, engine.end_of_turn, engine.simulate = (self._bump(_ORIG["act"]), self._bump(_ORIG["eot"]),
                                                           self._bump(_ORIG["sim"]))
        return self

    def __exit__(self, *a):
        engine._side, engine.Field, engine._setup_field = _ORIG["side"], _ORIG["field"], _ORIG["setup"]
        engine.best_attack, engine.act, engine.end_of_turn, engine.simulate = (_ORIG["best"], _ORIG["act"], _ORIG["eot"],
                                                                               _ORIG["sim"])


def _eq(O):
    O = np.asarray(O, float)
    if O.size == 1:
        return np.array([1.0]), np.array([1.0]), float(O.flat[0])
    v, x, y = solve(O)
    x, y = np.clip(x, 0, None), np.clip(y, 0, None)
    return x / x.sum(), y / y.sum(), v


def side_sig(s):
    """이월 상태의 요약(상태 캐시 키). 빗나감·부가효과 누적값은 넣지 않는다(작은 근사)."""
    if s is None:
        return None
    return (round(s.hp / s.maxhp, 2), tuple(s.boost), s.status, s.sleep, s.tox, s.item, s.disguise, s.locked, s.charging,
            s.recharge, s.blade, s.sitrus, s.seeded, s.turn > 0, tuple(min(v, 3) for v in s.pp.values()), s.taunt, s.encore,
            s.encore_mv, s.confused, s.rampage, s.frz_t, s.wish, s.drowsy, tuple(s.types), s.ability, s.protean_used,
            s.charged, s.fainted, min(s.hits_taken, 6), s.air, s.bound)


def field_sig(f):
    return None if f is None else (f.weather, f.wturns, f.terrain, f.tturns, f.aura)


class Seq:
    """한 상대 팀(빌드 목록)에 대한 3:3 순차 평가기. 캐시는 조합 쌍·선봉·스톤 조합 사이에서 공유한다.
    my, opp: Build 목록(파티 6, 상대 6 — 메가형 빌드를 따로 넣어도 된다). 조합은 슬롯 번호로 부른다."""

    def __init__(self, my, opp):
        self.my, self.opp = list(my), list(opp)
        self.env = Env()
        self.seg = {}
        self.n_sim = 0

    def _fight(self, A, B, pre=None):
        """지금 env 상태에서 A 대 B 구간 하나: 계획 게임(결정적 모드: 동률만 두 순서로 평균)을 풀고
        (균형 지지 계획 쌍의 잎들 [(확률, A Side, B Side, Field, 값)], 균형값). pre 는 교체 등장(첫 구간).
        plan_matrix(branch=False) 와 같은 값을 내되, 잎의 상태를 그대로 받아 두어 다시 시뮬하지 않는다."""
        env = self.env
        X, Y = (B, A) if pre == "B" else (A, B)
        px, py = engine.plans_vs(X, Y), engine.plans_vs(Y, X)
        cells = []
        O = np.zeros((len(px), len(py)))
        for i, x in enumerate(px):
            for j, y in enumerate(py):
                leaves, stack = [], [[]]
                while stack:
                    prefix = stack.pop()
                    br = engine.Brancher(prefix, acc=0, thr=0, tie=1)
                    env.record, env.created, env.fields = True, [], []
                    v = engine.simulate(X, Y, x, y, pre_hit=pre is not None, br=br)
                    env.record = False
                    self.n_sim += 1
                    leaves.append((br.prob, env.created[0], env.created[1], env.fields[0], v))
                    for k in range(len(prefix), len(br.taken)):
                        for alt in range(1, br.nopts[k]):
                            stack.append(br.taken[:k] + [alt])
                O[i, j] = sum(p * v for p, _, _, _, v in leaves)
                cells.append(leaves)
        xa, yb, val = _eq(O)
        outs = []
        for i in np.nonzero(xa > 1e-9)[0]:
            for j in np.nonzero(yb > 1e-9)[0]:
                for p, sx, sy, f, v in cells[i * len(py) + j]:
                    w = float(xa[i] * yb[j] * p)
                    outs.append((w, sy, sx, f, -v) if pre == "B" else (w, sx, sy, f, v))
        return outs, (-val if pre == "B" else val)

    def _segment(self, A, B, carry, field, fainted, screens):
        """상태 캐시: 양쪽 현재 포켓몬의 이월 상태·필드·쓰러진 수·벽이 같으면 경로가 달라도 같은 결과를 쓴다."""
        sg = (id(A), side_sig(carry.get(id(A))), id(B), side_sig(carry.get(id(B))), field_sig(field),
              fainted.get(id(A), 0), fainted.get(id(B), 0), screens.get(id(A)), screens.get(id(B)))
        r = self.seg.get(sg)
        if r is None:
            env = self.env
            env.carry, env.field, env.fainted, env.screens = carry, field, fainted, screens
            r = self._fight(A, B)
            self.seg[sg] = r
        return r

    def _segment_pre(self, A, B, pre):
        key = (pre, id(A), id(B))
        r = self.seg.get(key)
        if r is None:
            env = self.env
            env.carry, env.field, env.fainted, env.screens = {}, None, {}, {}
            r = self._fight(A, B, pre)
            self.seg[key] = r
        return r

    def battle(self, ta, tb, la, lb, pre=None):
        """내 조합 ta(파티 슬롯 3) 의 선봉 위치 la 대 상대 조합 tb 의 선봉 위치 lb → 기대 보수(내 입장).
        pre='A' 면 내 선봉이 교체로 들어와 상대 선봉의 한 방을 맞고 시작, 'B' 면 그 반대."""
        bA, bB = tuple(self.my[i] for i in ta), tuple(self.opp[j] for j in tb)
        st = {"aliveA": (True,) * 3, "aliveB": (True,) * 3, "hpA": (1.0,) * 3, "hpB": (1.0,) * 3,
              "curA": la, "curB": lb, "bA": bA, "bB": bB, "carry": {}, "field": None, "scrA": (0, 0), "scrB": (0, 0)}
        with self.env:
            first = self._segment_pre(bA[la], bB[lb], pre)[0] if pre else None
            return self._rec(st, first)

    @staticmethod
    def _ctx(bA, bB, aliveA, aliveB, scrA, scrB):
        fainted = {id(bA[i]): 3 - sum(aliveA) for i in range(3)}
        fainted.update({id(bB[i]): 3 - sum(aliveB) for i in range(3)})
        screens = {id(bA[i]): scrA for i in range(3)}
        screens.update({id(bB[i]): scrB for i in range(3)})
        return fainted, screens

    def _rec(self, st, first=None):
        aliveA, aliveB, bA, bB = st["aliveA"], st["aliveB"], st["bA"], st["bB"]
        curA, curB = st["curA"], st["curB"]
        if first is not None:
            outs = first
        else:
            fainted, screens = self._ctx(bA, bB, aliveA, aliveB, st["scrA"], st["scrB"])
            outs = self._segment(bA[curA], bB[curB], st["carry"], st["field"], fainted, screens)[0]
        EV = 0.0
        for p, sa0, sb0, fld0, v in outs:
            sa, sb, fld = copy_side(sa0), copy_side(sb0), copy.copy(fld0)
            a_dead, b_dead = sa.hp <= 0, sb.hp <= 0
            if not a_dead and not b_dead:
                continue                                  # 60턴 무승부(0)
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
                    pv = 0.5 if v > 0 else -0.5 if v < 0 else 0.0
                elif not any(alB):
                    pv = 0.5 + 0.5 * sum(h for h, al in zip(hpA, alA) if al) / 3
                else:
                    pv = -(0.5 + 0.5 * sum(h for h, al in zip(hpB, alB) if al) / 3)
                EV += p * pv
                continue
            remA = [i for i in range(3) if alA[i]]
            remB = [i for i in range(3) if alB[i]]
            scrA, scrB = (sa.scr_p, sa.scr_s), (sb.scr_p, sb.scr_s)
            fainted, screens = self._ctx(nbA, nbB, alA, alB, scrA, scrB)
            # 기절 교대: 다음 구간의 균형값으로 고른다(고른 쪽의 구간은 캐시에 남아 그대로 이어 쓴다)
            def val(X, Y, c, f=fld, fa=fainted, sc=screens):
                return self._segment(X, Y, c, f, fa, sc)[1]
            nA, nB = curA, curB
            if a_dead and b_dead:
                nA = max(remA, key=lambda i: np.mean([val(nbA[i], nbB[m], {}) for m in remB]))
                nB = min(remB, key=lambda m: np.mean([val(nbA[i], nbB[m], {}) for i in remA]))
            elif a_dead:
                nA = max(remA, key=lambda i: val(nbA[i], nbB[curB], carry))
            else:
                nB = min(remB, key=lambda m: val(nbA[curA], nbB[m], carry))
            st2 = {"aliveA": tuple(alA), "aliveB": tuple(alB), "hpA": tuple(hpA), "hpB": tuple(hpB), "curA": nA,
                   "curB": nB, "bA": tuple(nbA), "bB": tuple(nbB), "carry": carry, "field": fld, "scrA": scrA, "scrB": scrB}
            EV += p * self._rec(st2)
        return EV
