"""1:1 전투 엔진 — 레벨 50 싱글, 포켓몬 챔피언스 규칙.

능력치    HP = 종족값 + 75 + SP,  나머지 = ⌊(종족값 + 20 + SP) × 성격⌋   (SP 0~32, 합 66 · 개체값 31 가정)
데미지    ⌊⌊22·위력·A/D⌋/50⌋+2 × 날씨 × 필드 × 자속 × 상성 × 특성 × 도구 × 평균 난수(0.925)
턴 처리   우선도 → 스피드(랭크·스카프·마비·특성) → 행동 → 턴 종료(날씨·도구·상태이상)

전투 하나는 "계획"(그냥 때리기 / 기습 없이 / 버티기 / 쌓기 k회 후 / 상태이상 먼저) 쌍마다 끝까지 돌리고,
계획 행렬 게임의 혼합전략 균형값을 값 v ∈ [-1, 1] 로 쓴다. 이기면 +0.5 + 0.5×남은HP비율.

명중·난수·급소 세 가지 모드
  결정적  명중은 기술마다 빗나감을 누적해 0.5 에 이르는 차례에만 빗나감, 난수 0.925, 급소 없음(확정 급소기 제외)
  분기    결정적 규칙 위에, 한 판에서 명중 1번·문턱 타격(난수·급소로 KO 여부가 갈림) 2번을 갈래로 나눠 확률 가중 (기본)
  확률    명중·난수·급소·마비·잠듦·연속기 타수를 뽑아 N판 평균 (switch, pick --mc)
행동 결정은 명중·난수 결과를 미리 보지 않는다.

모델 밖: 교체, 스텔스록·압정, 하품·도발·앵콜·벽, 트릭룸, 공격기의 확률 부가효과(화상 10% 등).
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
SCREENS = {"reflect": "p", "light-screen": "s", "aurora-veil": "ps"}
FIELD_WEATHER = {"rain-dance": ("rain", "damp-rock"), "sunny-day": ("sun", "heat-rock"),
                 "sandstorm": ("sand", "smooth-rock"), "snowscape": ("snow", "icy-rock")}
FIELD_TERRAIN = {"grassy-terrain": "grassy", "psychic-terrain": "psychic", "electric-terrain": "electric",
                 "misty-terrain": "misty"}
SEC_STATUS = {"burn": "brn", "paralysis": "par", "poison": "psn", "freeze": "frz", "sleep": "slp"}
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
    if k in ("taunt", "yawn"):
        return "status"                                  # 도발·하품: 상태 계획으로(처음에 한 번)
    if k == "encore":
        return "encore"
    if k in SCREENS or k in FIELD_WEATHER or k in FIELD_TERRAIN:
        return "field"                                   # 벽·날씨·필드: 필드 계획으로
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
                 "types", "blade", "mega", "label", "kinds", "alt")

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
        self.alt = None      # 상대 대표 세트: 값을 못 매기는 기술 칸을 공격기로 바꾼 변형(meta.make_alt)

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
                 "charged", "protected", "protect_last", "wish", "cprob", "shed", "miss", "br", "acted",
                 "drowsy", "taunt", "encore", "encore_mv", "last", "last_kind", "scr_p", "scr_s", "sec", "field_done")

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
        self.br = None             # 분기 모드 Brancher(두 쪽이 같은 것을 공유)
        self.acted = False         # 이번 턴에 이미 행동했나(기습 실패 판정)
        self.drowsy = 0            # 하품: 0 이 되는 턴 끝에 잠듦
        self.taunt = 0             # 도발 남은 턴(변화기 금지)
        self.encore = 0            # 앙코르 남은 턴
        self.encore_mv = None
        self.last = None           # 직전에 쓴 기술과 그 분류(앙코르 대상)
        self.last_kind = None
        self.scr_p = 0             # 리플렉터(물리 반감) 남은 턴
        self.scr_s = 0             # 빛의장막(특수 반감) 남은 턴
        self.sec = {}              # 부가효과 누적(기대값·분기 모드): 효과별 0.5 에 이르면 발동
        self.field_done = False    # 필드 계획(벽·날씨·필드)을 이미 썼나

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
    ign_d = att.ability == "unaware"

    def stage(side, i, ignore, lo=-6, hi=6):
        """랭크 배율. 급소는 공격 쪽 하락(lo=0)과 방어 쪽 상승(hi=0)만 무시한다."""
        return 1.0 if ignore else STAGE[max(lo, min(hi, side.boost[i]))]

    a_lo = 0 if crit else -6                          # 급소: 공격 쪽 하락 무시
    d_hi = 0 if crit else 6                           # 급소: 방어 쪽 상승 무시(하락은 그대로)
    if k == "body-press":
        A = att.st(2, True) * stage(att, 2, ign_a, a_lo)
    elif k == "foul-play":
        A = dfd.st(1, True) * stage(dfd, 1, ign_d, a_lo)
    else:
        i = 1 if cat == "physical" else 3
        base = att.b.blade[i] if att.b.blade else att.st(i, True)          # 킬가르도는 공격할 때 블레이드폼
        A = base * stage(att, i, ign_a, a_lo)
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
    di = 2 if phys_def else 4
    Dv = dfd.st(di, True) * stage(dfd, di, ign_d, -6, d_hi)
    if phys_def and dab == "fur-coat":
        Dv *= 2
    if field.weather == "sand" and not phys_def and "rock" in dfd.types:
        Dv *= 1.5
    if field.weather == "snow" and phys_def and "ice" in dfd.types:
        Dv *= 1.5
    d = (int(int(22 * pw * A / max(1.0, Dv)) / 50) + 2) * ROLL
    if crit:
        d *= 1.5
    elif att.ability != "infiltrator" and ((cat == "physical" and dfd.scr_p) or (cat == "special" and dfd.scr_s)):
        d *= 0.5                                         # 리플렉터·빛의장막·오로라베일(급소·틈새포착은 무시)
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
    """기대값 모드에서 이번 사용이 맞는가: 빗나감 누적 + 이번 몫이 0.5 에 이르지 않으면 맞는다.
    부동소수점 오차(1−0.9 를 다섯 번 더하면 0.4999…)로 빗나갈 차례를 놓치지 않게 여유를 둔다."""
    return a >= 1.0 or s.miss.get(k, 0.0) + (1 - a) < 0.5 - 1e-9


class Brancher:
    """분기 모드: 한 판에서 명중 분기 acc 번·문턱(KO 여부가 난수·급소에 달린 타격) 분기 thr 번까지
    결과를 갈래로 나눈다. path 는 앞에서부터 고를 갈래 번호. 예산이 떨어지면 결정적 규칙으로 진행."""
    __slots__ = ("path", "i", "prob", "taken", "nopts", "acc", "thr", "tie")

    def __init__(self, path, acc=1, thr=2, tie=1):
        self.path, self.i, self.prob = path, 0, 1.0
        self.taken, self.nopts = [], []
        self.acc, self.thr, self.tie = acc, thr, tie

    def pick(self, kind, opts):
        if kind == "acc":
            if self.acc <= 0:
                return None
            self.acc -= 1
        elif kind == "tie":
            if self.tie <= 0:
                return None
            self.tie -= 1
        else:
            if self.thr <= 0:
                return None
            self.thr -= 1
        idx = self.path[self.i] if self.i < len(self.path) else 0
        self.taken.append(idx)
        self.nopts.append(len(opts))
        self.i += 1
        self.prob *= opts[idx][1]
        return opts[idx][0]


def outcome(v):
    """한 판 결과 → 승 1 / 패 0 / 끝나지 않음·동시 기절 0.5.
    승패가 난 판은 |v| ≥ 0.5 이고, 60턴 제한에 걸린 판은 |v| < 0.5 다. 예전에는 v > 0.05 를 승으로 세서
    HP 가 조금 앞선 미결 판까지 승으로 셌다."""
    if v >= 0.5 - 1e-9:
        return 1.0
    if v <= -0.5 + 1e-9:
        return 0.0
    return 0.5


def branch_value(run):
    """모든 갈래를 한 번씩 돌려 확률 가중 (값, 승률). run(br) → 값. 갈래는 많아야 2³=8."""
    total, win, stack = 0.0, 0.0, [[]]
    while stack:
        prefix = stack.pop()
        br = Brancher(prefix)
        v = run(br)
        total += br.prob * v
        win += br.prob * outcome(v)
        for j in range(len(prefix), len(br.taken)):
            for alt in range(1, br.nopts[j]):
                stack.append(br.taken[:j] + [alt])
    return total, win


def _threshold(s, o, mv, d):
    """분기 모드의 문턱 타격: KO 확률 p = (23/24)·P(난수 KO) + (1/24)·P(급소 난수 KO), 난수 0.85~1.00 균등.
    0<p<1 이면 KO 갈래(피해 = max(HP, 최대 난수 피해))와 비KO 갈래(비KO 구간 평균 피해)로 나눈다."""
    if s.br is None or n_hits(s, mv) > 1:
        return d
    if o.disguise or (o.hp >= o.maxhp and (o.item == "focus-sash" or o.ability == "sturdy")):
        return d                                       # 버티는 효과가 있으면 이번 타격으로는 KO 불가
    hp, raw = o.hp, d / ROLL

    def frac(x):                                       # 난수 r∈[0.85,1] 중 x·r ≥ hp 인 비율
        if x * 0.85 >= hp:
            return 1.0
        if x < hp:
            return 0.0
        return (1 - hp / x) / 0.15

    crit_ok = mv["key"] not in ALWAYS_CRIT and o.ability not in ("battle-armor", "shell-armor")
    p = frac(raw) * (23 / 24) + frac(raw * 1.5) / 24 if crit_ok else frac(raw)
    if p <= 1e-9 or p >= 1 - 1e-9:
        return d
    ko = s.br.pick("thr", [(True, p), (False, 1 - p)])
    if ko is None:
        return d
    if ko:
        return max(hp, raw)
    r_ko = min(1.0, hp / raw)
    return min(raw * (0.85 + r_ko) / 2, hp * (1 - 1e-9))


def roll_hit(s, k, a):
    """명중 판정 한 번(공격기·변화기 공통). 확률 모드는 난수, 분기 모드는 갈래, 기대값 모드는 빗나감 누적."""
    if s.rng is not None:
        return s.rng.random() < a
    if s.br is not None and a < 1.0:
        h = s.br.pick("acc", [(True, a), (False, 1 - a)])
        if h is not None:
            s.miss[k] = s.miss.get(k, 0.0) + (1 - a) - (0 if h else 1)   # 분기 결과로 누적도 갱신
            return h
    hit = will_hit(s, k, a)
    s.miss[k] = s.miss.get(k, 0.0) + (1 - a) - (0 if hit else 1)
    return hit


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
        # '잡는다' 판정은 맞았을 때 피해로. 이번에 빗나갈지는 행동을 정하는 쪽이 알 수 없으므로
        # (빗나감 누적·분기 결과를 미리 보지 않는다) 명중은 act() 에서만 판정한다.
        hit_d = d
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
    if k == "taunt":
        return (o.taunt == 0 and o.ability not in ("oblivious", "aroma-veil")
                and any(o.b.kinds.get(m) not in ("attack", "none") for m in o.b.moves))
    if k == "yawn":
        return (not o.status and not o.drowsy and o.ability not in ("insomnia", "vital-spirit", "sweet-veil")
                and not (field.terrain in ("electric", "misty") and grounded(o)))
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
    if s.encore and s.pp.get(s.encore_mv, 0) > 0:
        return ("move", D.MOVES[s.encore_mv])              # 앙코르: 같은 기술만
    kind, pm, n = plan
    taunted = s.taunt > 0                                  # 도발: 변화기(쌓기·회복·방어·상태이상·필드) 못 씀
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
    if not taunted and sum(max(0, x) for x in (o.boost[1], o.boost[3], o.boost[5])) >= 2:
        for k in s.b.moves:
            if s.b.kinds[k] == "phaze" and s.pp.get(k, 0) > 0:
                return ("move", D.MOVES[k])
    # 앙코르: 상대가 직전에 변화기(쌓기·회복·방어·상태이상·필드)를 썼으면 그 기술에 3턴 묶는다
    if not taunted and o.last and o.last_kind in ("setup", "heal", "protect", "status", "field", "encore") and not o.encore:
        for k in s.b.moves:
            if s.b.kinds[k] == "encore" and s.pp.get(k, 0) > 0:
                return ("move", D.MOVES[k])
    if taunted:
        mv, d, a = best_attack(s, o, field, avoid=avoid)
        return ("move", mv) if mv is not None else ("skip", None)
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
    if kind == "field" and not s.field_done and not s.locked:
        s.field_done = True                                # 벽·날씨·필드: 처음에 한 번
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


def _chance(s, tag, pct):
    """확률 p% 효과가 이번에 발동하나. 확률 모드는 난수, 결정적·분기 모드는 명중과 같은 누적 규칙:
    p 를 더해 가다 0.5 에 이르는 차례에 발동하고 1 을 뺀다 — 30% 는 2번째에 처음, 장기적으로 정확히 30%."""
    p = min(1.0, pct / 100)
    if s.rng is not None:
        return s.rng.random() < p
    acc = s.sec.get(tag, 0.0) + p
    hit = acc >= 0.5 - 1e-9
    s.sec[tag] = acc - (1 if hit else 0)
    return hit


def _sec_status_ok(s, o, st, field):
    """부가효과 상태이상이 걸릴 수 있나(변화기용 _status_ok 와 달리 황금몸·매직미러는 막지 못한다)."""
    if o.status or o.hp <= 0 or o.ability in ("purifying-salt", "comatose"):
        return False
    if field.terrain == "misty" and grounded(o):
        return False
    if st == "brn":
        return "fire" not in o.types and o.ability not in ("water-veil", "water-bubble", "thermal-exchange")
    if st == "par":
        return "electric" not in o.types and o.ability != "limber"
    if st == "psn":
        return s.ability == "corrosion" or ("poison" not in o.types and "steel" not in o.types and o.ability != "immunity")
    if st == "frz":
        return "ice" not in o.types and o.ability != "magma-armor" and weather_for(field, o) != "sun"
    if st == "slp":
        return o.ability not in ("insomnia", "vital-spirit", "sweet-veil") and not (field.terrain == "electric" and grounded(o))
    return False


def _secondary(s, o, mv, field, dealt):
    """공격기의 부가효과(C-3). 100% 는 바로, 그 밖은 _chance 규칙.
    우격다짐은 부가효과 없음, 인분·방진망토는 상대 쪽 효과를 막음, 하늘의은총은 확률 2배."""
    if dealt <= 0 or s.ability == "sheer-force":
        return
    meta, k = mv["meta"], mv["key"]
    mult = 2 if s.ability == "serene-grace" else 1
    shielded = o.ability == "shield-dust" or o.item == "covert-cloak"
    # 상태이상
    st = SEC_STATUS.get(meta.get("ailment"))
    c = (meta.get("ailmentChance") or 0) * mult
    if st and c > 0 and not shielded and _sec_status_ok(s, o, st, field):
        if c >= 100 or _chance(s, f"{k}:ail", c):
            if o.item == "lum-berry":
                o.item = None
            else:
                o.status = st
                if st == "slp":
                    o.sleep = s.rng.randint(1, 3) if s.rng is not None else 2
    # 풀죽음: 내가 먼저 움직였을 때만 의미가 있다(속이기는 따로 처리)
    fc = (meta.get("flinchChance") or 0) * mult
    if fc > 0 and k != "fake-out" and not shielded and not o.acted and o.hp > 0 and o.ability != "inner-focus":
        if fc >= 100 or _chance(s, f"{k}:flinch", fc):
            o.flinch = True
    # 확률 랭크 변화(100% 는 act() 에서 처리)
    sc = (meta.get("statChance") or 0) * mult
    ch = mv["stat_changes"]
    if 0 < (meta.get("statChance") or 0) < 100 and ch:
        up = all(x["change"] > 0 for x in ch)
        if up:                                             # 자기 강화(코멧펀치 공격 +1 등)
            if _chance(s, f"{k}:stat", sc):
                _apply_stat(s, ch)
        elif not shielded and o.hp > 0 and o.ability not in ("clear-body", "white-smoke", "full-metal-body"):
            if _chance(s, f"{k}:stat", sc):                # 상대 약화(문포스 특공 −1 등)
                _apply_stat(s if o.ability == "mirror-armor" else o, ch)


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
    s.last, s.last_kind = k, kind                          # 앙코르 대상
    if s.item == "choice-scarf" and not s.locked and kind == "attack":
        s.locked = k
    if kind == "protect":
        s.protected = True
        if k == "kings-shield" and s.b.blade is not None:
            s.blade = False                                # 킬가르도: 실드폼으로 돌아간다
        return
    # 상대가 방어 중이면 공격·상태이상은 막힌다(모으기 첫 턴·자기 강화는 통과)
    if o.protected and kind in ("attack", "status", "encore") and not (kind == "attack" and k in CHARGE and s.charging != k):
        shield = o_action[1]["key"] if (o_action and o_action[0] == "move") else None
        if kind == "attack" and "contact" in mv["traits"]:
            if shield == "spiky-shield" and s.ability != "magic-guard":
                s.hp -= s.maxhp / 8                        # 니들가드: 접촉하면 1/8
            elif shield == "kings-shield":
                s.boost[1] = max(-6, s.boost[1] - 1)       # 킹실드: 접촉하면 공격 −1
            elif shield == "silk-trap":
                s.boost[5] = max(-6, s.boost[5] - 1)       # 실크트랩: 스피드 −1
            elif shield == "baneful-bunker" and not s.status and not ({"poison", "steel"} & set(s.types)):
                s.status = "psn"                           # 토치카: 독
            elif shield == "burning-bulwark" and not s.status and "fire" not in s.types:
                s.status = "brn"                           # 불꽃방패: 화상
        return
    if kind == "attack":
        if k in CHARGE and s.charging != k and not (CHARGE[k] and weather_for(field, s) == CHARGE[k]):
            s.charging = k
            if k in ("meteor-beam", "electro-shot"):
                s.boost[3] = min(6, s.boost[3] + 1)
            return
        s.charging = None
        if k in ("sucker-punch", "thunderclap") and (o_action is None or o_action[0] != "move"
                                                     or o_action[1]["cat"] == "status" or o.acted):
            return                                         # 기습: 상대가 공격하지 않거나 이미 움직였으면 실패
        if k == "fake-out" or k == "first-impression":
            if s.turn > 0:
                return
        if s.b.blade is not None:
            s.blade = True
        if s.ability in ("protean", "libero") and not s.protean_used:
            s.types = [move_type(s, mv, field)]            # 막는 타입도 바뀐다
            s.protean_used = True
        # 명중: 기대값 모드는 피해에 명중률을 곱하지 않고(곱하면 확정 1타가 1타가 아니게 된다)
        # 기술마다 빗나감을 누적해 0.5 에 이르는 차례에만 빗나간다. 확률 모드는 난수.
        a = _acc(mv, s, field)
        if s.charged and move_type(s, mv, field) == "electric":
            s.charged = False                              # 충전은 한 번 쓰면 끝
        if not roll_hit(s, k, a):
            # 빗나가면 부가효과(용성군 특공 하락, 탁쳐서떨구기, 반동 턴, 흑안개류, 흡수·반동)는 없다
            if k in ("high-jump-kick", "jump-kick", "supercell-slam") and s.ability != "magic-guard":
                s.hp -= s.maxhp / 2                        # 무릎차기류는 빗나가면 최대 HP 1/2 자해
            return
        d = damage(s, o, mv, field) * mult
        if d <= 0:
            return                                         # 무효 — 부가효과도 없다
        if s.rng is None:
            d = _threshold(s, o, mv, d)                    # 분기 모드면 문턱 타격을 KO/비KO 갈래로
        if s.rng is not None:
            r = s.rng
            d *= r.uniform(0.85, 1.0) / ROLL
            if k not in ALWAYS_CRIT and o.ability not in ("battle-armor", "shell-armor") and r.random() < 1 / 24:
                d *= 1.5
            # 연속기 타수: damage() 는 기대 타수(2~5회 3.1타)로 계산하므로 확률 모드에서는 실제 타수를 뽑는다
            lo, hi = mv["meta"].get("minHits"), mv["meta"].get("maxHits")
            if k in HIT_POWER:                             # 트리플악셀: 2·3타도 타마다 명중, 빗나가면 거기서 끝
                pw = 1
                for step in (2, 3):
                    if r.random() >= a:
                        break
                    pw += step
                d *= pw / 6
            elif lo and hi and lo != hi and s.ability != "skill-link":
                n = r.choices([2, 3, 4, 5], weights=[35, 35, 15, 15])[0]
                d *= n / 3.1
        rb = RESIST_BERRY.get(o.item)
        hp_before = o.hp
        dealt = _take(o, d, field, hits=n_hits(s, mv))
        # 맞은 타수: 도중에 쓰러지면 쓰러뜨린 타까지. 트리플악셀·트리플킥은 타마다 위력이 1:2:3 이다.
        nh = n_hits(s, mv)
        landed = nh
        if nh > 1 and o.hp <= 0 and d > 0:
            if k in HIT_POWER:
                cum = [1 / 6, 3 / 6, 1.0]                  # 20, 20+40, 20+40+60 (÷120)
                landed = next((i + 1 for i, c in enumerate(cum) if d * c >= hp_before), 3)
            else:
                landed = min(nh, max(1.0, math.ceil(hp_before / (d / nh))))
        if dealt > 0 and o.hp > 0 and o.ability == "electromorphosis":
            o.charged = True
        if dealt > 0 and o.hp > 0 and mv["cat"] == "physical" and o.ability == "weak-armor":
            n_wa = max(1, int(round(landed)))              # 깨어진갑옷: 맞은 타마다 방어 −1, 스피드 +2
            o.boost[2] = max(-6, o.boost[2] - n_wa)
            o.boost[5] = min(6, o.boost[5] + 2 * n_wa)
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
        # 접촉 반격은 맞은 타마다(landed 는 위에서 계산)
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
        _secondary(s, o, mv, field, dealt)                 # 확률 부가효과(화상·마비·결빙·풀죽음·랭크 변화)
        if o.status == "frz" and dealt > 0 and (move_type(s, mv, field) == "fire" or k in ("scald", "steam-eruption")):
            o.status = None                                # 불꽃 기술·열탕에 맞으면 녹는다
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
        if not _status_ok(s, o, mv, field):
            return
        if not roll_hit(s, k, _acc(mv, s, field)):         # 변화기도 공격기와 같은 명중 규칙(도깨비불 85% 등)
            return
        if k == "taunt":
            o.taunt = 3
            return
        if k == "yawn":
            o.drowsy = 2                                   # 다음 턴 끝에 잠듦
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
    elif kind == "encore":
        if o.last and o.last != "encore" and not o.encore and o.ability != "aroma-veil":
            o.encore, o.encore_mv = 3, o.last
    elif kind == "field":
        if k in SCREENS:
            if k == "aurora-veil" and field.weather != "snow":
                return                                     # 오로라베일은 눈일 때만
            t = 8 if s.item == "light-clay" else 5
            if "p" in SCREENS[k]:
                s.scr_p = t
            if "s" in SCREENS[k]:
                s.scr_s = t
        elif k in FIELD_WEATHER:
            w, rock = FIELD_WEATHER[k]
            field.weather, field.wturns = w, (8 if s.item == rock else 5)
        else:
            field.terrain, field.tturns = FIELD_TERRAIN[k], (8 if s.item == "terrain-extender" else 5)


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
    if s.drowsy:                                           # 하품: 잠듦. 실제로는 교체로 피하므로 '한 턴 손해'로 보고 1턴만
        s.drowsy -= 1
        if s.drowsy == 0 and not s.status and s.hp > 0:
            s.status, s.sleep = "slp", 1
    if s.taunt:
        s.taunt -= 1
    if s.encore:
        s.encore -= 1
        if not s.encore:
            s.encore_mv = None
    if s.scr_p:
        s.scr_p -= 1
    if s.scr_s:
        s.scr_s -= 1
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
             max_turns=MAX_TURNS, trace=None, rng=None, br=None):
    """A 입장 결과 ∈ [-1,1]. pre_hit=True 면 B 가 교체 들어오는 A 에게 공짜 한 방을 먼저 넣는다.
    trace 에 리스트를 주면 턴별 행동과 HP 변화를 적는다(디버그용).
    rng(random.Random) 를 주면 명중·난수·급소·마비·잠듦 턴을 뽑는 확률 모드, 없으면 기대값 모드.

    종료 값: 한쪽이 쓰러지면 승자 +0.5 + 0.5×남은HP비율. max_turns 턴(PP 가 다 떨어지면 발버둥)까지
    안 끝나면 0.5×(내 HP비율 − 상대 HP비율), 범위 ±0.5 — 회복전은 '버틴 쪽이 조금 유리' 이상으로 치지 않는다."""
    a, b = _side(A, B, hpA), _side(B, A, hpB)
    a.rng = b.rng = rng
    a.br = b.br = br
    first = None
    ties = 0
    a.plan_left = planA[2] if planA[0] == "setup" else 0
    b.plan_left = planB[2] if planB[0] == "setup" else 0
    field = Field()
    _setup_field(a, b, field)
    if pre_hit:
        b.turn = 1                                         # 교체 등장에 대한 공짜 한 방은 첫 턴 기술(속이기 등)이 아니다
        mv, d, acc = best_attack(b, a, field)
        if mv is not None:
            act(b, a, mv, field, None)
        a.flinch = False
    for _ in range(max_turns):
        ca = choose(a, b, field, planA)
        cb = choose(b, a, field, planB)
        pa = priority(a, ca[1], field) if ca[0] == "move" else 0
        pb = priority(b, cb[1], field) if cb[0] == "move" else 0
        if pa != pb:
            a_first = pa > pb
        else:
            sa, sb = speed(a, field), speed(b, field)
            if sa != sb:
                a_first = sa > sb
            else:
                # 스피드 동률은 동률이 생길 때마다 50:50. 확률 모드는 동전, 분기 모드는 한 번 갈래, 결정적 모드는 번갈아.
                # (예전에는 경기 중 랭크·날씨로 생긴 동률에서 항상 A 가 먼저였다)
                ch = None
                if rng is not None:
                    ch = rng.random() < 0.5
                elif br is not None:
                    ch = br.pick("tie", [(True, 0.5), (False, 0.5)])
                if ch is None:
                    ch = tie_a_first if ties % 2 == 0 else not tie_a_first
                ties += 1
                a_first = ch
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
            if s.status == "frz":                          # 결빙: 행동 전 20% 로 녹는다(결정적 모드는 누적 규칙)
                if _chance(s, "_thaw", 20):
                    s.status = None
                else:
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
            s.acted = True
            if first is None:                     # 먼저 쓰러진 쪽이 진다(반동 동시 기절이면 맞은 쪽이 먼저)
                first = o if o.hp <= 0 else (s if s.hp <= 0 else None)
            if trace is not None:
                _tr(trace, a.turn + 1, s, o, s.b.D.move_name(c[1]["key"]), hs, ho)
        a.flinch = b.flinch = False
        a.acted = b.acted = False
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
        elif kd == "field":
            out.append(("field", k, 0))           # 벽·날씨·필드를 먼저 깔고 싸우기
    return list(dict.fromkeys(out))


W_NEUTRAL, W_SWITCH = 0.6, 0.2


BRANCH = True   # 기본은 분기 모드(명중 1 + 문턱 2 갈래). 세트 최적화는 속도 때문에 branch=False 로 부른다.


def value(A, B, mc=0, branch=None):
    """3:3 맥락의 1:1 값 = 정면 60% + A가 교체로 들어와 한 대 맞음 20% + B가 그렇게 들어옴 20%.
    기합의띠·옹골참·멀티스케일처럼 '만피 등장'에만 기대는 효과가 과대평가되지 않게 한다. 반대칭.
    mc>0 이면 확률 모드(명중·난수·급소·마비) 평균. branch 는 분기 모드(None 이면 BRANCH)."""
    return (W_NEUTRAL * duel(A, B, mc=mc, branch=branch) + W_SWITCH * duel(A, B, pre_hit=True, mc=mc, branch=branch)
            - W_SWITCH * duel(B, A, pre_hit=True, mc=mc, branch=branch))


def duel_bayes(A, Bs, ps, pre=None, mc=0, branch=None):
    """상대가 여러 세트(유형) 중 하나인데 나는 모르는 1:1 — 내 계획은 하나, 상대는 유형별로 대응하는 베이지안 게임.
    pre=None 정면, 'A' 는 B 가 교체 들어오는 A 에게 공짜 한 방, 'B' 는 A 가 B 에게 공짜 한 방."""
    from .game import solve_bayes
    Ms = []
    for B in Bs:
        if pre == "B":
            O, _ = plan_matrix(B, A, pre_hit=True, mc=mc, branch=branch)
            Ms.append([[-O[j][i] for j in range(len(O))] for i in range(len(O[0]))])   # B 입장 → A 입장(전치·부호)
        else:
            Ms.append(plan_matrix(A, B, pre_hit=(pre == "A"), mc=mc, branch=branch)[0])
    return solve_bayes(Ms, ps)[0]


def value_vs(A, B, mc=0, branch=None, f=None):
    """상대 B 에 대한 값. B 가 시뮬이 값을 못 매기는 기술(스텔스록 등)을 들고 있으면 그 칸을 공격기로 바꾼 변형(alt)과
    반반의 두 유형으로 본다. 예전처럼 두 게임을 따로 풀어 평균하면 내가 상대 세트를 아는 것처럼 대응하게 되므로,
    내 계획은 하나로 두고 상대만 세트별로 대응하는 베이지안 게임으로 푼다(값이 조금 보수적이 된다).
    f=duel 이면 정면 한 항만(세트 탐색의 빠른 모드)."""
    f = f or value
    if B.alt is None:
        return f(A, B, mc=mc, branch=branch)
    Bs, ps = [B, B.alt], [0.5, 0.5]
    if f is duel:
        return duel_bayes(A, Bs, ps, None, mc, branch)
    return (W_NEUTRAL * duel_bayes(A, Bs, ps, None, mc, branch) + W_SWITCH * duel_bayes(A, Bs, ps, "A", mc, branch)
            + W_SWITCH * duel_bayes(A, Bs, ps, "B", mc, branch))


def duel(A, B, hpA=1.0, hpB=1.0, pre_hit=False, mc=0, seed=0, branch=None):
    """계획 쌍 행렬 게임의 값 → A 입장 값. 반대칭: duel(A,B) = -duel(B,A) (pre_hit·HP 가 대칭일 때).
    mc>0 이면 칸마다 확률 모드로 mc 번 돌려 평균."""
    return duel_stats(A, B, hpA, hpB, pre_hit, mc, seed, branch)[0]


def plan_matrix(A, B, hpA=1.0, hpB=1.0, pre_hit=False, mc=0, seed=0, branch=None):
    """계획 행렬 (O, W): O[i][j] = A 가 계획 i, B 가 계획 j 일 때 A 입장 값, W 는 A 승률.
    칸 하나의 값: 확률 모드(mc>0)는 mc 판 평균, 분기 모드는 명중 1·문턱 2·동률 1 갈래의 확률 가중 평균,
    둘 다 아니면 결정적 한 판(시작부터 동률이면 두 순서 평균)."""
    if branch is None:
        branch = BRANCH
    import random
    pa, pb = plans(A), plans(B)
    eff = lambda X: X.stats[5] * (1.5 if (X.item == "choice-scarf" and not X.mega) else 1.0)
    tie = eff(A) == eff(B)
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
                w = sum(outcome(t) for t in vs) / mc
            elif branch:
                v, w = branch_value(lambda br: simulate(A, B, x, y, hpA, hpB, pre_hit, True, br=br))
            else:
                v = simulate(A, B, x, y, hpA, hpB, pre_hit, True)
                if tie:
                    v = 0.5 * (v + simulate(A, B, x, y, hpA, hpB, pre_hit, False))
                w = outcome(v)
            row.append(v)
            wrow.append(w)
        O.append(row)
        W.append(wrow)
    return O, W


def duel_stats(A, B, hpA=1.0, hpB=1.0, pre_hit=False, mc=0, seed=0, branch=None):
    """(값, A 승률). 값 = 계획 행렬 게임의 혼합전략 균형값(안장점이면 순수전략 값).
    승률은 확률·분기 모드에서 의미가 있고(미결·동시 기절은 0.5), 균형 혼합전략으로 가중."""
    O, W = plan_matrix(A, B, hpA, hpB, pre_hit, mc, seed, branch)
    pa, pb = range(len(O)), range(len(O[0]))
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
