"""pip-audit dependency CVE runner.

각 target dir 의 uv.lock 을 `uv export` 로 hashed requirements 변환 후
pip-audit -r 로 audit. pip-audit 가 직접 `pip install` 해서 path-only
dep (`venezia-shared` 등) 에서 실패하지 않도록 우회.

IGNORE_VULNS 는 upstream-blocked CVE 의 의식적 무시 — 추가 시 사유 주석 필수.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

NAME = "pip-audit"

# {target_rel_path: [vuln_id, ...]} — upstream 미해결 / 우리 사용 패턴 무관 CVE
IGNORE_VULNS: dict[str, list[str]] = {
    # PYSEC-2026-161 (starlette Host header 기반 path injection):
    # google-adk 2.x 까지 starlette<1 으로 cap. fix 는 starlette 1.0.1.
    # 300.Actor 는 internal-only (docker network 내부 DRO↔Actor) — Host header
    # 기반 인증 path-check 미사용 → 이 CVE 영향 없음.
    "300.Actor": ["PYSEC-2026-161"],
}


def _export_requirements(target_dir: Path) -> Path | None:
    """`uv export` 로 hashed requirements 생성.

    path-based dep (`-e .`, `../shared`) 는 제외 — pip-audit 가 hash 없는
    local path requirement 를 거부함. 해당 dep 들은 우리 자기 코드이므로
    audit 대상 아님 (transitive 만 audit).
    """
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    try:
        proc = subprocess.run(
            [
                "uv",
                "export",
                "--no-dev",
                "--no-emit-project",
                "--format",
                "requirements-txt",
                "--directory",
                str(target_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(f"[{NAME}] uv export failed: {proc.stderr.strip()}")
            return None
        # path/editable 라인 (-e ..., ../foo, /abs/path) 제거
        kept: list[str] = []
        skip_continuation = False
        for raw in proc.stdout.splitlines():
            stripped = raw.strip()
            if skip_continuation:
                # 이전 라인이 path requirement 였다면 그에 딸린 indented 주석/옵션 라인 skip
                if raw.startswith((" ", "\t", "#")):
                    continue
                skip_continuation = False
            if stripped.startswith("-e ") or stripped.startswith(("../", "/")):
                skip_continuation = True
                continue
            kept.append(raw)
        tmp.write("\n".join(kept) + "\n")
        tmp.close()
        return Path(tmp.name)
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise


def run(root: Path, audit_targets: list[str]) -> int:
    """각 pyproject.toml 디렉토리에 대해 uv export → pip-audit -r 실행."""
    overall = 0
    for tgt in audit_targets:
        d = root / tgt
        if not (d / "pyproject.toml").exists():
            print(f"━━━ [{NAME}] {tgt} skip (no pyproject.toml) ━━━")
            continue
        print(f"\n━━━ [{NAME}] {tgt} ━━━")
        req_path = _export_requirements(d)
        if req_path is None:
            print(f"[{NAME}/{tgt}] → exit 2 (export failed)")
            overall = max(overall, 2)
            continue
        try:
            cmd = [NAME, "--strict", "--disable-pip", "-r", str(req_path)]
            for vuln in IGNORE_VULNS.get(tgt, ()):
                cmd.extend(["--ignore-vuln", vuln])
            rc = subprocess.call(cmd)
        finally:
            req_path.unlink(missing_ok=True)
        overall = max(overall, rc)
        print(f"[{NAME}/{tgt}] → exit {rc}")
    print(f"\n[{NAME}] aggregate → exit {overall}")
    return overall
