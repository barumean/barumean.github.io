"""실데이터 고정물: 수집 데이터(data/raw 최신), 고정 파티(tests/fixtures/party_20260927.txt), 레플리카 팀 표본.
champions/ 는 읽기만 한다(pipeline 캐시를 읽거나 쓰지 않는다 — 파티 세트는 파일의 전체 스펙으로 만든다)."""
import os
import random

import _common  # noqa: F401  (sys.path 설정)
from champions.data import load
from champions.engine import Build, usable
from champions.meta import modal_build, opponents, stones_of
from champions.textio import parse_party

HERE = os.path.dirname(os.path.abspath(__file__))
PARTY_FILE = os.path.join(HERE, "fixtures", "party_20260927.txt")
SEED = 20260927


def data():
    return load()


def party(D):
    ps = parse_party(D, open(PARTY_FILE, encoding="utf-8-sig").read())
    return [Build(D, m["key"], m["moves"], m["item"], m["ability"], m["nature"], m["sp"]) for m in ps]


def clean(b):
    """유형(역할 변형·alt) 없이 대표 세트만 — 1:1 엔진의 반대칭 검사용."""
    return Build(b.D, **b.spec())


def top_opponents(D, n):
    return [(e, b, w) for e, b, w in opponents(D)[:n]]


def replica_team(D, t, mega_rule="first"):
    """레플리카 팀 1개 → (키 6개, 대표 세트 6개, 스톤 든 슬롯 목록).
    mega_rule='first': 스톤 든 슬롯 중 첫 번째만 메가형 대표 세트(배틀당 메가 1회를 고정된 알려진 선택으로 단순화)."""
    keys, stone_slots = [], []
    for s in t["slots"]:
        k = s["pokemon"]
        if k not in D.DEX:
            return None
        base = D.base_of(k)
        keys.append(base)
        it = s.get("item")
        if (it in D.STONE and D.DEX[D.STONE[it]]["base_key"] == base) or D.DEX[k]["base_key"] is not None:
            stone_slots.append(len(keys) - 1)
    if len(keys) != 6 or len(set(keys)) != 6:
        return None
    builds = []
    mega_slot = stone_slots[0] if (stone_slots and mega_rule == "first") else None
    for j, k in enumerate(keys):
        b = modal_build(D, k, j == mega_slot) if j == mega_slot and stones_of(D, k) else modal_build(D, k, False)
        if b is None or not usable(b):
            return None
        builds.append(b)
    return keys, builds, stone_slots


def sample_teams(D, n, seed=SEED, exclude_keys=()):
    rng = random.Random(seed)
    idx = list(range(len(D.TEAMS)))
    rng.shuffle(idx)
    out = []
    for i in idx:
        r = replica_team(D, D.TEAMS[i])
        if r is None:
            continue
        if set(r[0]) & set(exclude_keys):
            continue
        out.append((i,) + r)
        if len(out) == n:
            break
    return out
