# Results: test

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | page_hit@3 | containable | filter compliant | chunks | misses@3 |
|---|---|---|---|---|---|---|---|---|
| A | test | 4/6 | 5/6 | 5/6 | 6/6 | 2/2 | 157 | q18 |
| B | test | 4/6 | 4/6 | 4/6 | 6/6 | 2/2 | 186 | q18, q22 |
| C | test | 4/6 | 4/6 | 4/6 | 6/6 | 2/2 | 186 | q18, q22 |

Selected on dev: **B / C** (rule: higher dev Evidence Hit@3 > higher dev Hit@1 > fewer chunks)
Note: B and C tie on every pre-registered criterion (they share the same index); the rule does not separate them, so all tied strategies are carried to test.
