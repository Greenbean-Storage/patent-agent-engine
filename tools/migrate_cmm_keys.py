# /// script
# requires-python = ">=3.14"
# dependencies = ["boto3"]
# ///
"""A-2 CMM 지표 키 long→short 일회성 마이그레이션.

전 work 의 `sessions/{u}/{w}/models/concept-maturity-model.json` 5개 맵
(`scores`·`sub_scores`·`weights`·`sub_weights`·`rationales`)의 **지표 키**를
long→short rename 후 re-PUT:
  concept_clarity→clarity · description_completeness→completeness · patentability_potential→potential

indicator(지표) 레벨만 — leaf sub-key(purpose/components/...)·overall_score·last_updated 불변.
**idempotent** — 이미 짧은 키면 no-op(write 안 함). 부분 적용·중단 후 재실행 안전.

self-heal(다음 Director 사이클 full-PUT) 만으론 비활성 work 수렴 불보장이라 본 패스가 필수(A-2).
경로 suffix = scaffolding.yaml(models/concept-maturity-model.json) 고정값.

사용:
    S3_BUCKET=venezia-bucket AWS_REGION=ap-northeast-2 uv run tools/migrate_cmm_keys.py [--dry-run]
"""

from __future__ import annotations

import json
import os
import sys

import boto3

_RENAME = {
    "concept_clarity": "clarity",
    "description_completeness": "completeness",
    "patentability_potential": "potential",
}
_MAPS = ("scores", "sub_scores", "weights", "sub_weights", "rationales")
_PREFIX = "sessions/"
_SUFFIX = "/models/concept-maturity-model.json"


def _rename_indicator_keys(m: dict) -> tuple[dict, bool]:
    """지표 키만 long→short. 값(leaf 맵/숫자/문자)은 그대로."""
    out: dict = {}
    changed = False
    for k, v in m.items():
        nk = _RENAME.get(k, k)
        out[nk] = v
        changed = changed or nk != k
    return out, changed


def migrate_body(body: dict) -> bool:
    """body(CMM) 의 5 맵 지표 키 rename. 변경 있었으면 True."""
    changed = False
    for mp in _MAPS:
        if isinstance(body.get(mp), dict):
            body[mp], c = _rename_indicator_keys(body[mp])
            changed = changed or c
    return changed


def main() -> int:
    dry = "--dry-run" in sys.argv
    bucket = os.environ["S3_BUCKET"]
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))
    paginator = s3.get_paginator("list_objects_v2")
    seen = changed = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(_SUFFIX):
                continue
            seen += 1
            body = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
            if migrate_body(body):
                changed += 1
                if not dry:
                    s3.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=json.dumps(body, ensure_ascii=False).encode(),
                    )
                print(f"{'[dry] ' if dry else ''}migrated {key}")
    verb = "would change" if dry else "migrated"
    print(f"\nCMM files: {seen} seen, {changed} {verb}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
