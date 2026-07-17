"""invoke track CLI — 스택 없는 로직 검증, 라인 99% suite pytest 호출 (각 컨테이너 venv 별).

각 suite 는 해당 컨테이너의 uv venv 에서 ephemeral `pytest` 로 path-scoped 호출:
  - shared  : `shared` venv → suites/shared/   (venezia_* 99)
  - cm      : `400.CM` venv → suites/cm/        (src 99)
  - dro     : `200.DRO` venv → suites/dro/      (src 99)
  - actor   : `300.Actor` venv → suites/actor/   (src 99)
  - account : `100.Nexus` venv → suites/account/ (src 99)

invoke 가 유일한 라인-커버리지 트랙 — CM 포함 5 패키지 전부. omit/exclude 설정은
제품 pyproject 가 아니라 `tests/invoke/coveragerc`(--cov-config) 에만 둔다(제품 검증 흔적 0).
probe 트랙은 실 CM 블랙박스(API 전수 + scaffolding) — 라인 커버리지 아님.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "@pipelines").is_dir():
            return parent
    raise FileNotFoundError("Cannot locate project root")


ROOT = _find_root()


# cov = pytest-cov source 목록 (--cov=X). fail_under = 게이트(미달 시 FAIL) — ratchet.
# 5 패키지(shared·cm·dro·actor·account) 전부 99. omit/exclude = tests/invoke/coveragerc (--cov-config).
SUITES: dict[str, dict] = {
    "shared": {
        "venv_dir": "shared",
        "test_file": "tests/invoke/invoke/suites/shared",
        "filter": None,
        "cov": [
            "venezia_pipeline_runtime",
            "venezia_memory",
            "venezia_topology",
            "venezia_contracts",
            "venezia_logging",
            "venezia_deployment",
            "venezia_cm_client",
            "venezia_media_config",
        ],
        "fail_under": 99,
    },
    "cm": {
        "venv_dir": "400.CM",
        "test_file": "tests/invoke/invoke/suites/cm",
        "filter": None,
        "cov": ["src"],
        "fail_under": 99,
    },
    "dro": {
        "venv_dir": "200.DRO",
        "test_file": "tests/invoke/invoke/suites/dro",
        "filter": None,
        "cov": ["src"],
        "fail_under": 99,
    },
    "actor": {
        "venv_dir": "300.Actor",
        "test_file": "tests/invoke/invoke/suites/actor",
        "filter": None,
        "cov": ["src"],
        "fail_under": 99,
        # engine.config SoT — 컨테이너에선 /app/engine.config.yaml (빌드 COPY),
        # 스택 없는 invoke 는 repo 의 committed 파일을 env 로 지정.
        "env": {"ENGINE_CONFIG_FILE": str(ROOT / "@deployment" / "engine.config.yaml")},
    },
    "account": {
        "venv_dir": "100.Nexus",
        "test_file": "tests/invoke/invoke/suites/account",
        "filter": None,
        "cov": ["src"],
        "fail_under": 99,
        # media.config SoT — 컨테이너에선 /etc/media.config.yaml (mount), 스택 없는 invoke 는
        # repo 의 committed 파일을 env 로 지정 (Nexus 미디어 라우트가 venezia_media_config read).
        "env": {"MEDIA_CONFIG_FILE": str(ROOT / "@deployment" / "media.config.yaml")},
    },
}


def _run_suite(name: str, conf: dict) -> int:
    bar = "━" * 40
    print(f"\n{bar} [invoke/{name}] venv={conf['venv_dir']} {bar}")
    cov_flags: list[str] = []
    for c in conf.get("cov", []):
        cov_flags += [f"--cov={c}"]
    if cov_flags:
        # omit/exclude 설정은 제품 pyproject 가 아니라 검증 트랙(tests/invoke/coveragerc)에만 둔다
        # (제품 코드에 검증/커버리지 흔적 0 원칙). 패키지별 omit 합집합 — 미매칭 패턴은 무시됨.
        cov_flags += [f"--cov-config={ROOT / 'tests' / 'invoke' / 'coveragerc'}"]
        cov_flags += ["--cov-report=term-missing"]
        fu = conf.get("fail_under")
        if fu is not None:
            cov_flags += [f"--cov-fail-under={fu}"]
    cmd = [
        "uv",
        "run",
        "--directory",
        str(ROOT / conf["venv_dir"]),
        "--with",
        "pytest",
        "--with",
        "pytest-asyncio",
        *(["--with", "pytest-cov"] if cov_flags else []),
        "python",
        "-m",
        "pytest",
        str(ROOT / conf["test_file"]),
        "-v",
        "--tb=short",
        *cov_flags,
    ]
    if conf.get("filter"):
        cmd += ["-k", conf["filter"]]
    env = {**os.environ, **conf.get("env", {})}
    rc = subprocess.call(cmd, cwd=ROOT, env=env)
    print(f"[invoke/{name}] → exit {rc}")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="invoke",
        description="검증 track 3 — 모듈 단위 + integration pytest (no docker stack)",
    )
    ap.add_argument(
        "--suite",
        choices=[*SUITES.keys(), "all"],
        default="all",
        help="특정 suite 만 실행 (default: all)",
    )
    args = ap.parse_args()

    plan = list(SUITES.keys()) if args.suite == "all" else [args.suite]

    results: dict[str, int] = {}
    for name in plan:
        results[name] = _run_suite(name, SUITES[name])

    bar = "━" * 78
    print(f"\n{bar}\n  invoke — aggregate\n{bar}")
    overall = 0
    for name, rc in results.items():
        mark = "✓" if rc == 0 else "✗"
        print(f"  {mark} {name:<12}: exit {rc}")
        overall = max(overall, rc)
    print(bar)
    if overall == 0:
        print("✅ invoke PASS — 모든 suite 통과")
        return 0
    print(f"❌ invoke FAIL — exit {overall}")
    return overall
