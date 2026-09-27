# 코드 리뷰 — 전문 개발자 기준 (2026-09-27)

- **대상**: 최신 버전 7e610b4("챔피언스 룰 반영, 특성 추가, 역할별 상대 세트"). 이 브랜치에 병합해서 봤습니다.
- **범위**: `champions/` 패키지(Python 5,502줄 + HTML 템플릿), 저장소 구성, 의존성
- **방법**: 코드를 직접 읽고, 도구로 측정했습니다(ruff, radon, coverage, cProfile). 의심 가는 동작은 실행해서 재현했습니다.
- 모델의 도메인 정확도와 방법론은 [MODEL_REVIEW.md](MODEL_REVIEW.md), [METHODOLOGY_REVIEW.md](METHODOLOGY_REVIEW.md), [GAME_RULES_REVIEW.md](GAME_RULES_REVIEW.md)에서 다뤘습니다. 이 문서는 **코드 품질**만 봅니다.

## 총평

**기능과 도메인 정확도는 빠르게 좋아지고 있습니다.** 앞선 검토의 지적 대부분(지구력, 마비 12.5%, 분기 모드, 부가효과, 베이지안 게임 등)이 반영됐고, 회귀 테스트 26개도 생겼습니다.

**반면 구조, 테스트, 저장소 관리는 아직 "개인 연구 스크립트" 수준입니다.** 기능이 늘수록 비용이 커지는 형태라, 지금이 구조를 정리할 시점입니다. 가장 큰 위험은 다음 네 가지입니다.

1. **핵심 함수의 복잡도가 한계를 넘었습니다.** `act()`는 순환 복잡도 174, `damage()`는 157이고, engine.py의 유지보수성 지수는 0입니다.
2. **같은 규칙이 여러 곳에 구현되어 이미 서로 어긋납니다.** 미스트필드에서 부가효과로는 마비가 막히는데, 정전기 접촉으로는 걸립니다.
3. **커밋된 캐시를 pickle 허용 모드로 읽습니다.** 캐시 파일이 바뀌면 임의 코드가 실행될 수 있습니다.
4. **추천을 결정하는 층의 테스트 커버리지가 0%입니다.** team, pick, matrix, pipeline, 입력 파서, CLI가 해당합니다.

## 측정 지표

| 항목 | 값 | 기준·해석 |
|---|---|---|
| 코드 규모 | 5,502줄(engine.py 1,642) | 첫 검토(a545c41, 4,197줄) 이후 약 30% 증가 |
| ruff 기본 규칙 | 33건 | 한 줄 여러 문장 9, 파일 중간 import 6, 람다 대입 6, 미사용 import 3 등 |
| ruff 버그 성향 규칙(B·SIM·PERF·S 등) | 62건 | 실제 결함은 아래 [2-5](#2-5) |
| 순환 복잡도(CC) | `act` **174**, `damage` **157**, `choose` 89, `_optimize_arch` 73, `Data.__init__` 59, `simulate` 54, `end_of_turn` 44 | 흔히 쓰는 상한은 10~15. 15를 넘는 함수·메서드 31개, 10을 넘는 것 49개 |
| 유지보수성 지수(radon MI) | engine.py **0.0**, sets.py **0.0**, `__main__.py` 4.1 | 최저 등급 |
| 테스트 | `selftest` 26/26 통과 | |
| 커버리지 | 전체 **39%**. engine 74%, meta 89%, game 98%, sets 14% | `__main__`·team·pick·matrix·pipeline·textio·ui·audit은 **0%** |
| 성능 | `duel` 결정적 1.8 ms · 분기 2.6 ms, `value` 6.4 ms, `value_vs` **10.4 ms/쌍** | 471 카드 × 340 상대 ≈ 16만 쌍 ≈ **27 CPU분** |
| 줄바꿈 | 4개 파일 CRLF, 나머지 LF | engine.py 수정이 "파일 전체 교체"(+1,642/−1,173)로 보임 |
| 저장소 | .git 23 MB, 처리 캐시 폴더 7개 커밋, out/ 72개 파일 | `index.html`은 `out/pick_board.html`의 사본 |

---

## 1. 설계·구조

### 1-1. 거대 함수와 if 사슬 — 높음

- `act()`(220줄), `damage()`(171줄), `choose()`(90줄)는 특성·도구·기술 효과를 `if o.ability == "…"`로 한 함수 안에 계속 덧붙이는 구조입니다. 특성 하나를 넣을 때마다 이 함수들을 고쳐야 합니다(개방-폐쇄 원칙 위반).
- 이번 버전에서도 지구력, 하바네로분출, 정의의마음, 압박감, 결빙, 부가효과가 `act()`에 추가되어 CC가 계속 오르고 있습니다.
- **제안**
  - 효과별 훅 테이블(registry)로 나눕니다. 예: `ABILITY_HOOKS["stamina"] = Hooks(on_hit=...)`, `ITEM_HOOKS["rocky-helmet"] = Hooks(on_contact=...)`.
  - `damage()`는 "기본 피해 → 보정 계수 목록을 곱하는" 순수 함수로 바꾸면, 보정마다 단위 테스트를 둘 수 있습니다.

### 1-2. 같은 규칙의 중복 구현 → 이미 불일치 — 높음

- **상태이상 면역 판정이 세 곳에 따로 있습니다**: `_status_ok`(변화기), `_sec_status_ok`(부가효과), `_contact_reaction`의 `immune`(접촉 특성).
- **재현한 불일치**: 미스트필드에서 땅에 있는 한카리아스가 정전기 상대를 접촉했을 때입니다.
  - 부가효과 경로: `_sec_status_ok(..., "par", 미스트필드)` = False(막힘)
  - 접촉 특성 경로: 공격자가 **마비됨**. `_contact_reaction`은 `field`를 인자로 받지도 않습니다.
- **확률을 누적하는 구현도 네 가지**입니다.
  - 명중: `will_hit`와 `miss`의 가산 누적
  - 부가효과: `_chance`의 가산 누적
  - 접촉 특성: `cprob = 1 − (1−cprob)·0.7`
  - 탈피: `shed = 1 − (1−shed)·0.7`

  30% 효과가 경로에 따라 발동하는 차례와 장기 빈도가 서로 다릅니다.
- **제안**: `can_inflict(target, status, source, field)` 하나와 `Chance.roll(side, tag, p)` 하나로 합치고, 모든 경로가 이 둘을 부르게 합니다.

### 1-3. 문자열로 표현한 타입 — 중간

- 상태이상(`"brn"`, `"par"`, `"tox"`), 기술 분류(`"attack"`, `"setup"`…), 계획(`("atk", "nosucker", 0)`처럼 자리로 의미가 정해지는 튜플)이 모두 문자열입니다. 오타가 나도 조용히 "해당 없음"으로 지나갑니다.
- `Side`는 속성이 51개인 "신 객체"입니다.
- **제안**
  - `enum.StrEnum`(Status, MoveKind)을 씁니다.
  - 계획은 `@dataclass(frozen=True) class Plan: kind; move; count`로 바꿉니다.
  - `Side`는 하위 상태로 나눕니다: 지속 상태(status·sleep·tox), 휘발 상태(taunt·encore·drowsy·flinch), 필드 효과(scr_p·scr_s).

### 1-4. `Build`에 나중에 붙이는 속성 — 중간

- `Build.alt`, `roles`, `variants`는 생성 후에 `meta.py`가 붙입니다. 같은 `Build`가 어디서 만들어졌는지에 따라 `value_vs()` 결과가 달라지는 **시간적 결합**입니다.
- **제안**: `Build`는 불변 값 객체로 두고, 상대 쪽 불확실성은 `OpponentModel(builds, probs)`처럼 별도 타입으로 넘깁니다.

### 1-5. CLI 안의 업무 로직 — 중간

- `__main__.py`는 614줄이고 함수 안 import가 40개입니다. 순환 import를 피하려는 흔적입니다.
- `cmd_moves()`(117줄) 안에 도구 중복 해소 알고리즘이 있고, `cmd_team()`(98줄) 안에 동률 판정·추천 규칙이 있습니다. 둘 다 테스트할 수 없습니다(커버리지 0%).
- **제안**: 이 로직을 `team.py`·`sets.py`의 함수로 옮깁니다. CLI는 "인자 → 함수 호출 → 출력"만 맡깁니다.

### 1-6. 전역 상태 — 중간

- `data.load()`가 `lru_cache` 싱글턴이라 **항상 최신 수집본**만 씁니다. 이전 날짜로 결과를 재현하거나, 테스트에서 고정 데이터를 넣을 수 없습니다. `Data(day_dir)` 인자는 있지만 CLI에서 쓸 수 없습니다.
- `matrix._W`, `pipeline._E`는 프로세스 전역 딕셔너리입니다.
- `BRANCH`, `W_NEUTRAL`, `W_SWITCH`, `LAMBDA`는 모듈 상수인데 사실상 설정값입니다. 민감도 분석을 하려면 전역을 바꾸거나 계산을 복제해야 합니다.
- **제안**: `@dataclass Config`(branch, w_switch, lam, date…)를 만들어 계산 함수에 인자로 넘기고, CLI에 `--date`를 둡니다.

---

## 2. 정확성·견고성

### 2-1. 문서와 코드의 불일치 — 높음 (주석이 명세 역할을 하는 코드라서)

- `simulate()` docstring은 "끝나지 않으면 0.5×(HP 비율 차)"라고 하지만, 코드는 `return 0.0`입니다(1503행).
- engine.py 모듈 docstring의 "모델 밖: … 하품·도발·앵콜·벽 … 공격기의 확률 부가효과"는 이미 구현된 것들입니다.
- `_contact_reaction` docstring의 누적 규칙 설명은 `_chance`와 다릅니다([1-2](#1-2)).

### 2-2. 입력 검증 없음 — 높음

`textio.parse_party`에 넣어 본 결과입니다.

| 입력 | 결과 |
|---|---|
| `마스카나 \| 고집 \| 32/32/32/32/32/32` | **통과**(SP 합 192, 규칙은 한 칸 ≤32·합 ≤66) |
| `마스카나 \| 고집 \| 0/40/0/0/0/0` | **통과**(한 칸 40) |
| `… \| 트릭플라워, 하이드로펌프` | **통과**(마스카나는 배울 수 없는 기술) |
| `한카리아스 @ 구애머리띠` | 오류(챔피언스에 없는 도구) — 올바름 |
| `마스카나 \| 고짐`(성격 오타) | "**기술**을 찾을 수 없음: 고짐" — 틀린 메시지 |

불가능한 세트가 조용히 계산되면 사용자는 결과가 틀린 줄 모릅니다. SP 범위·합, 배울 수 있는 기술, 폼과 스톤 조합을 파서에서 검증하고, 칸의 종류를 추정하지 말고 모호하면 되묻는 오류 메시지를 줘야 합니다.

### 2-3. 원자적이지 않은 캐시 쓰기 — 중간

- `optimize_pool`은 10종마다 `sets.json`을 `write_text`로 통째로 덮어쓰고, `np.savez_compressed`도 대상 파일에 바로 씁니다.
- 20~30분 걸리는 prep이 쓰는 도중에 중단되면 손상된 파일이 남고, 다음 실행은 `json.loads`에서 멈춥니다.
- **제안**: 임시 파일에 쓰고 `os.replace()`로 교체합니다.

### 2-4. 부분 수집본을 조용히 사용 — 중간

- `latest_dir()`는 `dex.json`만 있으면 그 날짜를 최신으로 고릅니다. 수집이 중간에 끊기면(포켓몬 파일 일부만 있는 상태) 불완전한 데이터로 분석합니다.
- **제안**: 수집이 끝나면 `manifest.json`(파일 수·해시)을 쓰고, 이 파일이 있는 날짜만 고릅니다.

<a id="2-5"></a>
### 2-5. 린트가 잡은 실제 결함 — 낮음~중간

| 위치 | 내용 |
|---|---|
| `pick.py:107` | 계산한 `P`를 쓰지 않음(낭비이거나 의도한 사용이 빠짐) |
| `team.py:148` | `for combo in …` 안에서 `combo`를 다시 대입 |
| `__main__.py:177` | `with` 없는 `open()` — Windows에서 파일이 잠긴 채 남을 수 있음 |
| `__main__.py:609` | `except KeyError` 안에서 `raise SystemExit(...)`에 `from` 없음(원래 추적 정보 손실) |
| `engine.py:1615` | 루프 변수 `x`, `y`를 잡은 람다. 지금은 바로 호출해서 안전하지만, 나중에 호출하도록 바뀌면 버그. `functools.partial`로 묶는 것이 안전 |
| `__main__.py:18`, `pick.py:11`, `selftest.py:10` | 미사용 import |

---

## 3. 보안

### 3-1. `np.load(allow_pickle=True)` — 중간

- `pipeline.py` 172·186행은 **저장소에 커밋된** `matrix.npz`·`parts.npz`를 pickle 허용 모드로 읽습니다. 누군가 캐시 파일을 바꿔 커밋하거나 공유 폴더에서 받으면, 로드하는 순간 임의 코드가 실행될 수 있습니다.
- 카드·상대 ID 배열만 `dtype=object`라서 pickle이 필요합니다. ID를 문자열 배열(`dtype="U"`)이나 별도 JSON으로 저장하고 `allow_pickle=False`로 읽으면 됩니다.

### 3-2. HTML에 JSON을 그대로 삽입 — 낮음 (지금은 안전, 잠재 위험)

- `ui.py` 66행은 `json.dumps(payload)`를 `<script>` 안에 문자열 치환으로 넣습니다. 데이터(외부 op.gg 출처의 이름·설명)에 `</script>`가 들어오면 스크립트 밖으로 빠져나갑니다(XSS).
- `json.dumps(...).replace("</", "<\\/")`로 막고, U+2028/2029도 이스케이프합니다.
- `innerHTML` 7곳은 `esc()`를 쓰거나 숫자·고정 문자열만 넣어서 현재는 안전합니다.

### 3-3. API 키 — 양호

- 키는 환경변수 → `secret.env` 순서로 읽고, `.gitignore`에 등록되어 있습니다.
- 다만 키 파일을 `legacy_v5/`까지 찾아 들어갑니다. 한 곳으로 줄이는 편이 안전합니다.

---

## 4. 테스트

- **좋아진 점**: `selftest.py`로 과거 버그의 회귀 테스트 26개가 생겼습니다. 각 항목이 무엇을 지키는지 이름이 분명합니다.
- **문제**
  1. 테스트가 **모듈 import 시점의 전역 코드**로 실행됩니다. pytest로 찾거나, 골라서 돌리거나, 병렬로 돌릴 수 없습니다.
  2. `load()`로 **최신 수집본**을 씁니다. 새 데이터를 받으면 테스트 기대값이 흔들릴 수 있어서, 작은 고정 픽스처가 필요합니다.
  3. 결정 계층의 커버리지가 0%입니다.
- **우선 테스트할 곳**
  - `textio.parse_line`(CC 27, 0%): 위 2-2의 입력들
  - `TeamSearch.valid`·`search`(0%): 종·도구 중복, 메가 1장 제약
  - `pick.advise`(0%): 3×3 이하 퇴화 행렬, 메가 확정·미확정
  - `pipeline`의 지문 캐시 무효화
  - `game.solve`·`solve_bayes`의 경계(1×n, 모든 값 동일, 음수만)
  - `damage()` 골든 테스트: 표준 데미지 계산식으로 구한 20~30개 사례와 대조
- **CI**: GitHub Actions에서 `ruff check` + `pytest`(몇 분)를 돌리면 push마다 회귀를 잡을 수 있습니다.

## 5. 성능

- 측정값은 위 표와 같고, 행렬 한 번 계산에 약 27 CPU분이 듭니다(4코어면 7분 안팎).
- **병목**
  - `damage()`가 한 쌍에 약 650번 불립니다.
  - `best_attack()`이 한 턴에 최대 4번 불립니다: 내 KO 판정, 상대 최선 추정, 최종 선택, 상대 `choose()` 안의 같은 계산.
  - 같은 상태에서 같은 피해를 반복 계산하므로, **턴 단위 피해표 캐시**(턴마다 무효화)로 2배 안팎 빨라질 것으로 봅니다.
- 핫 경로 안의 import(`plan_matrix`의 `import random`, `duel_stats`의 `from .game import solve`)는 비용은 작지만 순환 import의 증상입니다([1-5](#1-5)).
- 캐시 뒤에도 느리면, engine은 순수 파이썬이라 PyPy로 몇 배 가속될 여지가 있습니다. 다음 단계는 numba나 Cython입니다.

## 6. 저장소·배포 관리

- **줄바꿈 혼재**: data·engine·matrix·meta.py만 CRLF라서, 수정할 때마다 전체 파일이 바뀐 것처럼 보여 리뷰가 불가능합니다. `.gitattributes`에 `* text=auto eol=lf`를 넣고 한 번 정규화합니다.
- **의존성 고정 오류**
  - `requirements.txt`는 `numpy==2.5.3`에 "Python 3.14"라는 주석만 있습니다.
  - 이 환경(Python 3.11)의 패키지 목록에는 2.5.3이 없어서(최신 2.4.6) 설치가 실패합니다. 그런데 코드는 3.11 + numpy 2.4.6에서 selftest를 모두 통과합니다.
  - `numpy>=2.0,<3` 같은 범위로 바꾸고, `pyproject.toml`에 `requires-python`을 명시합니다.
- **생성물 커밋**
  - 처리 캐시 폴더 7개가 지문마다 쌓이고 있고, `out/`에 파일 72개가 있습니다. `index.html`은 `out/pick_board.html`의 사본입니다. 그래서 .git이 23 MB로 커지고 있습니다.
  - 캐시와 중간 산출물은 `.gitignore`에 넣고, 배포용 `index.html`만 커밋하거나 GitHub Actions로 만들어 배포합니다.
- **패키징**: `pyproject.toml`과 `[project.scripts] champions = "champions.__main__:main"`을 두면 저장소 루트가 아니어도 실행됩니다.
- **타입 힌트**: 없습니다. dict·tuple 구조가 많아 실수가 조용히 지나가므로, 공개 함수와 `Build`·`Side`부터 붙이고 mypy를 CI에 넣습니다.

## 7. 잘된 점

- `__slots__`, 결정적 시드, 코드 지문 캐시, 반대칭 테스트 등 성능과 검증을 의식한 설계입니다.
- 한국어 주석이 **왜 그렇게 했는지**(도메인 근거, 과거 버그 이력, 예시 매치업)를 설명합니다. 유지보수에 큰 자산입니다.
- 외부 의존성이 최소입니다(numpy만). LP를 직접 구현하고 테스트까지 갖췄습니다.
- 스크레이퍼에 타임아웃·요청 간격·예외 처리가 있습니다. 비싼 외부 호출(audit)은 결과를 캐시합니다.

## 8. 개선 계획

| 기간 | 할 일 |
|---|---|
| **단기**(하루 안) | 줄바꿈 정규화, requirements 범위 지정, `allow_pickle` 제거, JSON 삽입 이스케이프, 원자적 쓰기, 린트 결함 6건, docstring 정정, 파서 검증(SP 범위·합, 기술 습득, 성격 오타) |
| **중기**(1~2주) | 상태이상 면역·확률 누적 단일화, pytest + 고정 픽스처 + CI, `Config` 객체로 전역 제거·`--date`, CLI 로직을 서비스 모듈로, 턴 단위 피해 캐시 |
| **장기** | 특성·도구 훅 레지스트리로 `act`·`damage` 분해, `Side` 상태 분리, Enum·타입 힌트, 생성물 빌드·배포 파이프라인 |

## 부록: 측정 방법

```bash
ruff check champions --statistics
ruff check champions --select B,E722,PLW0603,PLW2901,RUF005,SIM,PERF,S --statistics
radon cc champions -s -n C
radon mi champions -s
coverage run --source=champions -m champions.selftest && coverage report
```

- **성능**: 조우 상위 12종 사이 60쌍의 호출당 평균 시간, 20쌍 `value_vs`의 cProfile(tottime 순)입니다.
- **미스트필드 불일치**: `Field.terrain = "misty"`에서 `_sec_status_ok(피카츄(정전기), 한카리아스, "par")`와 `_contact_reaction(한카리아스, 피카츄)`의 결과를 비교했습니다.
- **파서**: 위 표의 다섯 줄을 `textio.parse_party`에 넣었습니다.
- **의존성**: `pip index versions numpy`(이 환경, Python 3.11)입니다.
