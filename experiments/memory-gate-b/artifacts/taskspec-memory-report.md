# Gate B TaskSpec Memory Report

- Dataset: `project-factory-history-80dce6f86632`
- Source SHA: `80dce6f866329b79061bb1ed6b0594f9fdf2dd45`
- Gateway recalls: 2
- Actual provider tokens: `not_measured`
- Estimated memory delta: 942 characters / 236 tokens
- Logical digest: `3b86e98ba0769df51bff21cb4fb63a8b52982d2526f828a20d566f47647c6277`

## Cases

- baseline: status=disabled, claims=0, chars=707
- relevant: status=ok, claims=3, chars=1649
- irrelevant: status=ok, claims=0, chars=665
- no_question: status=not_requested, claims=0, chars=654

## Promotion Gates

- [x] relevant_single_recall
- [x] relevant_bounded_claims
- [x] relevant_gold_hit
- [x] relevant_grounded
- [x] irrelevant_single_recall
- [x] irrelevant_empty
- [x] no_question_no_recall
- [x] no_question_status
- [x] local_contract_preserved
- [x] context_budget
- [x] provider_tokens_not_measured
