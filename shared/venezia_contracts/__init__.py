"""
venezia_contracts — runtime contract loader.

@contracts/의 JSON Schema·data-model을 워커 런타임에서 로드·검증.
사용자 의도: contract 파일만 수정하면 워커 출력이 그대로 바뀌게 (manual dict 조립 제거).

기본 사용:

    from venezia_contracts import ContractLoader

    contracts = ContractLoader()  # @contracts 자동 탐지
    schema = contracts.load("integrated-patentability-analysis")
    contracts.validate("integrated-patentability-analysis", payload)
"""

from .loader import ContractError, ContractLoader, ValidationResult

__all__ = [
    "ContractLoader",
    "ContractError",
    "ValidationResult",
]
