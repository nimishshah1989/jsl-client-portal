# PR7 — Staging post-merge validation runbook

Prove the unified-login merge on a **faithful snapshot of prod**, with prod left
untouched, before it ever runs for real. This is the gated path from
`HANDOFF_MULTIPORTFOLIO.md §4` and the post-merge half of the BJ53 validation.

**Golden rule:** every command here targets the **staging** instance. The schema
migration and the merge are **never** run against `fie-db` (prod) in this runbook.

Prereqs: AWS CLI access (`rds:*` on the snapshot/restore, or do steps 1–2 in the
AWS console), the RDS master creds, and `ssh jprod`. Constants:
`RDS_HOST=fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com`, db `client_portal`,
region `ap-south-1`, app image/container `client-portal`.

---

## 1. Snapshot prod (safety baseline)
```bash
SNAP=fie-db-pre-merge-$(date +%Y%m%d-%H%M)
aws rds create-db-snapshot --region ap-south-1 \
  --db-instance-identifier fie-db --db-snapshot-identifier "$SNAP"
aws rds wait db-snapshot-available --region ap-south-1 --db-snapshot-identifier "$SNAP"
echo "snapshot: $SNAP"
```

## 2. Restore the snapshot to a NEW staging instance
```bash
aws rds restore-db-instance-from-db-snapshot --region ap-south-1 \
  --db-instance-identifier fie-db-staging \
  --db-snapshot-identifier "$SNAP" \
  --db-instance-class db.t3.medium --no-multi-az
aws rds wait db-instance-available --region ap-south-1 --db-instance-identifier fie-db-staging
STAGING_HOST=$(aws rds describe-db-instances --region ap-south-1 \
  --db-instance-identifier fie-db-staging \
  --query 'DBInstances[0].Endpoint.Address' --output text)
echo "staging endpoint: $STAGING_HOST"
```
A restored instance keeps the **same master username/password** as prod. Put the
staging creds in your shell (NOT in any file):
```bash
export RDS_MASTER_USER='<master user>'
export RDS_MASTER_PW='<master pw>'
export STG_SYNC="postgresql://$RDS_MASTER_USER:$RDS_MASTER_PW@$STAGING_HOST:5432/client_portal"
export STG_ASYNC="postgresql+asyncpg://$RDS_MASTER_USER:$RDS_MASTER_PW@$STAGING_HOST:5432/client_portal"
```
> If the sandbox/EC2 egress isn't on the staging instance's security group, add it
> (temporarily) the same way prod's SG admits the EC2 box.

## 3. On the box: get this branch's scripts
```bash
ssh jprod
cd ~/apps/client-portal && git fetch origin claude/pr7a-merge-migration \
  && git checkout claude/pr7a-merge-migration
```

## 4. Apply the additive schema migration — STAGING ONLY
```bash
docker run --rm -i --network host -v "$PWD/scripts:/scripts" postgres:15 \
  psql "$STG_SYNC" -f /scripts/migrate_add_merge_columns.sql
```
(Adds `cpp_clients.merged_into` + `cpp_merge_audit`. Idempotent.)

## 5. Dry-run the merge on staging (read-only report)
A throwaway container off the prod image (has the deps), pointed at **staging**,
with this branch's scripts mounted — the running prod container is not touched:
```bash
RUN="docker run --rm --network host --env-file $PWD/.env \
  -e DATABASE_URL=$STG_ASYNC -e DATABASE_URL_SYNC=$STG_SYNC \
  -v $PWD/scripts:/app/scripts client-portal"

$RUN python /app/scripts/merge_clients_by_name.py        # --dry-run is the default
```
Review the plan: ~36 multi-code groups, ~44 codes retired. **Eyeball the
name-collision section** — confirm no two *different* people share a name and
got grouped (e.g. the JHAVERI family are distinct full names, correctly NOT
merged; only same-exact-name codes fold).

## 6. Real merge on staging (transactional, reconcile-before-commit)
The `--expect-*` guards assert the restore is faithful AND the merge preserves
firm-wide totals (these are the prod baseline; a faithful restore matches them):
```bash
$RUN python /app/scripts/merge_clients_by_name.py --execute --yes \
  --expect-aum 905234707.58 --expect-invested 651769759.97 \
  --credential-csv /app/scripts/merge_credential_delta.csv
```
Expect: `COMMITTED. Credential delta (≈44 retired logins, 0 ever used)`. If
`verify_merge_invariants` fails it rolls back and commits nothing — investigate
before retrying.

## 7. Prove the unified views reconcile (the BJ53 post-merge check)
```bash
$RUN python /app/scripts/validate_client_views.py --code BJ53 --sample 20
```
Now BJ53 is **one** client owning 6 portfolios, so the `COMBINED` line is the
**real `combined_service` output** (not a preview). Pass criteria:
- `✓ invested == Σ live` and `✓ current == Σ live` for BJ53 (≈ ₹75.9L → ₹1.13Cr)
  and every other unified person.
- Each unified Combined view: `✓ nav_chart ✓ nifty_overlay ✓ risk_table
  ✓ performance_table ✓ underwater_chart ✓ allocation ✓ growth ✓ xirr`.
- Individual portfolio views still reachable per `?portfolio_id=` (ownership-checked).

## 8. Spot-check a retired-alias login → survivor
```bash
$RUN python -c "
import asyncio; from backend.database import AsyncSessionLocal
from sqlalchemy import select; from backend.models.client import Client
from backend.services.merge_service import resolve_login_target
async def go():
    async with AsyncSessionLocal() as db:
        r=(await db.execute(select(Client).where(Client.client_code=='BJ53PASS'))).scalar_one()
        s=await resolve_login_target(db, r)
        print('BJ53PASS alias ->', None if s is None else (s.client_code, len(s.portfolios)))
asyncio.run(go())"
```
Expect `BJ53PASS alias -> ('BJ53', 6)` — the retired code resolves to the survivor.

## 9. Tear down staging (avoid cost)
```bash
aws rds delete-db-instance --region ap-south-1 \
  --db-instance-identifier fie-db-staging --skip-final-snapshot
```

---

## Known caveats this run will (correctly) surface
- **JA59 / JAYASREE is NOT fixed by the merge.** Her live `JA59` is empty and her
  data is in the *closed* `JA59CLOSE`; merging unifies the two client rows but the
  Combined view (live-only) still reads **₹0**. Fix the underlying data
  (un-close `JA59CLOSE`, or fund/repoint `JA59`) — this is a prerequisite, not a
  merge step.
- **Empty Holdings tables on liquidated-to-cash / NAV-only accounts persist** —
  these are correct (no equity held); the cash-row display is separate polish.
- The credential-delta CSV should show ≈0 retired logins ever used → near-zero
  client disruption when this is later run on prod.

Only after staging is green here do you run §1–6 against **prod** (snapshot first),
then deploy the PR7a code (the schema migration must already be applied to prod),
then PR7b (ingestion group-by-name).
