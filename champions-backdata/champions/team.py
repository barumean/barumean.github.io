"""팀 구성(6마리) 탐색과 선출 게임.

선출 게임: 서로 6마리를 보고 3마리씩 낸다. 내 3 (a) 대 상대 3 (b) 의 값
    P(a,b) = ½·mean_{j∈b} max_{i∈a} V[i,j]   (상대 한 마리마다 내가 가진 최선의 답)
           + ½·mean_{i∈a} min_{j∈b} V[i,j]   (내 한 마리마다 상대가 가진 최악의 카운터)
팀 대 팀 값 = (max_a min_b P + min_b max_a P) / 2   — 하한과 상한의 평균
팀 점수     = 레플리카 싱글 팀(실제 제출된 팀) 전체에 대한 평균

제약: 종 중복 없음, 도구 중복 없음(아이템 클로즈), 메가 스톤 1장 이하.
"""
import itertools
import random

import numpy as np

TRI = np.array(list(itertools.combinations(range(6), 3)))  # (20,3)


def pick_values(M):
    """M: (6, T, 6) 내 6 × 상대팀 T × 상대 6 → (T,) 팀 대 팀 값, 그리고 (20,20,T) P."""
    A = M[TRI]                                   # (20a, 3, T, 6)
    B = A[:, :, :, TRI]                          # (20a, 3, T, 20b, 3)
    ans = B.max(axis=1).mean(axis=-1)            # (20a, T, 20b)
    cnt = B.min(axis=-1).mean(axis=1)            # (20a, T, 20b)
    P = 0.5 * (ans + cnt)
    lower = P.min(axis=2).max(axis=0)            # (T,)
    upper = P.max(axis=0).min(axis=1)            # (T,)
    return 0.5 * (lower + upper), P


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

    def team_values(self, idx, exact=False):
        """상대 팀마다 선출 게임 값. exact=False 는 순수전략 하한·상한 평균(탐색용, 빠름),
        exact=True 는 20×20 행렬 게임의 혼합전략 균형값(최종 후보 재정렬용)."""
        M = self.V[np.array(idx)][:, self.T]                  # (6, T, 6)
        approx, P = pick_values(M)
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
        return sum(c["mega"] for c in cs) <= 1

    def search(self, must=(), restarts=4, seed=7, log=None):
        rnd = random.Random(seed)
        C = len(self.cards)
        must = [i for i in must]
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
                        if team[pos] in must:
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
