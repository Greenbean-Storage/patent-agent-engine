# Claude Code 승인 모델 — 자동승인 vs 수동승인 (이 repo 기준)

> 출처: [Configure permissions — Claude Code Docs](https://code.claude.com/docs/en/permissions) + `.claude/settings.json` allow 목록.

## 1. 규칙 (공식 문서)

- 권한 규칙 3종: `allow`(프롬프트 없이 실행) · `ask`(매번 확인) · `deny`(차단). **평가 순서 deny → ask → allow**, 가장 **구체적인 규칙**이 먼저(배열 순서 아님).
- **매칭되는 규칙이 없으면 → 기본 동작 = `ask`(수동 승인 프롬프트)**.
- 권한 모드 5종: `default` · **`acceptEdits`** · `plan` · `dontAsk` · `bypassPermissions`.
  - **이 세션 = `acceptEdits` 모드** → `Edit`/`Write`/`NotebookEdit` 는 **항상 자동승인**. Bash 는 여전히 allow/ask/deny 규칙을 탄다.
- Bash 내장 read-only 명령은 **모든 모드에서 프롬프트 없이** 실행: `ls cat echo pwd head tail grep find wc which diff stat du cd` + read-only git.
- 와일드카드: `Bash(ls *)` 는 `ls -la` 매칭하나 `lsof` 는 아님 — `*` 앞 공백(단어 경계)이 핵심.

## 2. 이 세션 분류 (settings.json allow + acceptEdits + 내장 read-only)

### ✅ 자동승인 (프롬프트 안 뜸)
| 분류 | 항목 |
|---|---|
| 파일 편집 | **`Edit` · `Write` · `NotebookEdit`** (acceptEdits 모드) · `Read` |
| 검색/탐색 (내장 또는 allow) | `grep *` · `find *` · `cat *` · `head *` · `tail *` · `ls`/`ls *` · `wc *` · `which *` · `file *` · `diff *` · `stat *` · `du *` · `df *` · `ps *` · `env` · `sort *` · `cut *` · `tr *` · `jq *` · `awk *` · `sed *` · `python3 *` · `cd` |
| 빌드/검증 | **`make *`** · **`uv *`** · `uvx ruff *` · `pip install *` · `pip list *` · `npm *` · `pre-commit run *` · `python -m venezia_contracts.codegen` · `.venv/bin/python *` |
| git (쓰기 포함) | **`git add *`** · **`git commit *` / `git commit -m *`** · `git mv *` · **`git rm *`** · `git restore *` · `git checkout *` · `git reset *` · `git grep *` · read-only git(log/show/status/diff) |
| docker | `docker compose *` · `docker ps/images/logs/exec/run/pull/build/inspect/info/...` (+ `sudo -n docker *` 변형) |
| 기타 allow | `curl *` · `mkdir -p *` · `cd <repo> *` · `claude *` · `WebSearch` · `Skill(update-config*)` · 특정 `rm codegen.py` · 특정 `rm models/*.py` · `:` · 특정 `tee /tmp/*` · 특정 `cp prior_art_search/*` · 특정 `sed -i ...` · `tmux *` · 특정 `rg -n/-oN ...`(그 정확한 형태만) |

### ✋ 수동승인 (프롬프트 뜸 — allow 미매칭 → 기본 ask)
| 항목 | 이유 |
|---|---|
| **`rg ...` (일반 ripgrep)** | allow 엔 *특정* `rg -n/-oN ...` 만 등재. 일반 `rg` 패턴 없음 → ask. |
| **`rm <경로>` (일반 삭제)** | allow 엔 `rm codegen.py`·`rm models/*.py` 만. 그 외 `rm <path>` → ask. |
| `mv *` · `cp *` (일반) | allow 에 특정 cp 만 — 일반 mv/cp 없음 → ask |
| `python *` (python3 아님) | allow 는 `python3 *` 와 특정 `.venv/bin/python` 만 |
| `xargs *` (일반) | 특정 xargs 만 allow |
| `touch` · `chmod` · `chown` · `ln` | 미등재 → ask |
| `git push` · `git fetch` · `git pull` | 미등재 → ask |
| `WebFetch(다른 도메인)` | allow 는 wipo/kipro/data.go.kr/cpc 5개 도메인만 |
| allow 미매칭 그 외 모든 Bash | 기본 ask |

## 3. ⚠️ 가장 중요 — 복합 명령은 무조건 수동 승인
allow 는 **단일 명령 1개**를 매칭한다. 아래처럼 **묶으면** 각 조각이 allow 라도 **단일 패턴에 매칭 실패 → 수동 승인 프롬프트**:
- `cd X && grep ...` (체이닝) · `A; B` (세미콜론) · `VAR="..." grep ...` (변수할당 prefix) · `grep ... | grep -v ...` (파이프) · `grep ... || echo` (or)
- 여러 줄 heredoc/스크립트도 동일.

→ **단일·단순 명령 하나씩** 실행. 다중 패턴 탐색은 **Bash 가 아니라 `Grep`/`Glob`/`Read` 툴(자동)** 로.

## 4. 운영 규칙 (나의 행동)
- 탐색은 **`Grep`/`Glob` 툴**(Bash 아님, 자동) 우선. Bash 가 꼭 필요하면 `rg` 말고 단일 `grep`/`find`/`cat`.
- 파일 삭제는 **`rm <path>` 대신 `git rm <path>`** (`git rm *` allow).
- 검증/빌드/커밋은 단일 `make`·`git`·`uv` 명령으로 (체이닝 금지). 임시 `python` 은 `python3`.
