# COLLOQUIAL-NORMALIZATION-001 — Engineering Review

## Outcome

The normalization layer now handles a narrow set of high-frequency chat forms without applying dangerous generic fuzzy matching. Together with the subsequent compositional slice, corrected behavior is locked by 24 regression cases while 35 independent cases remain blind.

## Design review

- Orthographic variants live in the resource catalog, not Python condition chains.
- Date suffix handling is implemented in both single-turn NLU and conversation-context extraction.
- Planner literal/filter logic still uses the original question; only catalog intelligence consumes the expanded semantic surface.
- Full-question aliases were avoided. Added vocabulary represents reusable concepts such as “doctor not entered” or “start after end”.

## Residual risks

1. Fresh data-quality paraphrases still degrade to generic count when they avoid known business nouns.
2. `check in`, `kuyrukta` and other operational colloquialisms need a deliberate terminology policy based on real users, not unlimited synonym growth.
3. Repeat-patient and compound period questions remain among the highest-value failures.
4. Live value grounding and real-result answer quality still require Monday's SQL Server profile.

## Follow-up delivered

`COMPOSITIONAL-METRIC-001` implemented column/concept + null/comparison/operator recognition. The fresh holdout now scores 23/35 and the catalog variation matrix remains 887/887.
