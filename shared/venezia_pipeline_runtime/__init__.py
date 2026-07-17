"""
venezia_pipeline_runtime — P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json 포맷 런타임 라이브러리.

단일 모듈:
- loader: P{NN}.R{NN} + persona.COMMON + GLOBAL 로드 후 4-layer cascading 합성.
  소비자 = 200.DRO(pipeline_walker) + tests/validate (stage 2 / cli).

구 composer / dispatch_resolver 는 제품 단독 소비자에게 흡수됨 (Actor 재설계 A5·C-3):
- composer → 300.Actor/src/composer.py
- dispatch_resolver → 200.DRO/src/dispatch_resolver.py
"""

from venezia_pipeline_runtime.loader import (
    LoaderError,
    load_pipeline_cascaded,
)

__all__ = [
    "load_pipeline_cascaded",
    "LoaderError",
]
