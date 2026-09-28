"""Phase 6 — property 테스트. 성질이 깨지면 실패한다(현재 코드에서 실패하는 것은 결함 기록이다 — 보고서 참고).

실행:  python -m unittest tests.test_phase6_properties -v      (프로젝트 루트에서)
       python tests/test_phase6_properties.py
허용 오차 TOL = 1e-6. 무작위 입력은 numpy default_rng(고정 seed).
"""
import itertools
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import TOL, residuals, ok, bayes_residuals, bayes_ok  # noqa: E402
from champions.game import solve, solve_bayes  # noqa: E402
from champions.pick import _pick_matrix, stone_sets, mega_scenarios, scenario_pick_matrices  # noqa: E402
from champions.team import TRI, pick_values  # noqa: E402

TRIS = [tuple(t) for t in TRI]


def P_of(V):
    return _pick_matrix(np.asarray(V, float), TRIS, TRIS)


class Formula(unittest.TestCase):
    """합산식·solver·사전분포 — 합성 데이터(빠름)."""

    def test_perspective_consistency_formula(self):
        rng = np.random.default_rng(1)
        for _ in range(50):
            V = rng.uniform(-1, 1, (6, 6))
            self.assertLess(np.abs(P_of(-V.T) + P_of(V).T).max(), 1e-12)

    def test_symmetric_data_value_zero(self):
        """같은 6마리끼리(V 반대칭) → P 반대칭 → 게임 값 0, 양쪽 전략이 같다."""
        rng = np.random.default_rng(2)
        for _ in range(30):
            U = rng.uniform(-1, 1, (6, 6)); V = U - U.T
            P = P_of(V)
            self.assertLess(np.abs(P + P.T).max(), 1e-12)
            v, x, y = solve(P)
            self.assertAlmostEqual(v, 0.0, delta=TOL)

    def test_probability_normalization(self):
        rng = np.random.default_rng(3)
        for _ in range(100):
            pm = [float(p) if rng.random() < 0.5 else 0.0 for p in rng.uniform(0, 1, 6)]
            K = list(rng.dirichlet(np.ones(3)))
            sc = stone_sets(pm, K)
            self.assertAlmostEqual(sum(p for p, _ in sc), 1.0, delta=1e-9)
            self.assertTrue(all(p >= 0 for p, _ in sc))
            self.assertTrue(all(len(S) <= 2 for _, S in sc))
        for _ in range(30):
            P = P_of(rng.uniform(-1, 1, (6, 6)))
            v, x, y = solve(P)
            self.assertAlmostEqual(x.sum(), 1, delta=TOL); self.assertAlmostEqual(y.sum(), 1, delta=TOL)
            self.assertGreater(x.min(), -TOL); self.assertGreater(y.min(), -TOL)

    def test_equilibrium_exploitability_zero(self):
        rng = np.random.default_rng(4)
        for _ in range(30):
            Vb = rng.uniform(-1, 1, (6, 6)); Vm = np.full((6, 6), np.nan)
            for j in rng.choice(6, 3, replace=False):
                Vm[:, j] = np.clip(Vb[:, j] - rng.uniform(0, .5, 6), -1, 1)
            opp = [(str(j), [(None, 1.0)]) for j in range(6)]
            pm = [0.6 if not np.isnan(Vm[:, j]).any() else 0 for j in range(6)]
            scen, Vc = mega_scenarios(opp, Vb, Vm, (0.08, 0.16, 0.76), None, pm)
            Ps = scenario_pick_matrices(scen, Vc, TRIS, TRIS)
            probs = [p for p, _ in scen]
            v, x, yd = solve_bayes(Ps, probs)
            self.assertTrue(bayes_ok(bayes_residuals(Ps, probs, v, x, yd)))
            v1, x1, y1 = solve(Ps[0])
            self.assertTrue(ok(residuals(Ps[0], v1, x1, y1)))

    def test_strictly_dominated_zero(self):
        rng = np.random.default_rng(5)
        for _ in range(30):
            P = P_of(rng.uniform(-1, 1, (6, 6)))
            Pd = np.vstack([P, P.min(axis=0) - 0.05])       # 모든 열에서 기존 어떤 행보다 작다 → 강지배
            v, x, y = solve(Pd)
            self.assertLess(x[-1], TOL)
            Pc = np.hstack([P, P.max(axis=1, keepdims=True) + 0.05])   # 최소화 쪽 강지배 열
            v, x, y = solve(Pc)
            self.assertLess(y[-1], TOL)

    def test_duplicate_strategy_invariance(self):
        rng = np.random.default_rng(6)
        for _ in range(30):
            P = P_of(rng.uniform(-1, 1, (6, 6)))
            v = solve(P)[0]
            i, j = rng.integers(20), rng.integers(20)
            self.assertAlmostEqual(solve(np.vstack([P, P[i]]))[0], v, delta=TOL)
            self.assertAlmostEqual(solve(np.hstack([P, P[:, [j]]]))[0], v, delta=TOL)

    def test_pokemon_order_permutation_invariance(self):
        """내 6마리·상대 6마리 순서를 바꿔도 게임 값이 같고, 추천 조합(원래 번호의 집합)이 같다."""
        rng = np.random.default_rng(7)
        for _ in range(30):
            V = rng.uniform(-1, 1, (6, 6))
            pr, pc = rng.permutation(6), rng.permutation(6)
            v, x, _ = solve(P_of(V))
            v2, x2, _ = solve(P_of(V[pr][:, pc]))
            self.assertAlmostEqual(v, v2, delta=TOL)
            best = set(TRIS[int(np.argmax(x))])
            best2 = {int(pr[i]) for i in TRIS[int(np.argmax(x2))]}
            if np.sort(x)[-1] - np.sort(x)[-2] > 1e-6:
                self.assertEqual(best, best2)

    def test_team_search_value_permutation(self):
        """팀 탐색 근사값(pick_values)도 순서에 무관."""
        rng = np.random.default_rng(8)
        M = rng.uniform(-1, 1, (6, 5, 6)).astype(np.float32)
        a, _ = pick_values(M)
        b, _ = pick_values(M[rng.permutation(6)][:, :, rng.permutation(6)])
        np.testing.assert_allclose(a, b, atol=1e-6)


class Engine(unittest.TestCase):
    """실데이터·엔진(수십 초). 반대칭이 깨지는 알려진 경우는 결함 기록으로 남긴다."""

    @classmethod
    def setUpClass(cls):
        from _fixtures import data, party, clean, top_opponents
        cls.D = data()
        cls.mine = party(cls.D)
        cls.opps = {e: clean(b) for e, b, _ in top_opponents(cls.D, 100)}
        cls.clean = staticmethod(clean)

    def _anti(self, A, B, **kw):
        from champions.engine import duel
        return duel(A, B, **kw) + duel(B, A, **kw)

    def test_1v1_antisymmetry_random_sample(self):
        """무작위 60쌍(seed 20260927) — 대부분(0.7% 제외)은 반대칭."""
        import random
        keys = sorted(self.opps)
        rnd = random.Random(20260927)
        bad = []
        for _ in range(60):
            a, b = rnd.sample(keys, 2)
            s = self._anti(self.opps[a], self.opps[b])
            if abs(s) > 1e-9:
                bad.append((a, b, s))
        self.assertEqual(bad, [])

    def test_1v1_antisymmetry_known_speed_tie(self):
        """결함 기록: 스피드 동률 쌍(분기 모드의 동률 갈래 1회 뒤 '번갈아' 규칙이 라벨 A 기준)."""
        self.assertAlmostEqual(self._anti(self.opps["archaludon"], self.opps["ceruledge"]), 0.0, delta=1e-9)

    def test_1v1_antisymmetry_known_end_of_turn(self):
        """결함 기록: 턴 종료 처리 순서가 라벨 A 먼저(모래바람 피해 ↔ 씨뿌리기 회복의 HP 상한)."""
        self.assertAlmostEqual(self._anti(self.opps["venusaur@mega"], self.opps["tyranitar@mega"], branch=False), 0.0, delta=1e-9)

    def test_mirror_value_zero(self):
        """같은 세트끼리(자기 자신과) 1:1 값은 0 이어야 한다."""
        from champions.engine import value
        bad = [(b.key, value(b, self.clean(b))) for b in self.mine if abs(value(b, self.clean(b))) > 1e-9]
        self.assertEqual(bad, [])

    def test_3v3_perspective_engine(self):
        """같은 엔진으로 두 방향을 따로 계산해도 P_opp = −P_meᵀ (유형 없는 대표 세트)."""
        from _fixtures import sample_teams
        from champions.engine import value
        errs = []
        for ti, keys, ob, st in sample_teams(self.D, 3, exclude_keys=[b.key for b in self.mine]):
            oc = [self.clean(b) for b in ob]
            V = np.array([[value(a, b) for b in oc] for a in self.mine])
            Vo = np.array([[value(b, a) for a in self.mine] for b in oc])
            errs.append(np.abs(P_of(Vo) + P_of(V).T).max())
        self.assertLess(max(errs), 1e-9)

    def test_symmetric_data_engine_value_zero(self):
        """내 파티 대 내 파티(같은 세트) → 게임 값 0."""
        from champions.engine import value
        other = [self.clean(b) for b in self.mine]
        V = np.array([[value(a, b) for b in other] for a in self.mine])
        self.assertAlmostEqual(solve(P_of(V))[0], 0.0, delta=TOL)

    def test_advise_permutation_invariance(self):
        """pick.advise: 내 파티·상대 순서를 바꿔도 게임 값과 추천 조합(세트 기준)이 같다."""
        from _fixtures import sample_teams
        from champions.pick import advise
        ti, keys, ob, st = sample_teams(self.D, 1, exclude_keys=[b.key for b in self.mine])[0]
        r1 = advise(self.D, self.mine, keys)
        pr, pc = [3, 0, 5, 1, 4, 2], [2, 5, 0, 4, 1, 3]
        r2 = advise(self.D, [self.mine[i] for i in pr], [keys[j] for j in pc])
        self.assertAlmostEqual(r1["best_value"], r2["best_value"], delta=TOL)   # solve_bayes 의 수렴 허용폭 1e-9 보다 느슨하게
        self.assertEqual({self.mine[i].key for i in r1["best"]}, {self.mine[pr[i]].key for i in r2["best"]})
        self.assertAlmostEqual(sum(r1["their_freq"]), 1.0, delta=1e-9)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], "-v"])
