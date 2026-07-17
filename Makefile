.PHONY: help up down logs ps mode topology \
        validate lint invoke probe enact play endpoint deploy export-openapi \
        _full_reset _deploy_env _check_aws_creds _wait_healthy \
        cli-install build-classification build-classification-dry verify-classification \
        manual-install build-drafting build-drafting-raw build-drafting-summary verify-drafting \
        rejections-install build-rejections build-rejections-summary build-rejections-by-section build-rejections-cases verify-rejections \
        .uv

.DEFAULT_GOAL := help

# --env-file 은 compose.yaml 의 ${VAR} interpolation 용. .env.topology=포트(topology.yaml SoT),
# .env.deploy=<UNIT>_TARGET(profile.stack.yaml SoT, build.target 보간). 둘 다 make up(_full_reset) 이 생성.
# service-level env_file: 과 다른 layer — compose 의 ports / environment / build.target 영역에 적용.
DOCKER := docker compose --env-file @deployment/.env.topology --env-file @deployment/.env.deploy

# 쉘에 stray VIRTUAL_ENV(예: 과거 `source 400.CM/.venv/bin/activate` 잔재)가 export 돼 있으면
# uv 가 "does not match project environment" 경고를 낸다. recipe 로 전파하지 않게 차단 — uv 가
# 각 프로젝트의 올바른 env 를 쓰게 한다 (값 변경 아님, make 가 자식 쉘로 안 넘김).
unexport VIRTUAL_ENV

# ambient ACTOR_TARGET/DRO_TARGET/CM_TARGET/NEXUS_TARGET 가 --env-file @deployment/.env.deploy 를
# 덮어쓰지 못하게 차단 (compose 보간 우선순위: shell env > --env-file). .env.deploy(make up/deploy 생성)가
# build.target 의 단일 권위 — ambient/stale 값으로 mock|production 잘못 launch 방지.
unexport ACTOR_TARGET DRO_TARGET CM_TARGET NEXUS_TARGET

# =============================================================================
# ANSI 색상 (help 출력용) — shell-evaluated escape (printf '\033')
# =============================================================================
ESC     := $(shell printf '\033')
RESET   := $(ESC)[0m
BOLD    := $(ESC)[1m
DIM     := $(ESC)[2m
RED     := $(ESC)[31m
GREEN   := $(ESC)[32m
YELLOW  := $(ESC)[33m
BLUE    := $(ESC)[34m
MAGENTA := $(ESC)[35m
CYAN    := $(ESC)[36m

# =============================================================================
# Help — welcome banner + 색상 + 섹션 분리
# =============================================================================
help:                         ## 명령어 도움말 (this screen)
	@printf "\n$(BOLD)$(MAGENTA)╔══════════════════════════════════════════════════════════════════╗$(RESET)\n"
	@printf "$(BOLD)$(MAGENTA)║   Patent AI Agent Engine  —  DRC Make 인터페이스                  ║$(RESET)\n"
	@printf "$(BOLD)$(MAGENTA)╚══════════════════════════════════════════════════════════════════╝$(RESET)\n\n"
	@printf "$(BOLD)$(CYAN)▶ 검증 7 track$(RESET) $(DIM)(역할별 동등, no-stack 3 + stack 4)$(RESET)\n"
	@printf "  $(GREEN)make validate$(RESET)              JSON 산출물 schema/cross-ref/registry 정적 (15 stage)\n"
	@printf "  $(GREEN)make lint$(RESET)                  코드 자동수정+검사 (ruff --fix+format · mypy · bandit · pip-audit)\n"
	@printf "  $(GREEN)make invoke$(RESET)                스택 없는 로직 라인 99%% (5 suite)\n"
	@printf "  $(GREEN)make probe$(RESET) <sub-cmd>       실 CM 블랙박스 — 관찰/구성/제어 + verify 검증\n"
	@printf "  $(GREEN)make enact$(RESET) [<대상>]        Actor 단일 RT 수행 — 시나리오 5/5 게이트·단건(P{NN}.R{NN} <step> | spec | PERSONA= PROMPT=)\n"
	@printf "  $(GREEN)make play$(RESET) [P{NN}.R{NN}]    pipeline 실행 — 無인자 = root 전수 (auto-seed + invariants)\n"
	@printf "  $(GREEN)make endpoint$(RESET) [<phase>]    외부 API REST + WS contract e2e\n\n"
	@printf "$(BOLD)$(YELLOW)▶ Stack utility$(RESET) $(DIM)(검증 verb 아님 — docker compose 작업. 모드는 deploy profile)$(RESET)\n"
	@printf "  $(YELLOW)make up$(RESET)                   풀 reset. 모드 = @deployment/profile.stack.yaml (positional 폐기)\n"
	@printf "      $(DIM)로컬/검증:$(RESET) $(YELLOW)make deploy init llm fake auth open$(RESET) 후 $(YELLOW)make up$(RESET)   $(DIM)# FIXTURE + OPEN$(RESET)\n"
	@printf "      $(DIM)실 운영:$(RESET)   $(YELLOW)make deploy init$(RESET) 후 $(YELLOW)make up$(RESET)                    $(DIM)# 전 knob default = PRODUCTION + SECURE (EC2 IAM)$(RESET)\n"
	@printf "  $(YELLOW)make mode$(RESET)                  현 모드 (profile.stack.yaml 의 auth/engine/llm/kipris)\n"
	@printf "  $(YELLOW)make topology$(RESET)              @deployment/topology.yaml → @deployment/.env.topology 재생성 (SoT 변경 시)\n"
	@printf "  $(YELLOW)make down$(RESET)                  stack 종료 + image/volume 제거\n"
	@printf "  $(YELLOW)make logs$(RESET) / $(YELLOW)ps$(RESET)             컨테이너 로그 / 상태\n\n"
	@printf "$(BOLD)$(YELLOW)▶ Deployment 구성$(RESET) $(DIM)(knob profile — deploy=구성, up=기동)$(RESET)\n"
	@printf "  $(YELLOW)make deploy init$(RESET) [<knob> <val>...]  profile 생성 (default + override. 예: $(YELLOW)init llm fake auth open$(RESET))\n"
	@printf "  $(YELLOW)make deploy set$(RESET) <knob> <val>  knob 값 변경 (예: $(YELLOW)make deploy set actor fake$(RESET))\n"
	@printf "      $(DIM)knob: actor/dro/cm/nexus/llm/kipris=real|fake · auth=open|secure · engine=full|smalltalk$(RESET)\n"
	@printf "  $(YELLOW)make deploy show$(RESET) / $(YELLOW)vet$(RESET) / $(YELLOW)reset$(RESET)        현 profile 출력 / 검증 / default 초기화\n\n"
	@printf "$(BOLD)$(CYAN)▶ probe sub-command$(RESET) $(DIM)(make probe <sub> + 필요 시 IOM= USER_ID= INVENTION_ID= 등)$(RESET)\n"
	@printf "  $(CYAN)view$(RESET) / $(CYAN)trail$(RESET) / $(CYAN)check$(RESET) <chain_id>         chain 전체 / trail / 9 invariants\n"
	@printf "  $(CYAN)seed$(RESET) $(DIM)IOM=<path>$(RESET)                       IOM JSON CM 적재\n"
	@printf "  $(CYAN)list$(RESET) $(DIM)[USER_ID=<u>]$(RESET)                    사용자의 invention 목록\n"
	@printf "  $(CYAN)list-chains$(RESET) <work_id>             invention 의 chain 인벤토리\n"
	@printf "  $(CYAN)dump-rt$(RESET) <chain_id> <rt_id>             RT JSON export\n"
	@printf "  $(CYAN)models$(RESET) <work_id>                  models/ (IOM / CMM / CDS / UR) dump\n"
	@printf "  $(CYAN)dialogs$(RESET) <work_id>                 runtime/{persona}/*.json dialogs dump\n"
	@printf "  $(RED)clean$(RESET) <work_id> $(DIM)[--yes]$(RESET)          invention 삭제 (DELETE, 되돌릴 수 없음)\n"
	@printf "  $(GREEN)verify$(RESET)                                 게이트: CM API 전수 + scaffolding 구조검증 (임시 세션)\n"
	@printf "  $(CYAN)exercise$(RESET) / $(CYAN)structure$(RESET) <work_id>      CM API 전수 / 세션 S3 구조 ↔ scaffolding·manifest\n\n"
	@printf "$(BOLD)$(BLUE)▶ Knowledge base$(RESET) $(DIM)(별개 도메인)$(RESET)\n"
	@printf "  $(BLUE)make build-classification$(RESET) / $(BLUE)build-drafting$(RESET) / $(BLUE)build-rejections$(RESET)\n"
	@printf "  $(BLUE)make verify-classification$(RESET) / $(BLUE)verify-drafting$(RESET) / $(BLUE)verify-rejections$(RESET)\n\n"
	@printf "$(DIM)📖 문서: .docs/Verification/verification.md$(RESET)\n\n"

.uv:
	@uv --version > /dev/null 2>&1 || (echo "uv not installed: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1)

# =============================================================================
# 검증 7 track
# =============================================================================

# --- Static (no docker stack) ---
validate: .uv                 ## JSON 산출물 schema · cross-ref · tool registry 정적 (15 stage)
	@cd tests/validate && uv run python -m validate

lint: .uv                     ## 코드 자동수정+검사 일괄 (ruff --fix+format write · mypy · bandit · pip-audit, 4개 다 게이트)
	@cd tests/lint && uv run python -m lint

invoke: .uv                   ## 모듈 단위 + integration pytest (각 컨테이너 venv 별)
	@cd tests/invoke && uv run python -m invoke

# --- Stack 필요 ---
probe: .uv                    ## 실 CM 블랙박스 sub-command tree (+ verify/structure 검증)
	@cd tests/probe && \
	 TOPOLOGY_NETWORK=external TOPOLOGY_FILE=$(abspath @deployment/topology.yaml) \
	 uv run python -m probe \
	  $(filter-out probe,$(MAKECMDGOALS)) \
	  $(if $(IOM),--iom $(abspath $(IOM))) \
	  $(if $(USER_ID),--user-id $(USER_ID)) \
	  $(if $(INVENTION_ID),--invention-id $(INVENTION_ID)) \
	  $(if $(POINTER),--pointer $(POINTER)) \
	  $(if $(ONLY),--only $(ONLY)) \
	  $(if $(YES),--yes)

enact: .uv                    ## Actor 단일 RT 수행 — 無인자=시나리오 전수 | <scenario> | P{NN}.R{NN} <step> | <spec> | PERSONA= PROMPT=
	@cd tests/enact && \
	 TOPOLOGY_NETWORK=external TOPOLOGY_FILE=$(abspath @deployment/topology.yaml) \
	 DEPLOYMENT_FILE=$(abspath @deployment/profile.stack.yaml) \
	 uv run python -m enact $(filter-out enact,$(MAKECMDGOALS))

play: .uv                     ## pipeline 실행 — 無인자 = root 전수, P{NN}.R{NN} = 단일
	@case "$(PLAY_VERB)" in \
	  P*|"") cd tests/play && \
	      TOPOLOGY_NETWORK=external TOPOLOGY_FILE=$(abspath @deployment/topology.yaml) \
	      DEPLOYMENT_FILE=$(abspath @deployment/profile.stack.yaml) \
	      uv run python -m play $(PLAY_VERB) \
	       $(if $(SEED),--seed-iom-from $(abspath $(SEED))) \
	       --ws-timeout $(or $(WS_TIMEOUT),1800) ;; \
	  *) printf "$(RED)사용법:$(RESET) make play [P{NN}.R{NN}] [SEED=path.json] [WS_TIMEOUT=N] (無인자 = root 전수)\n" && exit 2 ;; \
	esac

endpoint: .uv                 ## 외부 API REST + WS contract e2e (positional = phase | call)
	@cd tests/endpoint && \
	 TOPOLOGY_NETWORK=external TOPOLOGY_FILE=$(abspath @deployment/topology.yaml) \
	 DEPLOYMENT_FILE=$(abspath @deployment/profile.stack.yaml) \
	 uv run python -m endpoint \
	  $(filter-out endpoint,$(MAKECMDGOALS)) \
	  $(if $(TAPE),--tape "$(TAPE)") \
	  $(if $(REST),--rest "$(REST)") \
	  $(if $(WS),--ws '$(WS)') \
	  $(if $(BODY),--body '$(BODY)')

# --- 배포 profile 제어 (knob 시스템, stack 미중지) ---
deploy: .uv                   ## 배포 profile 제어 — init|show|reset|vet|set <knob> <value>...
	@cd shared && uv run python -m venezia_deployment \
	  --knobs $(abspath @deployment/knobs.yaml) \
	  --profile $(abspath @deployment/profile.stack.yaml) \
	  $(filter-out deploy,$(MAKECMDGOALS))
	@if test -f @deployment/profile.stack.yaml; then $(MAKE) -s _deploy_env; fi   # profile 변경 → .env.deploy 즉시 동기화 (stale launch 방지)

# === positional dispatcher (play / probe / up / deploy) =========================
ifeq (play,$(firstword $(MAKECMDGOALS)))
  PLAY_VERB := $(wordlist 2,2,$(MAKECMDGOALS))
  ifneq (,$(PLAY_VERB))
    $(eval $(PLAY_VERB):;@:)
    .PHONY: $(PLAY_VERB)
  endif
endif

# probe <sub> <positional...> — sub(2번째)는 정적 가짜-target 목록에 있음.
# chain_id/work_id/rt_id(3·4번째)는 UUID 라 동적 no-op target 등록(make 가 빌드 goal 로 오해 방지).
ifeq (probe,$(firstword $(MAKECMDGOALS)))
  PROBE_3 := $(wordlist 3,3,$(MAKECMDGOALS))
  PROBE_4 := $(wordlist 4,4,$(MAKECMDGOALS))
  ifneq (,$(PROBE_3))
    $(eval $(PROBE_3):;@:)
    .PHONY: $(PROBE_3)
  endif
  ifneq (,$(PROBE_4))
    $(eval $(PROBE_4):;@:)
    .PHONY: $(PROBE_4)
  endif
endif

# deploy <action> [<knob> <value>...] — passthrough 단어 전부 no-op phony 등록
# (make 가 init/set/actor/fake 등을 build goal 로 오해해 에러나는 것 방지). knob 무관 generic.
ifeq (deploy,$(firstword $(MAKECMDGOALS)))
  DEPLOY_ARGS := $(wordlist 2,99,$(MAKECMDGOALS))
  $(foreach w,$(DEPLOY_ARGS),$(eval $(w):;@:))
  .PHONY: $(DEPLOY_ARGS)
endif

# endpoint <phase...|call> — passthrough 단어 동적 no-op 등록 (deploy 동형 — 정적 목록의
# 누락(auth/secure)·신규 phase(ws_tape/call) 추가 시 유지보수 0).
ifeq (endpoint,$(firstword $(MAKECMDGOALS)))
  ENDPOINT_ARGS := $(wordlist 2,99,$(MAKECMDGOALS))
  $(foreach w,$(ENDPOINT_ARGS),$(eval $(w):;@:))
  .PHONY: $(ENDPOINT_ARGS)
endif

# enact VAR(PROMPT 등 자유 텍스트) 전달 = 2중 차단 (셸 인젝션 + make code execution):
#   1) unexport VAR — command-line 변수는 자동으로 자식 recipe env 에 export 되는데 그 시점에
#      recursive 확장이 일어나 값 안의 $(shell …) 가 실행됨. **전역**(ifeq 밖) unexport 로 끊음
#      — firstword≠enact 인 multi-goal(`make foo enact PROMPT=…`)도 우회 못 하게. ENACT_*
#      (simply-expanded raw) 만 명시 전달, cli 가 평문 문자열로 read (make·셸 재파싱 0).
#   2) $(value VAR) — ENACT_* 정의 시 값을 확장 없이 raw 로. `$(PROMPT)` 직접 참조는 값 안의
#      $(shell …) 를 정의 시점에 make 함수로 실행하므로 value 로 차단.
unexport PROMPT PERSONA TIMEOUT SPEC

# enact <scenario|P{NN}.R{NN} step|spec경로> — endpoint 동형 동적 no-op 등록
# (spec 경로는 실재 파일이라 .PHONY 필수 — "is up to date" 로 recipe 미실행 방지).
ifeq (enact,$(firstword $(MAKECMDGOALS)))
  ENACT_ARGS := $(wordlist 2,99,$(MAKECMDGOALS))
  $(foreach w,$(ENACT_ARGS),$(eval $(w):;@:))
  .PHONY: $(ENACT_ARGS)
  export ENACT_PROMPT := $(value PROMPT)
  export ENACT_PERSONA := $(value PERSONA)
  export ENACT_TIMEOUT := $(value TIMEOUT)
  export ENACT_SPEC := $(if $(value SPEC),$(abspath $(value SPEC)))
endif

# comma 변수 (findstring 안 escape 용; ifeq 블록 안에서 참조)
comma := ,

# make up positional(full/fixture/open) 폐기 (1b) — 모드는 @deployment/profile.stack.yaml (make deploy).
# `make up <인자>` 는 parse-time fail-loud (아래) — 옛 positional no-op 단어(smalltalk/full/fixture/
# production/open/secure)도 제거해 silent 무시 방지. (rebuild 낭비 없이 즉시 에러.)
ifeq (up,$(firstword $(MAKECMDGOALS)))
  ifneq (,$(wordlist 2,99,$(MAKECMDGOALS)))
    $(error 'make up' 은 인자를 받지 않습니다 — 모드는 @deployment/profile.stack.yaml (make deploy))
  endif
endif

# 가짜 target (probe 의 positional arg — endpoint 는 위 동적 dispatcher 가 처리)
view trail check seed list list-chains dump-rt models dialogs clean structure exercise verify:
	@:

# play P{NN}.R{NN} 패턴 가짜 target
P%:
	@:

# =============================================================================
# Stack utility (검증 verb 아님)
# make up = docker compose down/build/up (모드 = profile.stack.yaml, build.target = .env.deploy).
# 빌드 자체는 일반 docker compose 빌드 — play(검증) 와 본질 무관.
# =============================================================================

up:                           ## docker compose 풀 reset (모드 = @deployment/profile.stack.yaml — make deploy)
	@test -f @deployment/profile.stack.yaml || { \
	  printf "$(RED)profile 없음:$(RESET) @deployment/profile.stack.yaml — 먼저 $(YELLOW)make deploy init$(RESET) 실행\n" && exit 2; }
	@if grep -qE '^llm:[[:space:]]*real' @deployment/profile.stack.yaml; then \
	   $(MAKE) -s _check_aws_creds; fi   # llm:real(=PRODUCTION) → EC2 IAM 확인
	@$(MAKE) -s _full_reset

topology: .uv                 ## @deployment/topology.yaml → @deployment/.env.topology 생성 (compose interpolation 용)
	@cd shared && TOPOLOGY_FILE=$(abspath @deployment/topology.yaml) \
	 uv run python -m venezia_topology.export_env > ../@deployment/.env.topology
	@printf "$(GREEN)✓ @deployment/.env.topology generated$(RESET) (SoT: @deployment/topology.yaml)\n"

_deploy_env: .uv              # profile.stack.yaml → @deployment/.env.deploy (<UNIT>_TARGET, build.target 보간용)
	@cd shared && DEPLOYMENT_FILE=$(abspath @deployment/profile.stack.yaml) \
	 DEPLOYMENT_KNOBS=$(abspath @deployment/knobs.yaml) \
	 uv run python -m venezia_deployment.export > ../@deployment/.env.deploy
	@printf "$(GREEN)✓ @deployment/.env.deploy generated$(RESET) (SoT: @deployment/profile.stack.yaml)\n"

mode:                         ## 현 모드 (auth/engine/llm) — @deployment/profile.stack.yaml (SoT)
	@if [ -f @deployment/profile.stack.yaml ]; then \
	   printf "$(BOLD)모드$(RESET) (profile.stack.yaml — make up 시 컨테이너가 read):\n"; \
	   grep -E '^(auth|engine|llm|kipris):' @deployment/profile.stack.yaml | sed 's/^/  /'; \
	 else printf "$(RED)profile 없음$(RESET) — $(YELLOW)make deploy init$(RESET)\n"; fi

down:                         ## stack 종료 + image/volume 완전 제거
	@$(DOCKER) down --rmi all -v --remove-orphans 2>/dev/null || true
	@printf "$(GREEN)✓ all containers, images, volumes removed$(RESET)\n"

logs:                         ## 전체 로그 (-f)
	@$(DOCKER) logs -f

ps:                           ## 컨테이너 상태
	@$(DOCKER) ps

# =============================================================================
# 내부 헬퍼 (직접 호출 X)
# =============================================================================

_full_reset:
	@printf "\n$(BOLD)$(CYAN)▶ stack 풀 reset$(RESET)  (모드 = @deployment/profile.stack.yaml)\n"
	@test -f @deployment/profile.stack.yaml || { \
	  printf "$(RED)profile 없음:$(RESET) @deployment/profile.stack.yaml — 먼저 $(YELLOW)make deploy init$(RESET) 실행\n" && exit 2; }
	@grep -E '^(auth|engine|llm):' @deployment/profile.stack.yaml | sed 's/^/  /'
	@printf "  $(DIM)1/5$(RESET) config env 생성 (.env.topology + .env.deploy)\n"
	@$(MAKE) -s topology
	@$(MAKE) -s _deploy_env
	@printf "  $(DIM)2/5$(RESET) stack down + image/volume 제거\n"
	@$(DOCKER) down --rmi all -v --remove-orphans 2>/dev/null || true
	@printf "  $(DIM)3/5$(RESET) image rebuild (--no-cache --pull)\n"
	@$(DOCKER) build --no-cache --pull
	@printf "  $(DIM)4/5$(RESET) stack 시작 (--force-recreate)\n"
	@$(DOCKER) up -d --force-recreate
	@printf "  $(DIM)5/5$(RESET) healthcheck 대기\n"
	@$(MAKE) -s _wait_healthy
	@printf "\n$(GREEN)✓ stack ready$(RESET)  (모드 = profile.stack.yaml)\n"

# container_name 이 literal(예: 300.Actor / 400.CM)이라 기본 `<project>-<svc>-1` 패턴이
# 사라짐 → 컨테이너 ID 순회 방식(이름-무관)으로 health 대기. 모든 서비스가 healthcheck 보유.
_wait_healthy:
	@for cid in $$($(DOCKER) ps -aq); do \
	  name=$$(docker inspect --format='{{.Name}}' $$cid 2>/dev/null | sed 's#^/##'); \
	  printf "      waiting %-14s " "$$name"; \
	  for i in $$(seq 1 60); do \
	    status=$$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $$cid 2>/dev/null || echo missing); \
	    if [ "$$status" = "healthy" ]; then printf "$(GREEN)OK$(RESET)\n"; break; fi; \
	    if [ $$i = 60 ]; then printf "$(RED)TIMEOUT (status=$$status)$(RESET)\n"; exit 1; fi; \
	    sleep 2; \
	  done; \
	done

_check_aws_creds:
	@curl -s --max-time 1 -o /dev/null \
	  http://169.254.169.254/latest/meta-data/iam/security-credentials/ \
	  || (printf "$(RED)ERROR: PRODUCTION 모드는 EC2 IAM role 환경에서만 동작.$(RESET)\n" && \
	      printf "  로컬 dev 는 'make deploy init llm fake auth open && make up' 사용.\n" && \
	      printf "  PRODUCTION 운영은 EC2 인스턴스에서.\n" && \
	      exit 2)

export-openapi: .uv           ## Nexus /openapi.json → .docs/Architectures/external_api/openapi.nexus.json (stack 가동 가정)
	cd tools/openapi-export && uv sync --no-dev --quiet
	TOPOLOGY_FILE="$(PWD)/@deployment/topology.yaml" TOPOLOGY_NETWORK=external \
	  uv run --project tools/openapi-export export-openapi

# =============================================================================
# Knowledge Base 빌드 (별개 도메인)
# =============================================================================
CLI_DIR    := tools/classification-indexer
CLI_UV_RUN := cd $(CLI_DIR) && uv run

cli-install: .uv              ## classification-indexer deps
	cd $(CLI_DIR) && uv sync --no-dev

build-classification: .uv     ## @knowledge/classification/ 빌드 (WIPO + KIPI + KIPRIS + data.go.kr)
	$(CLI_UV_RUN) python -m classification_indexer build

build-classification-dry: .uv ## build 시뮬레이션 (write X)
	$(CLI_UV_RUN) python -m classification_indexer build --dry-run

verify-classification: .uv    ## @knowledge/classification/ 검증
	$(CLI_UV_RUN) python -m classification_indexer verify

MANUAL_DIR    := tools/manual-indexer
MANUAL_UV_RUN := cd $(MANUAL_DIR) && uv run

manual-install: .uv           ## manual-indexer deps
	cd $(MANUAL_DIR) && uv sync --no-dev

build-drafting-raw: .uv       ## KIPO 심사기준 7 PDF → @knowledge/drafting/raw/
	$(MANUAL_UV_RUN) python -m manual_indexer extract

build-drafting-summary: .uv   ## raw/* → summary.md (Claude 1회성)
	$(MANUAL_UV_RUN) python -m manual_indexer summarize

build-drafting: .uv           ## @knowledge/drafting/ end-to-end
	$(MANUAL_UV_RUN) python -m manual_indexer build

verify-drafting: .uv          ## @knowledge/drafting/summary.md 검증
	$(MANUAL_UV_RUN) python -m manual_indexer verify

REJECTIONS_DIR    := tools/rejections-indexer
REJECTIONS_UV_RUN := cd $(REJECTIONS_DIR) && uv run

rejections-install: .uv       ## rejections-indexer deps
	cd $(REJECTIONS_DIR) && uv sync --no-dev

build-rejections-summary: .uv ## drafting/raw → @knowledge/rejections/summary.md
	$(REJECTIONS_UV_RUN) python -m rejections_indexer summarize

build-rejections-by-section: .uv ## IPC Section 별 거절사유 가이드 → @knowledge/rejections/by-section/{A..H}.md
	$(REJECTIONS_UV_RUN) python -m rejections_indexer by-section

build-rejections-cases: .uv   ## KIPRIS 거절결정문 다운샘플링 + 임베딩 + Chroma sqlite
	$(REJECTIONS_UV_RUN) python -m rejections_indexer cases

build-rejections: .uv         ## @knowledge/rejections/ end-to-end
	$(REJECTIONS_UV_RUN) python -m rejections_indexer build

verify-rejections: .uv        ## @knowledge/rejections/ 검증
	$(REJECTIONS_UV_RUN) python -m rejections_indexer verify
