# T10.3.5 historical Secret Scan review

The project requester approved the two dispositions on 2026-11-27 in the Codex conversation for [draft PR #31](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/pull/31), in reply to the proposal for the exact historical findings on head `92421a9`. The approval was recorded as “Ок”. This decision covers one `credential_url` match in each row below.

| Historical Git blob | Blob SHA-256 | Source commit | Fixture location |
| --- | --- | --- | --- |
| `30c1cddf74b553e5922797e025c64f36ad33f7a9` | `6efa73df2f906277291abe7ffb540f390d087281cdc65e74d7ffff80ddeb3a70` | `5e0e55ac398c6facecd8325e799b69762b516fc3` | `tests/test_grounded_ai.py:25` |
| `dc0cf3dce5e56776ed1ba7ee68a02540f60972cd` | `5b578fadf24767557cbfbfe06ea57301e12cdbd1ed8ff6ae7b70a738719a258e` | `7eeef220f2b49c21d36aace37260c8bf0215fc0f` | `tests/test_grounded_ai.py:26` |

Both matches contain byte-identical userinfo URLs for a reserved `.test` host. The original commit introduced the URL as a mock search result in `test_filter_invalid_evidence`. The second commit added pilot authentication to other tests in the file. The test exercises rejection of URL userinfo and asserts that the result is empty and adapter selection is never called. The test path performs no network authentication. Git history supports synthetic fixture intent and use within the repository. External reuse of the literal userinfo remains unverified. The [baseline supply-chain run](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/actions/runs/45937825201) reported zero tracked matches and two historical matches.

The CI scan still inspects every tracked file and reachable blob and prints redacted findings and raw counts. The gate credits one historical match per record only after verifying the blob digest, match count, line, source commit and historical paths. A tracked match, an additional finding, a missing or conflicting record, or an incomplete scan fails the gate. Running `python scripts/scan_secrets.py` separately preserves the strict exit status for all findings. CI invokes `python scripts/scan_secrets.py --apply-reviewed-history` for the approved gate decision.

The local and CI Python discovery comparison found the same 167 test IDs at `41c327b` and `92421a9`, with 95 passes and 72 DB-only skips on each revision. Production remains **NO-GO**. A01, A02, A05 and A12 remain open.
