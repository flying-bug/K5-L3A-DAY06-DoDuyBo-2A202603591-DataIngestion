# Results: dev

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | page_hit@3 | containable | filter compliant | chunks | misses@3 |
|---|---|---|---|---|---|---|---|---|
| A | dev | 12/16 | 13/16 | 15/16 | 15/16 | 4/4 | 157 | q02, q10, q11 |
| B | dev | 13/16 | 15/16 | 16/16 | 16/16 | 4/4 | 186 | q11 |
| C | dev | 13/16 | 15/16 | 16/16 | 16/16 | 4/4 | 186 | q11 |

Selected on dev: **B / C** (rule: higher dev Evidence Hit@3 > higher dev Hit@1 > fewer chunks)
Note: B and C tie on every pre-registered criterion (they share the same index); the rule does not separate them, so all tied strategies are carried to test.
