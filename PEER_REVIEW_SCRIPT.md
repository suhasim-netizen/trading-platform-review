# Peer review script (checklist)

Use this checklist during peer review. Sections **2**, **8.2**, and **15 / Step 13** below state the corrected expectations (credentials in source, OCO account, order-groups POST).

---

## 2. TS_CLIENT_ID check

**Check:** TS_CLIENT_ID and TS_CLIENT_SECRET values are never hardcoded — they are loaded from environment variables via Pydantic AliasChoices (acceptable — alias strings are not secret values).

**Rationale:** AliasChoices strings in `config.py` are not credentials — they are env var name mappings. The actual secret values come from `.env` only.

---

## 8.2 OCO account check

**Check:** Account: OCO uses AccountID from the fill event (env-driven, not hardcoded — correct practice).

**Rationale:** Hardcoding SIM3236523M in code is bad practice. The correct implementation reads AccountID from the fill, ensuring OCO always posts to the same account as the entry order.

---

## 15. Manual verification (excerpt)

### Step 13

**Check:** POST to ordergroups using AccountID from fill (not hardcoded — correct implementation).
