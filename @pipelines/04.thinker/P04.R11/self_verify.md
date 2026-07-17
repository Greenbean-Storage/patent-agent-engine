# P04.R11.CLAIMS_WITH_NUMERALS :: self_verify

> draft 의 부호 인용 누락·중복·element 일치성·종속 관계 자체 검증 후 보정.

## Instructions

**1. 부호 일치 검증**: 각 청구항의 refs_used 의 모든 ref 가 context.inputs.all_numerals 에 존재하는지. (a) refs_used 의 부호가 all_numerals 에 없음 → issue (잘못된 부호). (b) all_numerals 의 핵심 부호(독립항 element 후보) 가 어느 청구항에도 인용 안 됨 → issue (커버리지 부족). (c) 청구항 본문 텍스트의 괄호 부호와 refs_used 가 일치하는지 — 텍스트에는 (140) 인데 refs_used 에 누락 → issue.

**2. 종속관계 트리 검증**: 각 type='종속' 청구항의 parent_number 가 (a) 유효한 청구항 번호(현재 list 에 존재), (b) 자기 자신 번호보다 작음(순환 종속 금지), (c) parent 가 type='독립' 또는 같은 트리의 다른 종속항. 위배 시 issue.

**3. 청구항 표현 명확성**: 각 청구항 본문에서 (a) 표준 어미 사용 여부('~인 것을 특징으로 하는', '제 N항에 있어서'), (b) 모호 표현 부재('약', '대략', '적절한', '신속한' 등), (c) 한 문장 단일 종결, (d) 한국어 명사형 종결. 위배 시 issue (severity='medium' 이상).

**4. 구체성·신규성 표현 점검**: 독립항이 prior_art 와 자명한 결합으로 보이지 않게 (a) 핵심 차별 한정어 포함, (b) 단순 부품 나열이 아닌 '~인 것을 특징으로 하는' 식 차별 표현. 추상적 또는 광범위 청구항은 issue (severity='high').

**5. issues 배열 작성**: 각 issue — (a) **claim_number**: 문제된 청구항 번호 (전체 영향이면 0). (b) **severity**: 'high'(검수 fail 직결) / 'medium'(보정 권고) / 'low'(스타일 권고). (c) **message**: 한 문장으로 무엇이 문제인지. (d) **suggestion**: 구체적 수정 방향 한 줄.

**6. corrected_claims 재출력**: 위 issues 중 직접 수정 가능한 것(부호 인용 오류·parent_number 오류·표준 어미 누락) 은 corrected_claims 에 반영. 발명 본질을 바꾸는 수정(범위 broad/narrow) 은 issue 만 표시하고 본문 유지. 수정 없으면 입력 claims 그대로 corrected_claims 에 복사 — 항상 반환되어야 함.

**7. self_check_notes 작성 (한 단락)**: 검수 결과 요약 — '청구항 12개 중 부호 인용 누락 2건, 종속관계 1건 수정. 독립항 1의 한정어 부족 issue 표시(severity=high, Director 검수 필요).' 다음 review_claims 의 단서.

**8. 보수적 검수**: 의심스러우면 issue 추가 + severity 한 단계 높게. 부호 인용 누락 / parent_number 오류 같은 형식 결함은 무조건 high. 청구항은 출원 후 보정 한계 크므로 사전 엄격함이 의뢰인 보호.

## Output Contract

`self-check-output`
