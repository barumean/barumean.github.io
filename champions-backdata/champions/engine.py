"""1:1 전투 엔진 — 레벨 50 싱글, 포켓몬 챔피언스 규칙.

능력치    HP = 종족값 + 75 + SP,  나머지 = ⌊(종족값 + 20 + SP) × 성격⌋   (SP 0~32, 합 66 · 개체값 31 가정)
데미지    ⌊⌊22·위력·A/D⌋/50⌋+2 × 날씨 × 필드 × 자속 × 상성 × 특성 × 도구 × 평균 난수(0.925)
턴 처리   우선도 → 스피드(랭크·스카프·마비·특성) → 행동 → 턴 종료(날씨·도구·상태이상)

전투 하나는 "계획"(그냥 때리기 / 쌓기 k회 후 때리기 / 상태이상 먼저) 쌍마다 끝까지 돌리고,
두 쪽의 보장값(maximin)을 평균해 값 v ∈ [-1, 1] 을 낸다. 이기면 +0.5 + 0.5×남은HP비율.

모델 밖: 교체, 급소, 명중 분산(기대 피해로 처리), 방어, 압정/스텔스록, 도발·앵콜, 트릭룸.
"""
import math

from .scrape import NATURES

TYPES = ["normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison", "ground",
         "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark", "steel", "fairy"]
_SE = {  # 공격 타입 → {방어 타입: 배율}
    "normal": {"rock": .5, "ghost": 0, "steel": .5},
    "fire": {"fire": .5, "water": .5, "grass": 2, "ice": 2, "bug": 2, "rock": .5, "dragon": .5, "steel": 2},
    "water": {"fire": 2, "water": .5, "grass": .5, "ground": 2, "rock": 2, "dragon": .5},
    "electric": {"water": 2, "electric": .5, "grass": .5, "ground": 0, "flying": 2, "dragon": .5},
    "grass": {"fire": .5, "water": 2, "grass": .5, "poison": .5, "ground": 2, "flying": .5, "bug": .5, "rock": 2, "dragon": .5, "steel": .5},
    "ice": {"fire": .5, "water": .5, "grass": 2, "ice": .5, "ground": 2, "flying": 2, "dragon": 2, "steel": .5},
    "fighting": {"normal": 2, "ice": 2, "poison": .5, "flying": .5, "psychic": .5, "bug": .5, "rock": 2, "ghost": 0, "dark": 2, "steel": 2, "fairy": .5},
    "poison": {"grass": 2, "poison": .5, "ground": .5, "rock": .5, "ghost": .5, "steel": 0, "fairy": 2},
    "ground": {"fire": 2, "electric": 2, "grass": .5, "poison": 2, "flying": 0, "bug": .5, "rock": 2, "steel": 2},
    "flying": {"electric": .5, "grass": 2, "fighting": 2, "bug": 2, "rock": .5, "steel": .5},
    "psychic": {"fighting": 2, "poison": 2, "psychic": .5, "dark": 0, "steel": .5},
    "bug": {"fire": .5, "grass": 2, "fighting": .5, "poison": .5, "flying": .5, "psychic": 2, "ghost": .5, "dark": 2, "steel": .5, "fairy": .5},
    "rock": {"fire": 2, "ice": 2, "fighting": .5, "ground": .5, "flying": 2, "bug": 2, "steel": .5},
    "ghost": {"normal": 0, "psychic": 2, "ghost": 2, "dark": .5},
    "dragon": {"dragon": 2, "steel": .5, "fairy": 0},
    "dark": {"fighting": .5, "psychic": 2, "ghost": 2, "dark": .5, "fairy": .5},
    "steel": {"fire": .5, "water": .5, "electric": .5, "ice": 2, "rock": 2, "steel": .5, "fairy": 2},
    "fairy": {"fire": .5, "fighting": 2, "poison": .5, "dragon": 2, "dark": 2, "steel": .5},
}


def type_eff(atk, defs):
    t = _SE.get(atk, {})
    e = 1.0
    for d in defs:
        e *= t.get(d, 1.0)
    return e


ROLL = 0.925
MAX_TURNS = 60          # PP 가 다 떨어지면 발버둥이라 회복전도 이 안에 끝나는 경우가 많다
STAGE = {-6: 2 / 8, -5: 2 / 7, -4: 2 / 6, -3: 2 / 5, -2: 2 / 4, -1: 2 / 3, 0: 1, 1: 1.5, 2: 2, 3: 2.5, 4: 3, 5: 3.5, 6: 4}
_SK = {"attack": 1, "defense": 2, "special-attack": 3, "special-defense": 4, "speed": 5}
_NI = {"atk": 1, "def": 2, "spa": 3, "spd": 4, "spe": 5}

# ── 특성·도구 표 (챔피언스에 있는 것만) ──────────────────────────
SKIN = {"aerilate": "flying", "pixilate": "fairy", "refrigerate": "ice", "galvanize": "electric", "dragonize": "dragon"}
IMMUNE_AB = {"levitate": "ground", "eelevate": "ground", "earth-eater": "ground", "flash-fire": "fire", "well-baked-body": "fire",
             "water-absorb": "water", "storm-drain": "water", "dry-skin": "water", "volt-absorb": "electric",
             "lightning-rod": "electric", "motor-drive": "electric", "sap-sipper": "grass"}
TRAIT_BOOST = {"tough-claws": ("contact", 1.3), "iron-fist": ("punch", 1.2), "strong-jaw": ("bite", 1.5),
               "mega-launcher": ("pulse", 1.5), "sharpness": ("slicing", 1.5), "punk-rock": ("sound", 1.3)}
INTIM_BLOCK = {"clear-body", "hyper-cutter", "inner-focus", "oblivious", "own-tempo", "scrappy", "white-smoke", "full-metal-body"}
TYPE_ITEM = {"black-belt": "fighting", "black-glasses": "dark", "charcoal": "fire", "dragon-fang": "dragon",
             "fairy-feather": "fairy", "hard-stone": "rock", "magnet": "electric", "metal-coat": "steel",
             "miracle-seed": "grass", "mystic-water": "water", "never-melt-ice": "ice", "poison-barb": "poison",
             "sharp-beak": "flying", "silk-scarf": "normal", "silver-powder": "bug", "soft-sand": "ground",
             "spell-tag": "ghost", "twisted-spoon": "psychic"}
RESIST_BERRY = {"occa-berry": "fire", "passho-berry": "water", "wacan-berry": "electric", "rindo-berry": "grass",
                "yache-berry": "ice", "chople-berry": "fighting", "kebia-berry": "poison", "shuca-berry": "ground",
                "coba-berry": "flying", "payapa-berry": "psychic", "tanga-berry": "bug", "charti-berry": "rock",
                "kasib-berry": "ghost", "haban-berry": "dragon", "colbur-berry": "dark", "babiri-berry": "steel",
                "roseli-berry": "fairy", "chilan-berry": "normal"}
WEATHER_AB = {"drought": "sun", "drizzle": "rain", "sand-stream": "sand", "snow-warning": "snow"}
TERRAIN_AB = {"psychic-surge": "psychic", "grassy-surge": "grassy", "electric-surge": "electric", "misty-surge": "misty"}
SPEED_WEATHER = {"chlorophyll": "sun", "swift-swim": "rain", "sand-rush": "sand", "slush-rush": "snow"}
PRIO_BLOCK = {"armor-tail", "queenly-majesty", "dazzling"}

# ── 기술 분류 ────────────────────────────────────────────────────
SELF_DROP = {"draco-meteor", "overheat", "leaf-storm", "psycho-boost", "fleur-cannon", "close-combat", "superpower",
             "v-create", "make-it-rain", "armor-cannon", "headlong-rush", "hammer-arm", "ice-hammer", "dragon-ascent",
             "spin-out", "clanging-scales", "scale-shot", "hyperspace-fury"}
SUICIDE = {"explosion", "self-destruct", "misty-explosion", "memento", "final-gambit", "healing-wish", "lunar-dance"}
RECHARGE = {"hyper-beam", "giga-impact", "blast-burn", "hydro-cannon", "frenzy-plant", "rock-wrecker", "roar-of-time", "prismatic-laser", "eternabeam"}
CHARGE = {"solar-beam": "sun", "solar-blade": "sun", "meteor-beam": None, "electro-shot": "rain", "sky-attack": None, "skull-bash": None}
FIRST_TURN = {"fake-out", "first-impression"}
PHAZE = {"roar", "whirlwind", "haze", "dragon-tail", "circle-throw", "clear-smog"}
FIXED_DMG = {"seismic-toss": 50, "night-shade": 50}
HIT_POWER = {"triple-axel": 6, "triple-kick": 6}  # 20+40+60 = 1타 위력 × 6
SPECIAL_VS_DEF = {"psyshock", "psystrike", "secret-sword"}
ALWAYS_CRIT = {"flower-trick", "wicked-blow", "surging-strikes", "storm-throw", "frost-breath", "zippy-zap"}
PROTECT = {"protect", "detect", "kings-shield", "spiky-shield", "baneful-bunker", "silk-trap", "burning-bulwark"}
NO_VALUE = {"endure", "substitute", "stealth-rock", "spikes", "toxic-spikes", "sticky-web", "taunt", "encore",
            "trick-room", "tailwind", "light-screen", "reflect", "aurora-veil", "helping-hand", "follow-me",
            "rage-powder", "u-turn-status", "baton-pass", "trick", "switcheroo", "yawn", "perish-song", "destiny-bond",
            "sleep-talk", "rain-dance", "sunny-day", "sandstorm", "snowscape", "psychic-terrain", "grassy-terrain",
            "electric-terrain", "misty-terrain", "wide-guard", "quick-guard", "ally-switch", "court-change",
            "parting-shot", "teleport", "chilly-reception", "shed-tail", "defog", "rapid-spin-status", "skill-swap"}


def classify(mv):
    """기술 → 'attack' | 'setup' | 'status' | 'heal' | 'phaze' | 'protect' | 'none'"""
    k = mv["key"]
    if k in SUICIDE:
        return "none"
    if k in PROTECT:
        return "protect"
    if k in PHAZE:
        return "phaze" if mv["cat"] == "status" else "attack"
    if mv["cat"] != "status":
        return "attack" if (mv["power"] or k in FIXED_DMG or k == "super-fang") else "none"
    if k in ("belly-drum", "curse"):
        return "setup"
    if k == "rest" or (mv["meta"].get("healing") or 0) > 0 or k == "wish":
        return "heal"
    ail = mv["meta"].get("ailment")
    if mv["target"] in ("selected-pokemon", "all-opponents") and (ail in ("burn", "paralysis", "poison", "sleep", "leech-seed")):
        return "status"
    if mv["target"] == "user" and any(c["change"] > 0 and c["stat"] in _SK for c in mv["stat_changes"]):
        return "setup"
    return "none"


class Build:
    """한 마리의 세트. key 는 기본 폼 키, 메가 스톤을 들면 form 이 메가 폼이 된다."""
    __slots__ = ("D", "key", "form", "item", "ability", "entry_ability", "nature", "sp", "moves", "stats",
                 "types", "blade", "mega", "label", "kinds")

    def __init__(self, D, key, moves, item=None, ability=None, nature="serious", sp=(0, 0, 0, 0, 0, 0), label=None):
        self.D = D
        if D.DEX[key]["base_key"]:                      # 메가 폼 키로 넘기면 기본 폼 + 스톤으로 바꾼다
            item = item or D.DEX[key]["item"]
            key = D.DEX[key]["base_key"]
        self.key, self.item, self.nature, self.sp = key, item, nature, tuple(sp)
        self.moves = [m for m in moves if m in D.MOVES][:4]
        mega = D.STONE.get(item)
        self.mega = bool(mega and D.DEX[mega]["base_key"] == key)
        self.form = mega if self.mega else key
        base_abs = D.DEX[key]["abilities"]
        self.entry_ability = ability if ability in base_abs else (_top_ability(D, key) or base_abs[0])
        self.ability = D.DEX[self.form]["abilities"][0] if self.mega else self.entry_ability
        self.types = D.DEX[self.form]["types"]
        self.stats = calc_stats(D.DEX[self.form]["stats"], sp, nature)
        self.blade = calc_stats(D.DEX["aegislash-blade"]["stats"], sp, nature) if key == "aegislash" and "aegislash-blade" in D.DEX else None
        self.label = label
        self.kinds = {m: classify(D.MOVES[m]) for m in self.moves}

    def spec(self):
        return {"key": self.key, "item": self.item, "ability": self.entry_ability, "nature": self.nature,
                "sp": list(self.sp), "moves": list(self.moves)}

    def __repr__(self):
        D = self.D
        return f"{D.name(self.form)} @{D.item_name(self.item)} [{self.nature}] {'/'.join(D.move_name(m) for m in self.moves)}"


def _top_ability(D, key):
    u = D.USAGE.get(key)
    return u["abilities"][0][0] if u and u["abilities"] else None


def calc_stats(base, sp, nature):
    nat = NATURES.get(nature)
    out = [base[0] + 75 + sp[0]]
    for i in range(1, 6):
        m = 1.0
        if nat:
            if _NI[nat[0]] == i:
                m = 1.1
            elif _NI[nat[1]] == i:
                m = 0.9
        out.append(int((base[i] + 20 + sp[i]) * m))
    return out


# ── 전투 상태 ────────────────────────────────────────────────────
class Side:
    __slots__ = ("b", "maxhp", "hp", "boost", "status", "tox", "sleep", "item", "disguise", "locked", "charging",
                 "recharge", "blade", "sitrus", "heals", "seeded", "turn", "plan_left", "status_done", "stats",
                 "types", "ability", "flinch", "air", "pp", "bound", "bind_frac", "rng", "protean_used",
                 "charged", "protected", "protect_last", "wish", "cprob", "shed", "miss")

    def __init__(self, b, hpfrac=1.0):
        self.b = b
        self.maxhp = b.stats[0]
        self.hp = max(1.0, b.stats[0] * hpfrac)
        self.boost = [0] * 6
        self.status = None
        self.tox = 0
        self.sleep = 0
        self.item = None if b.mega else b.item          # 메가 스톤은 효과 없음
        self.disguise = b.ability == "disguise"
        self.locked = None
        self.charging = None
        self.recharge = False
        self.blade = False
        self.sitrus = self.item == "sitrus-berry"
        self.heals = 0
        self.seeded = False
        self.turn = 0
        self.plan_left = 0
        self.status_done = False
        self.stats = b.stats
        self.types = b.types
        self.ability = b.ability
        self.flinch = False
        self.air = self.item == "air-balloon"
        self.pp = {m: b.D.MOVES[m]["pp"] for m in b.moves}
        self.bound = 0          # 속박(엉겨붙기·회오리불꽃 등) 남은 턴
        self.bind_frac = 0.125
        self.rng = None
        self.protean_used = False
        self.charged = False       # 전기로바꾸기: 맞으면 충전 → 다음 전기 기술 ×2
        self.protected = False     # 이번 턴 방어 중
        self.protect_last = False  # 직전 턴에 방어했나(연속 사용 금지)
        self.wish = 0              # 희망사항: 남은 턴(0 이 되는 턴 끝에 최대 HP 1/2 회복)
        self.cprob = 0.0           # 접촉 상태이상(정전기 등) 누적 확률 — 기대값 모드용
        self.shed = 0.0            # 탈피 누적 확률 — 기대값 모드용
        self.miss = {}             # 기술별 빗나감 누적(기대값 모드): 0.5 에 이르는 차례에 빗나간다

    def st(self, i, ignore_boost=False):
        s = (self.b.blade if (self.blade and self.b.blade and i in (1, 2, 3, 4)) else self.stats)[i]
        return s if ignore_boost else s * STAGE[self.boost[i]]


class Field:
    __slots__ = ("weather", "wturns", "terrain", "tturns", "aura")

    def __init__(self):
        self.weather = None
        self.wturns = 0
        self.terrain = None
        self.tturns = 0
        self.aura = False


def grounded(s):
    return "flying" not in s.types and s.ability not in ("levitate", "eelevate") and not s.air


# 기술 '계열'(타입이 아니라 성질)을 무효화하는 특성: 방탄 = 구슬·폭탄, 방음 = 소리
TRAIT_IMMUNE = {"bulletproof": "ball-bomb", "soundproof": "sound"}
# 접촉하면 30% 로 공격한 쪽에 상태이상
CONTACT_STATUS = {"static": "par", "flame-body": "brn", "poison-point": "psn"}


def weather_for(field, att):
    if att.ability == "mega-sol":
        return "sun"
    return field.weather


def speed(s, field):
    v = s.st(5)
    if s.item == "choice-scarf":
        v *= 1.5
    if s.status == "par":
        v *= 0.5
    w = SPEED_WEATHER.get(s.ability)
    if w and field.weather == w:
        v *= 2
    return v


def priority(s, mv, field):
    p = mv["priority"]
    if mv["key"] == "grassy-glide" and field.terrain == "grassy" and grounded(s):
        p += 1
    if s.ability == "prankster" and mv["cat"] == "status":
        p += 1
    if s.ability == "gale-wings" and mv["type"] == "flying" and s.hp >= s.maxhp:
        p += 1
    return p


def move_type(att, mv, field):
    t = mv["type"]
    k = mv["key"]
    if k == "weather-ball":
        t = {"sun": "fire", "rain": "water", "sand": "rock", "snow": "ice"}.get(weather_for(field, att), "normal")
    if t == "normal" and att.ability in SKIN and mv["cat"] != "status":
        t = SKIN[att.ability]
    if att.ability == "liquid-voice" and "sound" in mv["traits"]:
        t = "water"
    return t


def damage(att, dfd, mv, field, first_hit_check=True):
    """기대 피해가 아니라 '맞았을 때' 피해(평균 난수). 명중은 호출 쪽에서 곱한다."""
    k = mv["key"]
    mold = att.ability in ("mold-breaker", "teravolt", "turboblaze")
    dab = "" if mold else dfd.ability
    t = move_type(att, mv, field)
    eff = type_eff(t, dfd.types)
    if att.ability == "scrappy" and t in ("normal", "fighting") and "ghost" in dfd.types:
        eff = type_eff(t, [x for x in dfd.types if x != "ghost"])
    if IMMUNE_AB.get(dab) == t or (t == "ground" and dfd.air):
        return 0.0
    if TRAIT_IMMUNE.get(dab) in mv["traits"]:
        return 0.0                                       # 방탄·방음
    if eff == 0:
        return 0.0
    if k in FIXED_DMG:
        return float(FIXED_DMG[k])
    if k == "super-fang":
        return dfd.hp / 2
    pw = mv["power"]
    if not pw:
        return 0.0
    if t != mv["type"] and att.ability in SKIN:
        pw *= 1.2
    if k == "weather-ball" and weather_for(field, att):
        pw = 100
    if k == "knock-off" and dfd.item and dfd.item not in dfd.b.D.STONE:
        pw *= 1.5
    if k == "acrobatics" and not att.item:
        pw *= 2
    if k in ("hex", "venoshock", "infernal-parade") and dfd.status:
        pw *= 2
    if k == "facade" and att.status:
        pw *= 2
    if att.charged and t == "electric":              # 전기로바꾸기(충전) 상태
        pw *= 2
    if att.ability == "technician" and pw <= 60:
        pw *= 1.5
    # 타수
    meta = mv["meta"]
    if k in HIT_POWER:
        pw *= HIT_POWER[k]
    elif k == "population-bomb":
        pw *= 10 if att.ability == "skill-link" else 7
    else:
        lo, hi = meta.get("minHits"), meta.get("maxHits")
        if lo and hi:
            pw *= hi if (lo == hi or att.ability == "skill-link") else 3.1
    cat = mv["cat"]
    crit = k in ALWAYS_CRIT and dfd.ability not in ("battle-armor", "shell-armor")
    ign_a = dfd.ability == "unaware" and not mold
    ign_d = att.ability == "unaware" or crit          # 급소는 상대 방어 랭크업을 무시(근사: 전부 무시)
    if k == "body-press":
        A = att.st(2, ign_a)
    elif k == "foul-play":
        A = dfd.st(1, ign_d)
    else:
        i = 1 if cat == "physical" else 3
        A = att.b.blade[i] * (1 if ign_a else STAGE[att.boost[i]]) if att.b.blade else att.st(i, ign_a)  # 킬가르도는 공격할 때 블레이드폼
    if cat == "physical":
        if att.ability in ("huge-power", "pure-power"):
            A *= 2
        if att.ability == "hustle":
            A *= 1.5
        if att.status == "brn" and att.ability != "guts" and k != "facade":
            A *= 0.5
        if att.ability == "guts" and att.status:
            A *= 1.5
    elif att.ability == "solar-power" and weather_for(field, att) == "sun":
        A *= 1.5
    phys_def = cat == "physical" or k in SPECIAL_VS_DEF
    Dv = dfd.st(2 if phys_def else 4, ign_d)
    if phys_def and dab == "fur-coat":
        Dv *= 2
    if field.weather == "sand" and not phys_def and "rock" in dfd.types:
        Dv *= 1.5
    if field.weather == "snow" and phys_def and "ice" in dfd.types:
        Dv *= 1.5
    d = (int(int(22 * pw * A / max(1.0, Dv)) / 50) + 2) * ROLL
    if crit:
        d *= 1.5
    w = weather_for(field, att)
    if w == "sun":
        d *= 1.5 if t == "fire" else 0.5 if t == "water" else 1
    elif w == "rain":
        d *= 1.5 if t == "water" else 0.5 if t == "fire" else 1
    if field.terrain and grounded(att):
        if (field.terrain, t) in (("electric", "electric"), ("grassy", "grass"), ("psychic", "psychic")):
            d *= 1.3
    if field.terrain == "grassy" and k in ("earthquake", "bulldoze") and grounded(dfd):
        d *= 0.5
    if field.terrain == "misty" and t == "dragon" and grounded(dfd):
        d *= 0.5
    # 변환자재·리베로: 등장 후 첫 기술 때 그 기술 타입으로 바뀐다(1회). 아직 안 바뀌었으면 어떤 기술이든 자속.
    if t in att.types or (att.ability in ("protean", "libero") and not att.protean_used):
        d *= 2.0 if att.ability == "adaptability" else 1.5
    d *= eff
    # 공격 특성
    tb = TRAIT_BOOST.get(att.ability)
    if tb and tb[0] in mv["traits"]:
        d *= tb[1]
    if att.ability == "reckless" and (meta.get("drain") or 0) < 0:
        d *= 1.2
    if att.ability == "sheer-force" and ((meta.get("ailmentChance") or 0) > 0 or (meta.get("flinchChance") or 0) > 0):
        d *= 1.3
    if att.ability == "tinted-lens" and eff < 1:
        d *= 2
    if att.ability == "water-bubble" and t == "water":
        d *= 2
    if att.ability == "sand-force" and field.weather == "sand" and t in ("rock", "ground", "steel"):
        d *= 1.3
    if field.aura and t == "fairy":
        d *= 4 / 3
    # 방어 특성
    if dab in ("thick-fat",) and t in ("fire", "ice"):
        d *= 0.5
    if dab in ("heatproof", "water-bubble") and t == "fire":
        d *= 0.5
    if dab == "purifying-salt" and t == "ghost":
        d *= 0.5
    if dab == "fluffy":
        d *= (0.5 if "contact" in mv["traits"] else 1) * (2 if t == "fire" else 1)
    if dab == "ice-scales" and cat == "special":
        d *= 0.5
    if dab == "grass-pelt" and t == "grass":
        d *= 0.5                                         # 풀모피(챔피언스 설명: 풀 기술 반감)
    if dab == "aura-guard" and cat == "physical" and "contact" in mv["traits"]:
        d *= 0.5                                         # 파동의방호: 접촉 물리 반감
    if dab == "dry-skin" and t == "fire":
        d *= 1.25
    # 멀티스케일·반감 열매는 '첫 타'만 줄인다. 연속기는 위력×타수로 한 번에 계산하므로 첫 타 비중만큼만 반감.
    first = _first_hit_share(att, mv)
    if dab in ("multiscale", "shadow-shield") and dfd.hp >= dfd.maxhp:
        d *= 1 - 0.5 * first
    if dab in ("filter", "solid-rock", "prism-armor") and eff > 1:
        d *= 0.75
    # 도구
    it = att.item
    if it == "life-orb":
        d *= 1.3
    elif it == "expert-belt" and eff > 1:
        d *= 1.2
    elif it == "muscle-band" and cat == "physical":
        d *= 1.1
    elif it == "wise-glasses" and cat == "special":
        d *= 1.1
    elif it in TYPE_ITEM and TYPE_ITEM[it] == t:
        d *= 1.2
    rb = RESIST_BERRY.get(dfd.item)
    if rb and rb == t and (eff > 1 or rb == "normal"):
        d *= 1 - 0.5 * first
    return d


def _first_hit_share(att, mv):
    """연속기에서 첫 타가 차지하는 피해 비중. 단타기는 1. 트리플악셀·트리플킥은 20/120."""
    k = mv["key"]
    if k in HIT_POWER:
        return 1 / HIT_POWER[k]
    n = n_hits(att, mv)
    return 1.0 / n if n > 1 else 1.0


# ── 전투 진행 ────────────────────────────────────────────────────

def _acc(mv, att, field):
    a = mv["acc"]
    if a is None or att.ability == "no-guard":
        return 1.0
    if mv["key"] == "blizzard" and field.weather == "snow":
        return 1.0
    if mv["key"] in ("thunder", "hurricane") and field.weather == "rain":
        return 1.0
    return a / 100.0


def will_hit(s, k, a):
    """기대값 모드에서 이번 사용이 맞는가: 빗나감 누적 + 이번 몫이 0.5 미만이면 맞는다."""
    return a >= 1.0 or s.miss.get(k, 0.0) + (1 - a) < 0.5


def _usable(s, m, turn):
    k = m["key"]
    if k in FIRST_TURN and s.turn > 0:
        return False
    return s.pp.get(k, 1) > 0


COND_PRIORITY = {"sucker-punch", "thunderclap"}   # 상대가 공격할 때만 성공 — 읽힐 수 있는 수
STRUGGLE = {"key": "struggle", "name": "발버둥", "type": "typeless", "cat": "physical", "power": 50, "acc": None,
            "priority": 0, "pp": 99, "target": "selected-pokemon", "meta": {}, "stat_changes": [],
            "traits": {"contact"}, "available": True}


def _recoil_frac(s, mv):
    """준 피해 중 스스로 받는 비율."""
    if s.ability in ("rock-head", "magic-guard"):
        return 0.0
    dr = mv["meta"].get("drain") or 0
    return -dr / 100 if dr < 0 else 0.0


def best_attack(s, o, field, can_ko_only=False, avoid=()):
    """(기술, 1회 피해, 명중).
    잡을 수 있으면: 반동으로 같이 죽지 않는 기술 > 우선도 > 명중 > 반동 적음.
    못 잡으면: (상대 HP 중 깎는 비율 × 명중) − (내 HP 중 반동 비율) + 흡수 회복 이 최대인 기술.
    깎는 양은 상대 남은 HP(띠·옹골참·탈이면 HP−1)에서 자르므로 넘치는 위력은 값이 없다."""
    D = s.b.D
    if s.locked:
        mv = D.MOVES[s.locked] if s.pp.get(s.locked, 1) > 0 else STRUGGLE
        return mv, damage(s, o, mv, field), _acc(mv, s, field)
    best, bestv, ko = None, -9.0, None
    blocks0 = o.disguise or (o.item == "focus-sash" and o.hp >= o.maxhp) or (o.ability == "sturdy" and o.hp >= o.maxhp)
    any_pp = False
    for k in s.b.moves:
        if s.b.kinds[k] != "attack" or k in avoid:
            continue
        mv = D.MOVES[k]
        if not _usable(s, mv, s.turn):
            continue
        any_pp = True
        d = damage(s, o, mv, field)
        if d <= 0:
            continue
        a = _acc(mv, s, field)
        if priority(s, mv, field) > 0 and (field.terrain == "psychic" and grounded(o) or o.ability in PRIO_BLOCK):
            continue
        eff_d = d
        if k in CHARGE and not (CHARGE[k] and weather_for(field, s) == CHARGE[k]):
            eff_d = d / 2
        if k in RECHARGE:
            eff_d = d / 2
        rf = _recoil_frac(s, mv)
        nh = n_hits(s, mv)
        blocks = blocks0 and not (nh > 1 and not o.disguise)      # 연속기는 띠·옹골참을 뚫는다
        cap = max(1.0, o.hp - 1) if blocks else o.hp
        # '잡는다' 판정은 실제로 들어갈 피해로: 확률 모드는 맞았을 때 값,
        # 기대값 모드는 act() 와 같은 규칙(빗나감 누적)으로 이번에 맞으면 전체 피해, 빗나갈 차례면 0
        hit_d = d if (s.rng is not None or will_hit(s, k, a)) else 0.0
        if hit_d >= o.hp and not blocks and k not in CHARGE:
            lethal = rf * o.hp >= s.hp
            key = (not lethal, priority(s, mv, field), a, -rf, d)
            if ko is None or key > ko[0]:
                ko = (key, mv, d, a)
        dealt = min(eff_d, cap)
        recoil = rf * dealt * a
        v = dealt * a / max(1.0, o.hp) - recoil / max(1.0, s.hp)
        if recoil >= s.hp:
            v -= 1.0                                   # 못 잡으면서 반동으로 자멸하는 수
        dr = mv["meta"].get("drain") or 0
        if dr > 0:
            v += 0.5 * min(s.maxhp - s.hp, dealt * a * dr / 100) / s.maxhp
        if v > bestv:
            best, bestv = (mv, d, a), v
    if ko:
        return ko[1], ko[2], ko[3]
    if can_ko_only:
        return None
    if best is None and not any_pp and not avoid and any(s.b.kinds[m] == "attack" for m in s.b.moves):
        return STRUGGLE, damage(s, o, STRUGGLE, field), 1.0   # PP 가 바닥나면 발버둥
    return best if best else (None, 0.0, 0.0)


def _heal_frac(mv, field):
    k = mv["key"]
    if k == "rest":
        return 1.0
    frac = (mv["meta"].get("healing") or 50) / 100
    if k in ("moonlight", "synthesis", "morning-sun"):
        frac = 2 / 3 if field.weather == "sun" else 0.25 if field.weather in ("rain", "sand", "snow") else 0.5
    if k == "shore-up" and field.weather == "sand":
        frac = 2 / 3
    return frac


def _heal_amount(s, mv, field):
    return min(s.maxhp - s.hp, s.maxhp * _heal_frac(mv, field))


def _status_ok(s, o, mv, field):
    ail = mv["meta"].get("ailment")
    k = mv["key"]
    if o.ability in ("good-as-gold", "magic-bounce"):
        return False
    if TRAIT_IMMUNE.get(o.ability) in mv["traits"] and s.ability not in ("mold-breaker", "teravolt", "turboblaze"):
        return False                                     # 방음(노래하기 등)·방탄
    if ail == "leech-seed":
        return not o.seeded and "grass" not in o.types
    if o.status:
        return False
    if field.terrain == "misty" and grounded(o):
        return False
    if ail == "burn":
        return "fire" not in o.types and o.ability not in ("water-veil", "water-bubble", "thermal-exchange")
    if ail == "paralysis":
        if "electric" in o.types or o.ability == "limber":
            return False
        return not (k == "thunder-wave" and "ground" in o.types)
    if ail == "poison":
        return s.ability == "corrosion" or ("poison" not in o.types and "steel" not in o.types and o.ability != "immunity")
    if ail == "sleep":
        if "powder" in mv["traits"] and ("grass" in o.types or o.ability == "overcoat"):
            return False
        return o.ability not in ("insomnia", "vital-spirit", "sweet-veil") and not (field.terrain == "electric" and grounded(o))
    return False


def choose(s, o, field, plan):
    """이번 턴 행동: ('move', mv) | ('skip', None)."""
    D = s.b.D
    if s.recharge:
        return ("skip", None)
    if s.charging:
        return ("move", D.MOVES[s.charging])
    kind, pm, n = plan
    avoid = COND_PRIORITY if (kind == "atk" and pm == "nosucker") else ()
    ko = best_attack(s, o, field, can_ko_only=True, avoid=avoid)
    # 속이기: 첫 턴이면 (+3 로 먼저 쳐서 상대를 풀죽게 만드는) 공짜 한 턴. 지금 확실히 먼저 잡을 수 있을 때만 양보.
    if s.turn == 0 and "fake-out" in s.b.moves and s.pp.get("fake-out", 0) > 0 and not s.locked:
        fo = D.MOVES["fake-out"]
        usable = (damage(s, o, fo, field) > 0 and o.ability not in PRIO_BLOCK
                  and not (field.terrain == "psychic" and grounded(o)))
        sure_ko = ko and ko[0] is not None and (priority(s, ko[0], field) > 0 or speed(s, field) > speed(o, field))
        if usable and not sure_ko:
            return ("move", fo)
    if ko and ko[0] is not None:
        return ("move", ko[0])
    opp_best = best_attack(o, s, field)
    opp_d = opp_best[1] * opp_best[2] if opp_best[0] else 0.0
    # 쌓은 상대 → 흑안개·날려버리기 (PP 있을 때)
    if sum(max(0, x) for x in (o.boost[1], o.boost[3], o.boost[5])) >= 2:
        for k in s.b.moves:
            if s.b.kinds[k] == "phaze" and s.pp.get(k, 0) > 0:
                return ("move", D.MOVES[k])
    # 회복: 두 대 안에 쓰러질 위험이거나 절반 이하이고, (회복 + 턴 종료 회복)이 상대 한 턴 피해보다 클 때.
    # 내가 느리고 이번 턴 한 대에 쓰러지면 회복은 늦으므로 쓰지 않는다. 횟수는 PP 로만 제한.
    if opp_d > 0 or s.hp < s.maxhp:
        regen = s.maxhp / 16 if (s.item == "leftovers" or (s.item == "black-sludge" and "poison" in s.types)) else 0.0
        slower = speed(s, field) < speed(o, field) or (opp_best[0] is not None and priority(o, opp_best[0], field) > 0)
        # 느리면 이번 턴 한 대 맞고 나서 움직이고, 다음 턴에도 먼저 맞는다 → (맞은 뒤 HP + 턴 종료 회복) 으로 판단.
        # 빠르면 내가 움직인 뒤 이번 턴에 맞는다 → 지금 HP 로 판단.
        # 다음 한 대를 못 버틸 때만 회복한다(버틸 수 있으면 때리는 게 낫다 — 더시마사리식 회복·엉겨붙기 교대).
        hp_at_act = s.hp - (opp_d if slower else 0.0)
        margin = hp_at_act + (regen if slower else 0.0) - opp_d
        prot = next((k for k in s.b.moves if s.b.kinds[k] == "protect" and s.pp.get(k, 0) > 0), None)
        # 희망사항이 이번 턴 끝에 들어오면 방어로 한 턴 버틴다(희망사항 → 방어)
        if s.wish == 1 and prot and not s.protect_last:
            return ("move", D.MOVES[prot])
        sustain = kind == "atk" and pm == "sustain"
        # 버티기 계획: 상대가 턴마다 깎이면(맹독·화상·씨뿌리기·속박) 방어로 한 턴 더 깎는다
        residual = o.status in ("tox", "brn", "psn") or o.seeded or o.bound
        if sustain and prot and not s.protect_last and residual and o.ability != "magic-guard":
            return ("move", D.MOVES[prot])
        for k in s.b.moves:
            if s.b.kinds[k] != "heal" or s.pp.get(k, 0) <= 0 or hp_at_act <= 0:
                continue
            mv = D.MOVES[k]
            frac_heal = s.maxhp * _heal_frac(mv, field)
            if k == "wish":
                # 희망사항은 한 턴 늦게 들어온다: 다음 턴을 방어로 버틸 수 있거나 그냥 버틸 수 있을 때, 두 대 안에 위험하면
                if not s.wish and hp_at_act <= 2 * opp_d and (prot or margin > 0):
                    return ("move", mv)
                continue
            if sustain:
                # 버티기 계획: 회복량을 거의 다 쓸 만큼 깎였으면 미리 회복(회복 먼저, 공격은 나중에)
                if s.maxhp - hp_at_act >= 0.9 * frac_heal and frac_heal + regen > 0.5 * opp_d:
                    return ("move", mv)
            elif margin <= 0 and frac_heal + regen > opp_d and margin + min(frac_heal, s.maxhp - hp_at_act) > 0:
                # 기본: 다음 한 대를 못 버틸 때만, 회복이 상대 한 턴 피해를 따라잡을 때
                return ("move", mv)
    # 계획
    if kind == "setup" and s.plan_left > 0 and not s.locked and s.pp.get(pm, 0) > 0:
        return ("move", D.MOVES[pm])
    if kind == "status" and not s.status_done and not s.locked:
        s.status_done = True
        if _status_ok(s, o, D.MOVES[pm], field):
            return ("move", D.MOVES[pm])
    mv, d, a = best_attack(s, o, field, avoid=avoid)
    if mv is None and avoid:
        mv, d, a = best_attack(s, o, field)
    if mv is None:
        return ("skip", None)
    return ("move", mv)


def _apply_stat(s, changes, sign=1):
    for c in changes:
        i = _SK.get(c["stat"])
        if i:
            s.boost[i] = max(-6, min(6, s.boost[i] + sign * c["change"]))


def n_hits(att, mv):
    """기대 타수. 연속기는 띠·옹골참·탈을 첫 타로 깨고 나머지 타로 넘긴다."""
    k = mv["key"]
    if k in HIT_POWER:
        return 3
    if k == "population-bomb":
        return 10 if att.ability == "skill-link" else 7
    lo, hi = mv["meta"].get("minHits"), mv["meta"].get("maxHits")
    if lo and hi:
        return hi if (lo == hi or att.ability == "skill-link") else 3.1
    return 1


def _take(s, d, field, hits=1):
    """피해 적용. 탈·띠·옹골참·열매 처리. 실제 들어간 피해를 돌려준다.
    hits>1(연속기)면 탈은 첫 타만 막고, 띠·옹골참은 남은 타에 뚫린다."""
    if d <= 0:
        return 0.0
    if s.disguise:
        s.disguise = False
        s.hp -= s.maxhp / 8
        if hits <= 1:
            return 0.0
        d *= (hits - 1) / hits
    full = s.hp >= s.maxhp
    if d >= s.hp and full and hits <= 1 and (s.item == "focus-sash" or s.ability == "sturdy"):
        d = s.hp - 1
        if s.item == "focus-sash":
            s.item = None
    d = min(d, s.hp)
    s.hp -= d
    if s.sitrus and 0 < s.hp <= s.maxhp / 2:
        s.hp += s.maxhp / 4 + (s.maxhp / 3 if s.ability == "cheek-pouch" else 0)   # 볼주머니: 열매 먹으면 1/3 추가
        s.sitrus = False
        s.item = None
    return d


def _contact_reaction(s, o):
    """o 의 특성이 접촉한 s 에게 주는 효과.
    미끈미끈: 스피드 −1. 정전기·불꽃몸·독가시: 30% 상태이상 — 확률 모드는 30% 로 뽑고,
    기대값 모드는 누적 확률 1−0.7ⁿ 이 0.5 를 넘는 순간(=두 번째 접촉)에 건다."""
    ab = o.ability
    if ab == "gooey" and s.ability not in ("clear-body", "white-smoke", "full-metal-body", "mirror-armor"):
        s.boost[5] = max(-6, s.boost[5] - 1)
    st = CONTACT_STATUS.get(ab)
    if not st or s.status or s.hp <= 0:
        return
    immune = ((st == "brn" and ("fire" in s.types or s.ability in ("water-veil", "water-bubble")))
              or (st == "par" and ("electric" in s.types or s.ability == "limber"))
              or (st == "psn" and ({"poison", "steel"} & set(s.types) or s.ability == "immunity"))
              or s.ability == "purifying-salt" or s.item == "covert-cloak")
    if immune:
        return
    if s.rng is not None:
        hit = s.rng.random() < 0.3
    else:
        s.cprob = 1 - (1 - s.cprob) * 0.7
        hit = s.cprob >= 0.5
    if hit:
        if s.item == "lum-berry":
            s.item = None
        else:
            s.status = st


def act(s, o, mv, field, o_action, mult=1.0):
    """s 가 mv 를 쓴다. o_action 은 상대가 이번 턴 고른 행동(기습 성공 판정용). mult 는 마비 등 기대값 감쇠."""
    D = s.b.D
    k = mv["key"]
    kind = s.b.kinds.get(k) or classify(mv)
    if k in s.pp and s.charging != k:
        s.pp[k] -= 1
    if s.item == "choice-scarf" and not s.locked and kind == "attack":
        s.locked = k
    if kind == "protect":
        s.protected = True
        if k == "kings-shield" and s.b.blade is not None:
            s.blade = False                                # 킬가르도: 실드폼으로 돌아간다
        return
    # 상대가 방어 중이면 공격·상태이상은 막힌다(모으기 첫 턴·자기 강화는 통과)
    if o.protected and kind in ("attack", "status") and not (kind == "attack" and k in CHARGE and s.charging != k):
        spiky = o_action and o_action[0] == "move" and o_action[1]["key"] == "spiky-shield"
        if kind == "attack" and spiky and "contact" in mv["traits"] and s.ability != "magic-guard":
            s.hp -= s.maxhp / 8                            # 니들가드: 접촉하면 1/8
        return
    if kind == "attack":
        if k in CHARGE and s.charging != k and not (CHARGE[k] and weather_for(field, s) == CHARGE[k]):
            s.charging = k
            if k in ("meteor-beam", "electro-shot"):
                s.boost[3] = min(6, s.boost[3] + 1)
            return
        s.charging = None
        if k in ("sucker-punch", "thunderclap") and (o_action is None or o_action[0] != "move" or o_action[1]["cat"] == "status"):
            return
        if k == "fake-out" or k == "first-impression":
            if s.turn > 0:
                return
        if s.b.blade is not None:
            s.blade = True
        if s.ability in ("protean", "libero") and not s.protean_used:
            s.types = [move_type(s, mv, field)]            # 막는 타입도 바뀐다
            s.protean_used = True
        if s.rng is None:
            # 기대값 모드: 피해에 명중률을 곱하지 않는다(곱하면 확정 1타가 1타가 아니게 된다).
            # 대신 기술마다 빗나감 확률을 누적해 0.5 에 이르는 차례에만 빗나간다 — 90% 기술은 5번째에 한 번.
            a = _acc(mv, s, field)
            if will_hit(s, k, a):
                s.miss[k] = s.miss.get(k, 0.0) + (1 - a)
                d = damage(s, o, mv, field) * mult
            else:
                s.miss[k] = s.miss.get(k, 0.0) + (1 - a) - 1
                d = 0.0
        else:
            r = s.rng
            if r.random() >= _acc(mv, s, field):
                d = 0.0                                                       # 빗나감
            else:
                d = damage(s, o, mv, field) * r.uniform(0.85, 1.0) / ROLL
                if k not in ALWAYS_CRIT and o.ability not in ("battle-armor", "shell-armor") and r.random() < 1 / 24:
                    d *= 1.5
        rb = RESIST_BERRY.get(o.item)
        if s.charged and move_type(s, mv, field) == "electric":
            s.charged = False                              # 충전은 한 번 쓰면 끝
        hp_before = o.hp
        dealt = _take(o, d, field, hits=n_hits(s, mv))
        if dealt > 0 and o.hp > 0 and o.ability == "electromorphosis":
            o.charged = True
        if dealt > 0 and o.hp > 0 and mv["cat"] == "physical" and o.ability == "weak-armor":
            o.boost[2] = max(-6, o.boost[2] - 1)          # 깨어진갑옷: 방어 −1, 스피드 +2
            o.boost[5] = min(6, o.boost[5] + 2)
        if rb and dealt > 0 and move_type(s, mv, field) == rb:
            o.item = None
        if k == "knock-off" and o.item and o.item not in D.STONE:
            if o.item == "sitrus-berry":
                o.sitrus = False
            o.item = None
            o.air = False
        if o.air and dealt > 0:
            o.air = False
            o.item = None
        meta = mv["meta"]
        dr = meta.get("drain") or 0
        if dr > 0:
            if o.ability == "liquid-ooze":                 # 해감액: 흡수한 만큼 오히려 피해
                if s.ability != "magic-guard":
                    s.hp -= dealt * dr / 100
            else:
                s.hp = min(s.maxhp, s.hp + dealt * dr / 100)
        elif dr < 0 and s.ability not in ("rock-head", "magic-guard"):
            s.hp -= dealt * (-dr) / 100
        if s.item == "life-orb" and dealt > 0 and s.ability != "magic-guard":
            s.hp -= s.maxhp / 10
        # 접촉 반격은 맞은 타마다. 도중에 쓰러지면 쓰러뜨린 타까지만.
        nh = n_hits(s, mv)
        landed = nh
        if nh > 1 and o.hp <= 0 and d > 0:
            landed = min(nh, max(1.0, math.ceil(hp_before / (d / nh))))
        if "contact" in mv["traits"] and dealt > 0 and s.ability != "magic-guard":
            if o.item == "rocky-helmet":
                s.hp -= s.maxhp / 6 * landed
            if o.ability in ("rough-skin", "iron-barbs"):
                s.hp -= s.maxhp / 8 * landed
        if "contact" in mv["traits"] and dealt > 0:
            for _ in range(max(1, int(round(landed)))):
                _contact_reaction(s, o)
        if (meta.get("statChance") or 0) >= 100 and mv["stat_changes"]:
            ch = mv["stat_changes"]
            if k in SELF_DROP or all(c["change"] > 0 for c in ch):
                _apply_stat(s, ch)
            elif o.ability == "mirror-armor" and o.hp > 0:
                _apply_stat(s, ch)                          # 미러아머: 능력 하락을 되받아친다
            elif o.ability not in ("clear-body", "white-smoke", "full-metal-body") and o.hp > 0:
                _apply_stat(o, ch)
        if k == "clear-smog":
            o.boost = [0] * 6
        if k in ("dragon-tail", "circle-throw"):
            o.boost = [0] * 6
        if k == "fake-out" and dealt > 0 and o.ability not in ("inner-focus", "shield-dust") and o.item != "covert-cloak":
            o.flinch = True
        if k in RECHARGE:
            s.recharge = True
        if k == "struggle":
            s.hp -= s.maxhp / 4
        if meta.get("ailment") == "trap" and dealt > 0 and o.hp > 0 and not o.bound:
            o.bound = 5                                   # 4~5턴 → 5 (실제로는 거의 끝까지 간다)
            o.bind_frac = 1 / 6 if s.item == "binding-band" else 1 / 8
    elif kind == "setup":
        if k == "belly-drum":
            if s.hp > s.maxhp / 2:
                s.hp -= s.maxhp / 2
                s.boost[1] = 6
        elif k == "curse":
            _apply_stat(s, [{"stat": "attack", "change": 1}, {"stat": "defense", "change": 1}, {"stat": "speed", "change": -1}])
        else:
            _apply_stat(s, mv["stat_changes"])
        s.plan_left -= 1
    elif kind == "heal":
        s.heals += 1
        if k == "rest":
            s.hp = s.maxhp
            s.status, s.tox, s.sleep = "slp", 0, 2
        elif k == "wish":
            if not s.wish:
                s.wish = 2                                 # 다음 턴 끝에 최대 HP 1/2 회복
        else:
            s.hp += _heal_amount(s, mv, field)
    elif kind == "status":
        acc = _acc(mv, s, field)
        miss = (s.rng.random() >= acc) if s.rng is not None else acc < 0.5
        if miss or not _status_ok(s, o, mv, field):
            return
        ail = mv["meta"].get("ailment")
        if ail == "leech-seed":
            o.seeded = True
            return
        if o.item == "lum-berry":
            o.item = None
            return
        o.status = {"burn": "brn", "paralysis": "par", "poison": "tox" if k == "toxic" else "psn", "sleep": "slp"}[ail]
        if o.status == "slp":
            o.sleep = s.rng.randint(1, 3) if s.rng is not None else 2
    elif kind == "phaze":
        o.boost = [0] * 6
        o.plan_left = 0


def end_of_turn(s, o, field):
    if s.hp <= 0:
        return
    mg = s.ability == "magic-guard"
    if field.weather == "sand" and not mg and not ({"rock", "ground", "steel"} & set(s.types)) and s.ability not in ("sand-veil", "sand-rush", "sand-force", "overcoat"):
        s.hp -= s.maxhp / 16
    if field.weather == "snow" and s.ability == "ice-body":
        s.hp = min(s.maxhp, s.hp + s.maxhp / 16)
    if field.weather == "rain" and s.ability == "rain-dish":
        s.hp = min(s.maxhp, s.hp + s.maxhp / 16)
    if s.status and s.status != "slp":
        if field.weather == "rain" and s.ability == "hydration":
            s.status, s.tox = None, 0                      # 촉촉바디
        elif s.ability == "shed-skin":                     # 탈피 30%: 확률 모드는 뽑고, 기대값 모드는 누적 0.5 에서
            if s.rng is not None:
                cure = s.rng.random() < 0.3
            else:
                s.shed = 1 - (1 - s.shed) * 0.7
                cure = s.shed >= 0.5
            if cure:
                s.status, s.tox, s.shed = None, 0, 0.0
    if s.item == "leftovers" or (s.item == "black-sludge" and "poison" in s.types):
        s.hp = min(s.maxhp, s.hp + s.maxhp / 16)
    if field.terrain == "grassy" and grounded(s):
        s.hp = min(s.maxhp, s.hp + s.maxhp / 16)
    if not mg:
        if s.status == "brn":
            s.hp -= s.maxhp / 16
        elif s.status == "psn":
            s.hp -= s.maxhp / 8 if s.ability != "poison-heal" else -s.maxhp / 8
        elif s.status == "tox":
            s.tox += 1
            s.hp -= s.maxhp * s.tox / 16 if s.ability != "poison-heal" else -s.maxhp / 8
        if s.seeded:
            dd = s.maxhp / 8
            s.hp -= dd
            if o.hp > 0:
                o.hp = min(o.maxhp, o.hp + dd)
        if s.bound:
            s.hp -= s.maxhp * s.bind_frac
            s.bound -= 1
    if s.wish:
        s.wish -= 1
        if s.wish == 0 and s.hp > 0:
            s.hp += s.maxhp / 2                            # 희망사항 발동
    s.hp = min(s.hp, s.maxhp)
    s.protect_last, s.protected = s.protected, False
    if s.ability == "speed-boost":
        s.boost[5] = min(6, s.boost[5] + 1)


def _setup_field(a, b, field):
    # 위협(등장 특성) — 메가는 기본 폼 특성으로 등장한 뒤 메가진화한다
    for x, y in ((a, b), (b, a)):
        if x.b.entry_ability == "intimidate" and y.b.entry_ability not in INTIM_BLOCK and y.item != "clear-amulet":
            if y.b.entry_ability == "guard-dog":
                y.boost[1] += 1
            elif y.b.entry_ability == "mirror-armor":
                x.boost[1] -= 1                            # 미러아머: 위협을 되받아친다
            else:
                y.boost[1] -= 1
                if y.b.entry_ability == "defiant":
                    y.boost[1] += 2
                if y.b.entry_ability == "competitive":
                    y.boost[3] += 2
                if y.b.entry_ability == "rattled":
                    y.boost[5] += 1
    # 날씨·필드 — 나중에 발동한 쪽이 이긴다. 등장 특성(빠른 순) → 턴 시작 메가진화(빠른 순)
    order = sorted((a, b), key=lambda s: (s.b.mega, -s.stats[5]))
    for s in order:
        w = WEATHER_AB.get(s.ability)
        if w:
            field.weather, field.wturns = w, 5
        t = TERRAIN_AB.get(s.ability)
        if t:
            field.terrain, field.tturns = t, 5
    field.aura = "fairy-aura" in (a.ability, b.ability)


def transform(me, target):
    """괴짜(메타몽): 등장하자마자 상대로 변신 — 능력치(HP 제외)·타입·특성·기술을 복사, 도구는 자기 것."""
    D = me.D
    t = Build(D, target.key, target.moves, target.item if target.mega else None, target.entry_ability,
              target.nature, target.sp)
    t.stats = [me.stats[0]] + list(target.stats[1:])
    t.entry_ability = "imposter"                      # 등장 특성은 괴짜 (위협 등은 복사 전이라 발동 안 함)
    t.item = me.item
    return t


def _side(X, Y, hp):
    if X.ability == "imposter":
        s = Side(transform(X, Y), hp)
        s.item = X.item                               # 상대가 메가여도 내 도구(스카프 등)는 그대로
        s.sitrus = s.item == "sitrus-berry"
        s.air = s.item == "air-balloon"
        s.pp = {m: 5 for m in s.b.moves}               # 변신한 기술은 PP 5
        return s
    return Side(X, hp)


def usable(b):
    """1:1 에서 싸울 수 있는 세트인가(공격기가 있거나 괴짜로 상대를 복사)."""
    return b.ability == "imposter" or any(b.kinds[m] == "attack" for m in b.moves)


def _tr(trace, t, s, o, what, hs, ho):
    D = s.b.D
    trace.append(f"T{t:<2} {D.name(s.b.form):<8} {what:<14} 자신 {hs:6.1f}→{s.hp:6.1f}  상대 {ho:6.1f}→{o.hp:6.1f}")


def simulate(A, B, planA=("atk", None, 0), planB=("atk", None, 0), hpA=1.0, hpB=1.0, pre_hit=False, tie_a_first=True,
             max_turns=MAX_TURNS, trace=None, rng=None):
    """A 입장 결과 ∈ [-1,1]. pre_hit=True 면 B 가 교체 들어오는 A 에게 공짜 한 방을 먼저 넣는다.
    trace 에 리스트를 주면 턴별 행동과 HP 변화를 적는다(디버그용).
    rng(random.Random) 를 주면 명중·난수·급소·마비·잠듦 턴을 뽑는 확률 모드, 없으면 기대값 모드.

    종료 값: 한쪽이 쓰러지면 승자 +0.5 + 0.5×남은HP비율. max_turns 턴(PP 가 다 떨어지면 발버둥)까지
    안 끝나면 0.5×(내 HP비율 − 상대 HP비율), 범위 ±0.5 — 회복전은 '버틴 쪽이 조금 유리' 이상으로 치지 않는다."""
    a, b = _side(A, B, hpA), _side(B, A, hpB)
    a.rng = b.rng = rng
    first = None
    a.plan_left = planA[2] if planA[0] == "setup" else 0
    b.plan_left = planB[2] if planB[0] == "setup" else 0
    field = Field()
    _setup_field(a, b, field)
    if pre_hit:
        mv, d, acc = best_attack(b, a, field)
        if mv is not None:
            act(b, a, mv, field, None)
            b.turn = 1
    for _ in range(max_turns):
        ca = choose(a, b, field, planA)
        cb = choose(b, a, field, planB)
        pa = priority(a, ca[1], field) if ca[0] == "move" else 0
        pb = priority(b, cb[1], field) if cb[0] == "move" else 0
        if pa != pb:
            a_first = pa > pb
        else:
            sa, sb = speed(a, field), speed(b, field)
            a_first = sa > sb or (sa == sb and tie_a_first)
        order = ((a, b, ca, cb), (b, a, cb, ca)) if a_first else ((b, a, cb, ca), (a, b, ca, cb))
        for s, o, c, oc in order:
            if s.hp <= 0 or o.hp <= 0:
                continue
            if s.flinch:
                s.flinch = False
                continue
            if s.status == "slp":
                s.sleep -= 1
                if s.sleep >= 0:
                    if s.sleep == 0:
                        s.status = None
                    continue
            if c[0] == "skip":
                s.recharge = False
                continue
            hs, ho = s.hp, o.hp
            if s.status == "par" and rng is not None and rng.random() < 0.25:
                if trace is not None:
                    _tr(trace, a.turn + 1, s, o, "(마비로 못 움직임)", hs, ho)
                continue
            act(s, o, c[1], field, oc, 0.75 if (s.status == "par" and rng is None) else 1.0)  # 기대값 모드: 마비 25% → 피해 ×0.75
            if first is None:                     # 먼저 쓰러진 쪽이 진다(반동 동시 기절이면 맞은 쪽이 먼저)
                first = o if o.hp <= 0 else (s if s.hp <= 0 else None)
            if trace is not None:
                _tr(trace, a.turn + 1, s, o, s.b.D.move_name(c[1]["key"]), hs, ho)
        a.flinch = b.flinch = False
        a.turn += 1
        b.turn += 1
        for s, o in ((a, b), (b, a)):
            hs, ho = s.hp, o.hp
            end_of_turn(s, o, field)
            if first is None and s.hp <= 0:
                first = s
            if trace is not None and (hs != s.hp or ho != o.hp):
                _tr(trace, a.turn, s, o, "(턴 종료)", hs, ho)
        if field.wturns:
            field.wturns -= 1
            if field.wturns == 0:
                field.weather = None
        if field.tturns:
            field.tturns -= 1
            if field.tturns == 0:
                field.terrain = None
        if a.hp <= 0 or b.hp <= 0:
            break
    ra, rb = max(0.0, a.hp) / a.maxhp, max(0.0, b.hp) / b.maxhp
    if a.hp <= 0 and b.hp <= 0:
        return 0.5 if first is b else -0.5 if first is a else 0.0
    if b.hp <= 0:
        return 0.5 + 0.5 * ra
    if a.hp <= 0:
        return -(0.5 + 0.5 * rb)
    return max(-0.5, min(0.5, 0.5 * (ra - rb)))


def plans(b):
    """계획 후보 전부(기술 순서로 자르지 않는다 — 예전 out[:5] 는 뒤쪽 기술의 계획을 버렸다).
    기술이 4개라 많아야 ~9개: 때리기 / 기습 없이 / 버티기(회복·방어 먼저) / 쌓기 1·2회 / 상태이상 먼저."""
    out = [("atk", None, 0)]
    if COND_PRIORITY & set(b.moves):
        out.append(("atk", "nosucker", 0))     # 기습을 읽히는 경우(상대 변화기)에 대비해 기습 없이 때리는 계획
    if any(b.kinds[m] in ("heal", "protect") for m in b.moves):
        out.append(("atk", "sustain", 0))      # 회복 먼저·방어로 잔여 피해 벌기, 공격은 그다음
    for k in b.moves:
        kd = b.kinds[k]
        if kd == "setup":
            out.append(("setup", k, 1))
            if k not in ("belly-drum", "shell-smash"):
                out.append(("setup", k, 2))
        elif kd == "status":
            out.append(("status", k, 0))
    return list(dict.fromkeys(out))


W_NEUTRAL, W_SWITCH = 0.6, 0.2


def value(A, B, mc=0):
    """3:3 맥락의 1:1 값 = 정면 60% + A가 교체로 들어와 한 대 맞음 20% + B가 그렇게 들어옴 20%.
    기합의띠·옹골참·멀티스케일처럼 '만피 등장'에만 기대는 효과가 과대평가되지 않게 한다. 반대칭.
    mc>0 이면 확률 모드(명중·난수·급소·마비) 평균."""
    return (W_NEUTRAL * duel(A, B, mc=mc) + W_SWITCH * duel(A, B, pre_hit=True, mc=mc)
            - W_SWITCH * duel(B, A, pre_hit=True, mc=mc))


def duel(A, B, hpA=1.0, hpB=1.0, pre_hit=False, mc=0, seed=0):
    """계획 쌍 행렬의 하한·상한 평균 → A 입장 값. 반대칭: duel(A,B) = -duel(B,A) (pre_hit·HP 가 대칭일 때).
    mc>0 이면 칸마다 확률 모드로 mc 번 돌려 평균."""
    return duel_stats(A, B, hpA, hpB, pre_hit, mc, seed)[0]


def duel_stats(A, B, hpA=1.0, hpB=1.0, pre_hit=False, mc=0, seed=0):
    """(값, A 승률). 값 = 계획 행렬 게임의 혼합전략 균형값(안장점이면 순수전략 값).
    승률은 확률 모드에서만 의미가 있다(기대값 모드는 0/0.5/1). 균형 혼합전략으로 가중."""
    import random
    pa, pb = plans(A), plans(B)
    tie = A.stats[5] == B.stats[5]
    O, W = [], []
    for x in pa:
        row, wrow = [], []
        for y in pb:
            if mc:
                vs = []
                for n in range(mc):
                    rng = random.Random(seed * 100003 + n)
                    vs.append(simulate(A, B, x, y, hpA, hpB, pre_hit, rng.random() < 0.5 if tie else True, rng=rng))
                v = sum(vs) / mc
                w = sum(1.0 if t > 0.05 else 0.5 if t > -0.05 else 0.0 for t in vs) / mc
            else:
                v = simulate(A, B, x, y, hpA, hpB, pre_hit, True)
                if tie:
                    v = 0.5 * (v + simulate(A, B, x, y, hpA, hpB, pre_hit, False))
                w = 1.0 if v > 0.05 else 0.5 if v > -0.05 else 0.0
            row.append(v)
            wrow.append(w)
        O.append(row)
        W.append(wrow)
    i = max(range(len(pa)), key=lambda i: min(O[i]))
    j = min(range(len(pb)), key=lambda j: max(O[r][j] for r in range(len(pa))))
    lower, upper = min(O[i]), max(O[r][j] for r in range(len(pa)))
    if upper - lower <= 1e-9:                     # 안장점: 순수전략이 곧 해
        return lower, W[i][j]
    # 안장점이 없으면(예: 도깨비불 ↔ 기습 읽기) 혼합전략 균형값. 승률도 그 혼합으로 기대값.
    from .game import solve
    v, x, y = solve(O)
    w = sum(x[r] * y[c] * W[r][c] for r in range(len(pa)) for c in range(len(pb)))
    return v, w
