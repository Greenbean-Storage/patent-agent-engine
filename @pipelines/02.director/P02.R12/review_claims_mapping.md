# P02.R12.DRAWING_ORCHESTRATION :: review_claims_mapping

> 청구항 초안의 부호 인용·element 일치성 검토.

## Instructions

**1. 부호 사용 검사**: context.steps.claims_call.out.claims 의 각 청구항 본문에서 context.steps.review_numerals_batch.all_numerals 의 부호가 자연스럽게 인용되는지. 형식: '~ NTC 서미스터(110)' / '~ MCU(120) 에 의해'. 부호가 빠지거나 잘못된 번호 인용이면 fail.

**2. 청구항 트리 정합성**: 각 청구항의 claim_number(독립항=1, 종속항=2,3,...) 와 parent_number 가 유효한지. 종속항의 parent_number 는 같은 트리 내의 더 작은 번호여야 함. 순환 종속(2가 3에 의존, 3이 2에 의존) 금지. independent_claims 와 dependent_claims 분리 정확.

**3. 핵심 발명 커버**: context.inputs.patent_model.specification 의 problem/solution 의 핵심 element 가 independent_claims 의 한정어로 표현되는지. element 빠뜨림 = 보호범위 축소 = 출원의 가치 손실. context.steps.review_numerals_batch.all_numerals 의 모든 핵심 ref 가 어떤 청구항이든 인용돼야 함.

**4. 한국 청구항 표준 어미 부합**: 표준 — '~인 것을 특징으로 하는 ~장치/방법' (독립항 종결) / '~를 더 포함하는' (종속항 추가 한정) / '~를 포함하는' (구성요소 나열). 명사형 종결만 사용 — '~한다', '~할 수 있다' 같은 종결형 금지. 영문 직역체('~을 가지는')는 권장 안함.

**5. checks 배열 산출**: 위 4개 항목을 {item, pass, comment} 4~6개. 1개라도 fail 이면 needs_revision=true.

**6. revision_comment 작성**: 청구항 단위로 구체적 지시. 예: '청구항 1 의 본문에 sigmoid 매핑 한정어 추가, 부호 (120) 인용. 청구항 3 의 parent_number 를 2 로 수정'. claims_with_numerals sub_pipeline 의 다음 라운드 입력으로 사용.

**7. existing_claims_for_revision 필드**: 재시도 시 Thinker 가 빈 상태에서 다시 만들지 않고 현재 claims 를 base 로 revision_comment 만 반영하도록, 현재 claims_call.out.claims 를 그대로 전달. 통과 시(needs_revision=false)에도 같은 값 — save_claims 가 이걸 IOM 에 patch.

**8. 보수적 검수 원칙**: 부호 인용 누락 / parent_number 오류 같은 형식 결함은 무조건 fail. 한국어 어미 불일치도 무조건 fail. 청구항은 출원 후 보정 한계가 큰 영역이므로 사전 엄격함이 의뢰인 보호.

## Output Contract

`review-claims-output`
