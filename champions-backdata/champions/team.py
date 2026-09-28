"""팀 구성(6마리) 탐색과 선출 게임.

선출 게임: 서로 6마리를 보고 3마리씩 낸다. 내 3 (a) 대 상대 3 (b) 의 값
    P(a,b) = mean_{i∈a, j∈b} V[i,j]   (기본, AGG_W = 0)
    예전 식 ½·mean_j max_i V + ½·mean_i min_j V 는 AGG_W = 1 (카운터 재사용 가정이 과대평가를 만들어 바꿈)
팀 대 팀 값 = (max_a min_b P + min_b max_a P) / 2   — 하한과 상한의 평균
팀 점수     = 레플리카 싱글 팀(실제 제출된 팀) 전체에 대한 평균

제약: 종 중복 없음, 도구 중복 없음(아이템 클로즈), 메가 스톤 1장 이하, 마무리 포켓몬(총대장·성묘) 1마리 이하.
상대 팀이 스톤을 둘 이상 들었으면(레플리카 팀의 76%) 배틀에서 메가진화는 한 번뿐이다 → 상대가 스톤 든 둘을 같이 내면
그중 나에게 더 불리한 쪽만 메가, 다른 쪽은 기본형으로 계산한다(선출 보드와 같은 규칙).
"""
import itertools
import random

import numpy as np

TRI = np.array(list(itertools.combinations(range(6), 3)))  # (20,3)


# 3:3 집계식: P(a,b) = (1−w)·mean_{i∈a,j∈b} V + w·(½·mean_j max_i V + ½·mean_i min_j V).
# REPORT(09-27) 5-3: 순차 3:3 모델(Model B) 기준으로 ½max+½min(w=1)은 단순 평균(w=0)보다 후회가 +0.13 [0.02, 0.34]
# 컸다(6/6팀). 카운터를 만피로 무한히 재사용한다는 가정이 과대평가를 만든다 → 기본 w=0. 민감도 분석에 w=1 변형을 둔다.
AGG_W = 0.0


def _pick_P(M, w=None):
    w = AGG_W if w is None else w
    A = M[TRI]                                   # (20a, 3, T, 6)
    B = A[:, :, :, TRI]                          # (20a, 3, T, 20b, 3)
    mean = B.mean(axis=(1, 4))                   # (20a, T, 20b)
    if w <= 0:
        return mean
    ans = B.max(axis=1).mean(axis=-1)            # (20a, T, 20b)
    cnt = B.min(axis=-1).mean(axis=1)            # (20a, T, 20b)
    return (1 - w) * mean + w * 0.5 * (ans + cnt)


def pick_values(M, alt=None):
    """M: (6, T, 6) 내 6 × 상대팀 T × 상대 6 → (T,) 팀 대 팀 값, 그리고 (20,20,T) P.
    alt = (M1, M2, both): 스톤 든 두 칸 중 하나만 메가인 두 변형과, 상대 조합이 두 칸을 모두 포함하는지 (T, 20b).
    두 칸을 모두 낸 조합은 상대가 나에게 더 불리한 쪽을 메가진화한다."""
    P = _pick_P(M)
    if alt is not None:
        M1, M2, both = alt
        Pm = np.minimum(_pick_P(M1), _pick_P(M2))
        P = np.where(both[None, :, :], Pm, P)
    lower = P.min(axis=2).max(axis=0)            # (T,)
    upper = P.max(axis=0).min(axis=1)            # (T,)
    return 0.5 * (lower + upper), P


def _closer_card(c):
    """마무리 포켓몬 카드(총대장·성묘). 1:1 값은 '동료 2마리가 쓰러진 뒤 마지막에 나옴'으로 계산하므로
    한 팀에 둘이면 둘 다 그 보너스를 받는 이중 계산이 된다."""
    sp = c.get("spec") or {}
    return sp.get("ability") == "supreme-overlord" or "last-respects" in (sp.get("moves") or [])


class TeamSearch:
    def __init__(self, cards, V, opp_ids, opp_teams, opp_weights):
        """cards: [{'id','key','item','mega','build',...}], V: (C, E) 행렬,
        opp_teams: [[열 인덱스 ×6]] (6마리 모두 알려진 팀만), opp_weights: (E,) 조우 가중치"""
        self.cards = cards
        self.V = np.asarray(V, dtype=np.float32)
        self.T = np.array(opp_teams, dtype=np.int64)          # (T,6)
        self.ow = np.asarray(opp_weights, dtype=np.float64)
        self.opp_ids = opp_ids
        self.cache = {}
        self._exact = {}
        self._mega_variants()

    def _mega_variants(self):
        """스톤 2개 이상인 상대 팀: 앞의 두 메가 칸 p, q 에 대해 'p 만 메가'(q 는 기본형), 'q 만 메가' 열 배열과
        상대 3마리 조합(20)마다 두 칸을 모두 포함하는지 표시. 기본형 개체가 없으면(스톤 채용률 100%) 그대로 둔다."""
        col = {e: i for i, e in enumerate(self.opp_ids)}
        T1, T2 = self.T.copy(), self.T.copy()
        both = np.zeros((len(self.T), len(TRI)), dtype=bool)
        for t, row in enumerate(self.T):
            megas = [p for p in range(6) if str(self.opp_ids[row[p]]).endswith("@mega")
                     and str(self.opp_ids[row[p]])[:-5] in col]
            if len(megas) < 2:
                continue
            p, q = megas[:2]
            T1[t, q] = col[str(self.opp_ids[row[q]])[:-5]]
            T2[t, p] = col[str(self.opp_ids[row[p]])[:-5]]
            both[t] = [(p in tri) and (q in tri) for tri in TRI]
        self.multi = both.any(axis=1)
        self.T1, self.T2, self.both = T1, T2, both

    def team_values(self, idx, exact=False):
        """상대 팀마다 선출 게임 값. exact=False 는 순수전략 하한·상한 평균(탐색용, 빠름),
        exact=True 는 20×20 행렬 게임의 혼합전략 균형값(최종 후보 재정렬용)."""
        Vi = self.V[np.array(idx)]
        M = Vi[:, self.T]                                     # (6, T, 6)
        alt = (Vi[:, self.T1], Vi[:, self.T2], self.both) if self.multi.any() else None
        approx, P = pick_values(M, alt)
        if not exact:
            return approx
        key = tuple(sorted(idx))
        if key not in self._exact:
            from .game import solve
            self._exact[key] = np.array([solve(P[:, t, :])[0] for t in range(P.shape[1])])
        return self._exact[key]

    def exact_score(self, idx):
        return float(self.team_values(list(idx), exact=True).mean())

    def score(self, idx):
        key = tuple(sorted(idx))
        s = self.cache.get(key)
        if s is None:
            s = float(self.team_values(list(key)).mean())
            self.cache[key] = s
        return s

    def gap(self, idx):
        """무답 노출: V ≥ 0 인 카드가 2장 미만인 상대 개체의 조우 가중치 합."""
        sub = self.V[np.array(idx)]
        answers = (sub >= 0).sum(axis=0)
        return float(self.ow[answers < 2].sum())

    def valid(self, idx):
        cs = [self.cards[i] for i in idx]
        if len({c["key"] for c in cs}) < len(cs):
            return False
        items = [c["item"] for c in cs if c["item"]]
        if len(set(items)) < len(items):
            return False
        if sum(_closer_card(c) for c in cs) > 1:
            return False                                   # 마무리 포켓몬은 한 팀에 하나 — 마지막은 한 마리뿐
        return sum(c["mega"] for c in cs) <= 1

    def search(self, must=(), restarts=4, seed=7, log=None):
        rnd = random.Random(seed)
        C = len(self.cards)
        must = [i for i in must]
        # 필수는 '종' 기준으로 지킨다. 도구 재배치(reassign_items)가 같은 종의 다른 카드로 바꾸면
        # 카드 번호가 달라지므로, 번호로 비교하면 그 뒤 한 장 바꾸기에서 필수 종이 빠질 수 있었다.
        must_keys = {self.cards[i]["key"] for i in must}
        results = {}
        for r in range(restarts):
            team = list(must)
            # 탐욕 시작(첫 회) 또는 무작위 시작
            order = list(range(C))
            rnd.shuffle(order)
            while len(team) < 6:
                best, bv = None, -9
                cand = order if r else range(C)
                for c in cand:
                    if c in team or not self.valid(team + [c]):
                        continue
                    if r and len(team) < 3 and best is not None:
                        break                                   # 무작위 시작은 앞 3칸을 섞인 순서대로
                    v = self.score(team + [c]) if len(team) == 5 else self._partial(team + [c])
                    if v > bv:
                        best, bv = c, v
                if best is None:
                    break
                team.append(best)
            if len(team) < 6:
                continue
            cur = self.score(team)
            while True:
                improved = True
                while improved:
                    improved = False
                    for pos in range(6):
                        if self.cards[team[pos]]["key"] in must_keys:
                            continue
                        for c in range(C):
                            if c in team:
                                continue
                            trial = team[:pos] + [c] + team[pos + 1:]
                            if not self.valid(trial):
                                continue
                            v = self.score(trial)
                            if v > cur + 1e-7:
                                team, cur, improved = trial, v, True
                # 한 장 바꾸기로는 못 가는 '두 마리 도구 맞바꾸기'(아이템 클로즈 충돌 해소): 같은 6종의 도구 변형 전부.
                # 바뀌면 그 팀에서 한 장 바꾸기를 다시 돈다(개선이 없을 때까지)
                t2, v2 = self.reassign_items(team)
                if v2 > cur + 1e-7:
                    team, cur = t2, v2
                    continue
                break
            results[tuple(sorted(team))] = cur
            if log:
                log(f"  재시작 {r + 1}/{restarts}: {cur:+.4f}")
        return sorted(results.items(), key=lambda x: -x[1])

    def reassign_items(self, team):
        """같은 6종을 유지하고, 종마다 가진 카드(메가·1순위 도구·2순위 도구) 조합을 전부 본다(최대 3^6)."""
        by_key = {}
        for i, c in enumerate(self.cards):
            by_key.setdefault(c["key"], []).append(i)
        options = [by_key[self.cards[i]["key"]] for i in team]
        best, bv = list(team), self.score(team)
        for combo in itertools.product(*options):
            combo = list(combo)
            if combo == team or not self.valid(combo):
                continue
            v = self.score(combo)
            if v > bv + 1e-7:
                best, bv = combo, v
        return best, bv

    def _partial(self, idx):
        """6마리 미만일 때의 대리 점수: 상대 개체마다 최선의 답 평균 + 최악 카운터 평균."""
        sub = self.V[np.array(idx)]
        return float((self.ow * (0.5 * sub.max(axis=0) + 0.5 * sub.mean(axis=0))).sum())

    def neighbors(self, team, k=10):
        """이 팀에서 한 장만 바꾼 팀 중 점수 상위 k (동률 집단 확인용)."""
        out = []
        for pos in range(6):
            for c in range(len(self.cards)):
                if c in team:
                    continue
                trial = team[:pos] + [c] + team[pos + 1:]
                if self.valid(trial):
                    out.append((tuple(sorted(trial)), self.score(trial)))
        return sorted(set(out), key=lambda x: -x[1])[:k]

    def paired_z(self, a, b):
        """팀 a − 팀 b 의 평균 차이 / 대응 표준오차 (같은 상대 팀 표본에서 비교)."""
        d = self.team_values(list(a), exact=True) - self.team_values(list(b), exact=True)
        se = d.std() / np.sqrt(len(d))
        return float(d.mean() / se) if se > 0 else float("inf") * np.sign(d.mean())

    def bootstrap(self, teams, n=1000, seed=20260923):
        """상대 팀 표본을 다시 뽑아 각 후보가 1위일 확률."""
        vals = np.stack([self.team_values(list(t), exact=True) for t in teams])   # (K, T)
        rng = np.random.default_rng(seed)
        Tn = vals.shape[1]
        wins = np.zeros(len(teams))
        for _ in range(n):
            s = rng.integers(0, Tn, Tn)
            wins[vals[:, s].mean(axis=1).argmax()] += 1
        se = vals.std(axis=1) / np.sqrt(Tn)
        return wins / n, se
