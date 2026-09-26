"""수집 원본(data/raw/<날짜>) → 분석용 메모리 구조.

DEX[key]      도감(메가 폼 포함): name, types, abilities, stats(H A B C D S), learnset, base_key, item
MOVES[key]    기술: type, cat(physical/special/status), power, acc, priority, target, meta, stat_changes, traits
ITEMS[key]    아이템 이름
USAGE[key]    op.gg 싱글 통계: moves/items/abilities/natures/training/teammates/win/lose
TIER          싱글 순위 [{rank,key,name}]
TEAMS         레플리카 싱글 팀 [[slot…]]
"""
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

STAT_ORDER = ("hp", "attack", "defense", "spAttack", "spDefense", "speed")


def latest_dir():
    days = sorted(p for p in RAW.iterdir() if p.is_dir() and p.name[:2] == "20" and (p / "dex.json").exists())
    if not days:
        raise SystemExit("수집 데이터가 없습니다. 먼저 `python -m champions scrape` 를 실행하세요.")
    return days[-1]


class Data:
    def __init__(self, day_dir=None):
        d = Path(day_dir) if day_dir else latest_dir()
        self.dir = d
        dex = json.loads((d / "dex.json").read_text(encoding="utf-8"))
        self.DEX = {}
        for p in dex["pokemon"]:
            self.DEX[p["key"]] = {
                "key": p["key"], "name": p["name"], "types": p["types"], "abilities": p["abilities"],
                "stats": [p["stats"][k] for k in STAT_ORDER], "learnset": set(p.get("moves") or []),
                "base_key": p.get("base_key") if p.get("base_key") not in (None, "$undefined") else None,
                "item": p.get("item") if p.get("item") not in (None, "$undefined") else None,
            }
        self.MOVES = {}
        for m in dex["moves"]:
            meta = m.get("meta") or {}
            self.MOVES[m["key"]] = {
                "key": m["key"], "name": m["name"], "type": m["type"], "cat": m["category"],
                "power": m.get("power") or 0, "acc": m.get("accuracy"), "priority": m.get("priority") or 0,
                "pp": m.get("pp") or 8,
                "target": m.get("target"), "meta": meta, "stat_changes": m.get("statChanges") or [],
                "traits": set(m.get("moveTraits") or []), "available": bool(m.get("isAvailable")),
            }
        # 부가효과 확률은 게임 설명문을 우선한다(op.gg 기술 메타가 본가 수치인 기술이 있다: 문포스 30→10%,
        # 아이언헤드 30→20%, 셸암즈 20→10%). 설명문에 확률이 하나만 있을 때만 바꾼다.
        self.CHANCE_FIX = {}
        for m in dex["moves"]:
            mm = self.MOVES.get(m["key"])
            ps = set(int(x) for x in re.findall(r"(\d+)\s*%", m.get("description") or ""))
            if not mm or len(ps) != 1:
                continue
            p = ps.pop()
            for c in ("ailmentChance", "flinchChance", "statChance"):
                v = mm["meta"].get(c)
                if v and 0 < v < 100 and v != p:
                    mm["meta"] = dict(mm["meta"], **{c: p})
                    self.CHANCE_FIX[m["key"]] = (c, v, p)
        self.ITEMS = {i["key"]: i["name"] for i in dex["items"]}
        self.ABILITIES = {k: a["name"] for k, a in (dex.get("abilities") or {}).items()}
        # 메가: 스톤 → 메가 폼, 기본 폼 → [메가 폼…]
        self.STONE = {}
        self.MEGAS = {}
        for k, p in self.DEX.items():
            if p["base_key"] and p["item"]:
                self.STONE[p["item"]] = k
                self.MEGAS.setdefault(p["base_key"], []).append(k)
        self.USAGE = {}
        for f in (d / "pokemon").glob("*.json"):
            u = json.loads(f.read_text(encoding="utf-8"))
            self.USAGE[u["key"]] = u
        tier = json.loads((d / "tier.json").read_text(encoding="utf-8"))
        self.SEASON = tier["season"]
        self.TIER = tier["formats"]["single"]
        self.RANK = {r["key"]: r["rank"] for r in self.TIER}
        # 외형 변형(암컷 모습 등, 능력치·타입·특성이 같은 것)은 기본 종으로 합친다 — 메가진화·종 중복 판정이 룰대로.
        # 돌핀맨 마이티폼은 한 번 교체해야 되는 폼이라 1:1 은 제로폼으로 시작한다.
        self.CANON = {"palafin-hero": "palafin"} if "palafin" in self.DEX else {}
        for k, p in self.DEX.items():
            if k.endswith("-female"):
                b = self.DEX.get(k[:-len("-female")])
                if b and b["stats"] == p["stats"] and b["types"] == p["types"] and b["abilities"] == p["abilities"]:
                    self.CANON[k] = b["key"]
        teams = json.loads((d / "replica_teams.json").read_text(encoding="utf-8"))
        for t in teams:
            for sl in t.get("slots") or []:
                sl["pokemon"] = self.CANON.get(sl["pokemon"], sl["pokemon"])
        # 같은 팀을 여러 번 올린 경우(복사·재업로드)는 한 번만 센다 — 조우 가중치와 부트스트랩이 한 팀에 끌려가지 않게
        seen, self.TEAMS = set(), []
        for t in teams:
            if t["format"] != "SINGLE" or len(t["slots"]) != 6:
                continue
            sig = tuple(sorted((s["pokemon"], s.get("item") or "", s.get("nature") or "",
                                tuple(sorted(s.get("moves") or []))) for s in t["slots"]))
            if sig in seen:
                continue
            seen.add(sig)
            self.TEAMS.append(t)
        self.TEAMS_RAW = sum(1 for t in teams if t["format"] == "SINGLE" and len(t["slots"]) == 6)
        # 한글 이름 → 키
        self.BY_NAME = {}
        for k, p in self.DEX.items():
            self.BY_NAME.setdefault(p["name"].replace(" ", ""), k)
        # 괄호 뗀 별칭: '킬가르도' → 실드폼, '대쓰여너' → 수컷. 싱글 순위가 높은(=실제로 쓰는) 폼을 우선
        for k in sorted(self.DEX, key=lambda k: self.RANK.get(k, 9999)):
            short = re.sub(r"\(.*?\)", "", self.DEX[k]["name"]).replace(" ", "")
            if short and not self.DEX[k]["base_key"] and k != "aegislash-blade":
                self.BY_NAME.setdefault(short, k)
        for k, n in self.ITEMS.items():
            self.BY_NAME.setdefault("item:" + n.replace(" ", ""), k)
        for k, m in self.MOVES.items():
            self.BY_NAME.setdefault("move:" + m["name"].replace(" ", ""), k)

    # ── 이름 해석 ───────────────────────────────────────────────
    def mon(self, s):
        k = self._mon(s)
        return self.CANON.get(k, k)

    def _mon(self, s):
        s = s.strip()
        if s in self.DEX:
            return s
        k = self.BY_NAME.get(s.replace(" ", ""))
        if k:
            return k
        low = s.lower().replace(" ", "-")
        if low in self.DEX:
            return low
        cand = [k for k, p in self.DEX.items() if s.replace(" ", "") in p["name"].replace(" ", "")]
        if len(cand) == 1:
            return cand[0]
        raise KeyError(f"포켓몬을 찾을 수 없음: {s}" + (f" (후보: {', '.join(self.DEX[c]['name'] for c in cand[:8])})" if cand else ""))

    def move(self, s):
        s = s.strip()
        if s in self.MOVES:
            return s
        k = self.BY_NAME.get("move:" + s.replace(" ", "")) or (s.lower().replace(" ", "-") if s.lower().replace(" ", "-") in self.MOVES else None)
        if not k:
            raise KeyError(f"기술을 찾을 수 없음: {s}")
        return k

    def item(self, s):
        s = s.strip()
        if s in self.ITEMS:
            return s
        k = self.BY_NAME.get("item:" + s.replace(" ", "")) or (s.lower().replace(" ", "-") if s.lower().replace(" ", "-") in self.ITEMS else None)
        if not k:
            raise KeyError(f"아이템을 찾을 수 없음: {s}")
        return k

    def name(self, key):
        return self.DEX[key]["name"] if key in self.DEX else key

    def move_name(self, key):
        return self.MOVES[key]["name"] if key in self.MOVES else key

    def ability_name(self, key):
        return self.ABILITIES.get(key, key or "없음")

    def ability(self, s):
        """한글·영문 특성 이름 → 키."""
        s = s.strip()
        k = s.lower().replace(" ", "-")
        if k in self.ABILITIES:
            return k
        for kk, n in self.ABILITIES.items():
            if n.replace(" ", "") == s.replace(" ", ""):
                return kk
        raise KeyError(f"특성을 찾을 수 없음: {s}")

    def item_name(self, key):
        return self.ITEMS.get(key, key or "없음")

    def base_of(self, key):
        return self.DEX[key]["base_key"] or key

    def usage_pct(self, key, field, name):
        for n, v in (self.USAGE.get(key, {}).get(field) or []):
            if n == name:
                return v
        return 0.0


@lru_cache(maxsize=1)
def load():
    return Data()
