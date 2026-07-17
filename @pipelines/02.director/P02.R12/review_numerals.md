# P02.R12.DRAWING_ORCHESTRATION :: review_numerals

> 수집된 numerals 의 일관성·중복·신규 부호 부여 적정성 검토. 표준화.

## Instructions

**1. drawings ↔ numerals_results 매칭**: context.steps.generate_drawing_list.drawings 와 context.steps.extract_numerals_fanout.numerals_results 를 인덱스 순서 또는 drawing_id 로 매칭. fan_out 결과는 보통 인덱스 순서 보존되지만 drawing_id 일치 우선.

**2. 부호 번호 충돌 검사**: 모든 도면의 numerals 를 합쳐 ref(부호 번호) 가 서로 다른 부품(name 이 다름)에 동일하게 할당된 경우 fail. 예: fig1 의 100=NTC, fig2 의 100=MCU → 충돌. 같은 부품이면 같은 번호 사용은 정상(일관성).

**3. 부호 번호 패턴 일관성**: 한국 특허 표기 관습 — fig1 의 부호는 100/110/120... fig2 는 200/210/220... 단위. 패턴이 깨지면 fail. 단, 같은 부품을 여러 도면에서 참조할 때는 원래 번호 유지.

**4. key_elements 커버리지**: 각 drawing 의 key_elements 가 그 drawing 의 numerals 에 모두 매핑되는지. 누락된 element 있으면 fail.

**5. 한국어 라벨 부합**: numerals[*].name 이 한국어 명사구('NTC 서미스터', 'RGB 발광 다이오드')인지. 영문만 있거나 동사/형용사 라벨이면 fail. description 은 한국어 한 문장.

**6. 도면 간 일관성**: 같은 부품(NTC 서미스터)이 fig1 과 fig2 에 모두 등장하면 동일 ref 번호여야 함. 다른 번호면 fail.

**7. drawings_with_numerals 배열 생성**: 각 drawing object 에 다음 필드 추가 — numerals: list[{ref: int, name: string, description: string, drawing_role: string}] / numerals_payload: {drawing_id, numerals, extraction_notes} (save_drawing_artifacts sub_pipeline 이 받는 wrapper).

**8. all_numerals 산출**: 모든 도면의 부호를 합친 단일 list. 중복 부품(같은 ref+name)은 1회만. 청구항 작성 단계가 이 list 를 보고 청구항 본문에 부호를 인용. 형식: [{drawing_id, ref, name, description}].

**9. checks 배열 + needs_revision 결정**: 위 검사 결과를 {item, pass, comment} 형식으로 5~7개. 1개라도 fail 이면 needs_revision=true.

**10. revision_comment 작성**: 모든 도면에 공통으로 적용 가능한 한 단락 지시. 예: 'fig2 의 부호 200~270 패턴 유지하고 NTC 는 fig1 의 110 으로 통일. 한국어 라벨 사용'. 다음 extract_numerals_fanout 의 sub_pipeline 에 전달.

**11. 보수적 검수**: 부호 일관성은 출원 후 OA 에서 보정 가능하지만 사전에 잡으면 OA 부담 감소. 의심스러우면 fail.

## Output Contract

`review-numerals-batch-output`
