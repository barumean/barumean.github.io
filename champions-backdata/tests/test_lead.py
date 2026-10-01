"""선출 + 선봉 60전략 게임(champions/lead.py)과 3:3 순차 평가(champions/seq3.py) 검사.

실행:  python -m unittest tests.test_lead -v      (프로젝트 루트에서, 1~2분)
데이터: 최신 수집본, 고정 파티 tests/fixtures/party_20260927.txt, 레플리카 팀 표본(seed SEED+2).
"""
import os
import random
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fixtures import data, party, clean, sample_teams, SEED  # noqa: E402
from champions.game import solve, solve_bayes  # noqa: E402
from champions.lead import LeadGame, TRI  # noqa: E402
from champions.meta import modal_build, stones_of  # noqa: E402
from champions.seq3 import Seq  # noqa: E402

D = data()
MINE = party(D)
TEAMS = sample_teams(D, 2, seed=SEED + 2, exclude_keys=[b.key for b in MINE])
OPP = [clean(b) for b in TEAMS[0][2]]
FLIP = {"A": "B", "B": "A", None: None}


class SeqTest(unittest.TestCase):

    def test_antisymmetry(self):
        """내 입장 값 = −상대 입장 값(교체 등장 시작 포함). 엔진이 반대칭이므로 순차 평가도 정확히 반대칭이어야 한다."""
        s1, s2 = Seq(MINE, OPP), Seq(OPP, MINE)
        rng = random.Random(1)
        for _ in range(30):
            ta, tb, la, lb = rng.choice(TRI), rng.choice(TRI), rng.randrange(3), rng.randrange(3)
            pre = rng.choice([None, "A", "B"])
            self.assertAlmostEqual(s1.battle(ta, tb, la, lb, pre), -s2.battle(tb, ta, lb, la, FLIP[pre]), delta=1e-9)

    def test_matches_model_b(self):
        """상태 캐시 순차 평가 ≈ 경로 캐시 Model B(tests/model_b.py). 다른 점은 경기 중 스피드 동률을 50:50 으로 나누고,
        기절 교대 판정에 필드의 벽을 넣는 것뿐이라 칸 평균 차이가 작아야 한다."""
        from model_b import DetCtx, battle_det
        s = Seq(MINE, OPP)
        rng = random.Random(2)
        cells = [(rng.choice(TRI), rng.choice(TRI), rng.randrange(3), rng.randrange(3)) for _ in range(30)]
        ctx = DetCtx(MINE, OPP)
        with ctx.env:
            ref = [battle_det(ctx, ta, tb, la, lb)[0] for ta, tb, la, lb in cells]
        got = [s.battle(ta, tb, la, lb) for ta, tb, la, lb in cells]
        self.assertLess(float(np.mean(np.abs(np.array(got) - np.array(ref)))), 0.05)


class LeadGameTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.g = LeadGame(MINE, OPP)
        cls.P = cls.g.matrix(None)

    def test_double_oracle_equals_full(self):
        """필요한 조합 쌍만 계산하는 이중 오라클의 균형값·보장값 최고 수 = 60×60 전체를 푼 결과."""
        r = self.g.solve([(1.0, ())])
        self.assertAlmostEqual(r["value"], solve(self.P)[0], delta=1e-6)
        a, i = r["safe"]
        self.assertAlmostEqual(self.P[3 * a + i].min(), self.P.min(axis=1).max(), delta=1e-9)
        x = np.zeros(60)
        for (a, i), w in r["x"].items():
            x[3 * a + i] = w
        self.assertGreater((x @ self.P).min(), solve(self.P)[0] - 1e-6)     # 균형 혼합의 보장값 = 게임 값

    def test_lead_turn_switch(self):
        """선봉 턴 게임: 교체 선택지를 주면 값이 '둘 다 그대로'와 달라지는 칸이 있고, 양쪽 혼합은 확률 분포다."""
        changed = 0
        for a in range(0, 20, 5):
            for b in range(0, 20, 5):
                M = self.g._block(TRI[a], TRI[b])[0]
                for i in range(3):
                    for j in range(3):
                        v, x, y, ks, ls = self.g.sub(TRI[a], TRI[b], i, j)
                        changed += abs(v - M[i, j]) > 1e-6
                        self.assertAlmostEqual(x.sum(), 1, delta=1e-9)
                        self.assertAlmostEqual(y.sum(), 1, delta=1e-9)
        self.assertGreater(changed, 0)

    def test_bayes_mega_scenarios(self):
        """상대 메가(스톤 조합)를 유형으로 둔 베이지안 게임: 이중 오라클 = 전체 행렬로 푼 값."""
        c, mb = None, None
        for j, b in enumerate(TEAMS[0][2]):
            if stones_of(D, b.key) and not b.mega:
                mb = modal_build(D, b.key, True)
                if mb is not None:
                    c = j
                    break
        if c is None:
            self.skipTest("표본 팀에 스톤을 들 수 있는 기본형이 없음")
        g = LeadGame(MINE, OPP, {c: clean(mb)})
        scen = [(0.4, ()), (0.6, (c,))]
        r = g.solve(scen)
        P0, Pc = g.matrix(None), g.matrix(c)
        Ps = [P0, P0.copy()]
        for bi, b in enumerate(TRI):
            if c in b:
                Ps[1][:, 3 * bi:3 * bi + 3] = Pc[:, 3 * bi:3 * bi + 3]
        self.assertAlmostEqual(r["value"], solve_bayes(Ps, [0.4, 0.6])[0], delta=1e-6)


if __name__ == "__main__":
    unittest.main()
