"""무거운 계산을 캐시와 함께 묶는다.  data/processed/<수집일>/

sets.json    풀 포켓몬별 최적 세트(메가형·비메가형)
matrix.npz   카드 × 상대 개체 상성 행렬
"""
import json
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .data import ROOT, load
from .engine import Build
from .matrix import compute
from .meta import opponents, stones_of, team_entities, entity_id


def pdir(D):
    d = ROOT / "data" / "processed" / D.dir.name
    d.mkdir(parents=True, exist_ok=True)
    return d


def pool_keys(D, n=None):
    """팀 후보 풀. n=None 이면 싱글 순위 전 종(op.gg 통계가 있는 것)."""
    ks = [r["key"] for r in D.TIER if r["key"] in D.USAGE and r["key"] in D.DEX]
    return ks if n is None else ks[:n]


# ── 세트 최적화 (병렬) ───────────────────────────────────────────
_E = {}


def _res_json(r):
    return {"spec": r["build"].spec(), "arch": r.get("arch"), "arch_scores": r.get("arch_scores", {}),
            "score": r["score"], "real_score": r["real_score"],
            "real_top4": r["real_top4"], "moves": r["moves"], "items": r["items"]}


def _opt_worker(key):
    from .sets import optimize, Evaluator
    D = load()
    if "ev" not in _E:
        _E["ev"] = Evaluator(opponents(D))
    ev = _E["ev"]
    out = {"base": _res_json(optimize(D, key, ev, mega=False))}
    if stones_of(D, key):
        out["mega"] = _res_json(optimize(D, key, ev, mega=True))
    return key, out


def party_worker(args):
    """(key, optimize 키워드) → (key, mega, 결과). moves 명령의 병렬 작업용."""
    from .sets import optimize, Evaluator
    D = load()
    if "ev" not in _E:
        _E["ev"] = Evaluator(opponents(D))
    key, kw = args
    return key, kw.get("mega"), _res_json(optimize(D, key, _E["ev"], **kw))


def optimize_pool(D, keys, workers=None, log=print):
    f = pdir(D) / "sets.json"
    cache = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    todo = [k for k in keys if k not in cache]
    if todo:
        log(f"[sets] {len(todo)}종 세트 최적화 (병렬 {workers or max(1, (os.cpu_count() or 2) - 1)})…")
        with ProcessPoolExecutor(workers or max(1, (os.cpu_count() or 2) - 1)) as ex:
            for n, (k, r) in enumerate(ex.map(_opt_worker, todo), 1):
                cache[k] = r
                if n % 10 == 0 or n == len(todo):
                    log(f"  {n}/{len(todo)}")
                    f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {k: cache[k] for k in keys if k in cache}


def best_set(D, key, mega=None):
    """캐시에 있으면 최적 세트, 없으면 None."""
    f = pdir(D) / "sets.json"
    if not f.exists():
        return None
    c = json.loads(f.read_text(encoding="utf-8")).get(key)
    if not c:
        return None
    if mega is None:
        r = max(c.values(), key=lambda x: x["score"])
    else:
        r = c.get("mega" if mega else "base")
    return r


# ── 카드와 행렬 ──────────────────────────────────────────────────

def make_cards(D, sets):
    """포켓몬마다: 메가 카드 1장 + 비메가 카드(1순위 도구, 2순위 도구) — 아이템 중복 회피용."""
    cards = []
    for k, r in sets.items():
        if "mega" in r:
            s = r["mega"]["spec"]
            cards.append({"id": f"{k}@mega", "key": k, "item": s["item"], "mega": True, "spec": s, "score": r["mega"]["score"]})
        b = r["base"]
        s = b["spec"]
        cards.append({"id": f"{k}#{s['item']}", "key": k, "item": s["item"], "mega": False, "spec": s, "score": b["score"]})
        from .sets import item_moves_ok
        alts = [it for it, v in b["items"] if it != s["item"] and item_moves_ok(D, it, s["moves"])]
        if alts:
            s2 = dict(s, item=alts[0])
            v2 = dict(b["items"]).get(alts[0], b["score"])
            cards.append({"id": f"{k}#{alts[0]}", "key": k, "item": alts[0], "mega": False, "spec": s2, "score": v2})
    return cards


def opponent_space(D):
    """상대 개체 목록·가중치, 레플리카 팀(개체 인덱스 6개) 목록."""
    opps = opponents(D)
    ids = [e for e, _, _ in opps]
    col = {e: i for i, e in enumerate(ids)}
    teams = []
    for t in D.TEAMS:
        ents = [entity_id(k, m) for k, m in team_entities(D, t)]
        # 개체가 없으면(예: 스톤 든 비메가 개체) 반대 형태로 대체
        idx = []
        for e in ents:
            if e in col:
                idx.append(col[e])
            elif e.replace("@mega", "") in col:
                idx.append(col[e.replace("@mega", "")])
        if len(idx) == 6:
            teams.append(idx)
    return opps, ids, teams


def card_matrix(D, cards, opps, workers=None, log=print):
    f = pdir(D) / "matrix.npz"
    cid = [c["id"] for c in cards]
    oid = [e for e, _, _ in opps]
    if f.exists():
        z = np.load(f, allow_pickle=True)
        old_c, old_o, V = list(z["cards"]), list(z["opps"]), z["V"]
        if old_o == oid:
            have = {c: i for i, c in enumerate(old_c)}
            miss = [c for c in cards if c["id"] not in have]
            if not miss:
                return V[[have[c] for c in cid]]
            log(f"[matrix] 카드 {len(miss)}장 추가 계산…")
            rows = compute([Build(D, **c["spec"]) for c in miss], [b for _, b, _ in opps], workers)
            V = np.vstack([V, np.array(rows, dtype=np.float32)])
            old_c += [c["id"] for c in miss]
            np.savez_compressed(f, cards=np.array(old_c, dtype=object), opps=np.array(oid, dtype=object), V=V)
            have = {c: i for i, c in enumerate(old_c)}
            return V[[have[c] for c in cid]]
    log(f"[matrix] {len(cards)} × {len(opps)} 상성 계산…")
    V = np.array(compute([Build(D, **c["spec"]) for c in cards], [b for _, b, _ in opps], workers), dtype=np.float32)
    np.savez_compressed(f, cards=np.array(cid, dtype=object), opps=np.array(oid, dtype=object), V=V)
    return V
