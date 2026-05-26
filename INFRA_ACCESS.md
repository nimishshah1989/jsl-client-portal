# Infrastructure Access — JSL Client Portfolio Portal

**Purpose:** lets Claude operate the production stack (EC2 + RDS + AWS) end-to-end without the operator having to paste credentials every session. Once the env vars described below are configured **once** in the Claude Code project settings, every future session boots ready.

**Hard rule:** this file documents *what* values are needed and *where to find them*. It does NOT contain any secret value. Secrets live in Claude Code project environment variables (which are encrypted, never committed to git, never visible to the LLM training pipeline). If a value looks sensitive and someone is tempted to paste it directly into this file, the answer is **no** — add it to the env vars instead. C1 (the leaked `fie_admin` password in `CLAUDE.md`) is exactly what happens when this rule is broken.

---

## One-time setup (~5 min)

### Step 1 — Find each value

| Env var | What it is | Where to find it |
|---|---|---|
| `EC2_HOST` | SSH target, e.g. `ubuntu@ec2-13-234-x-x.ap-south-1.compute.amazonaws.com` | **AWS Console → EC2 → Instances** → click the instance hosting `clients.jslwealth.in` (the ".214 box") → "Public IPv4 DNS" (or "Public IPv4 address"). Prefix with `ubuntu@` for Ubuntu AMIs or `ec2-user@` for Amazon Linux. |
| `SSH_PRIVATE_KEY` | Full PEM contents (begins with `-----BEGIN OPENSSH PRIVATE KEY-----` or similar) | The `.pem` file you used to launch the instance — usually on your laptop at `~/.ssh/<keyname>.pem`. Run `cat ~/.ssh/<keyname>.pem` and paste the full output. **If lost:** use AWS EC2 Instance Connect (browser SSH from the EC2 console) to log in, then `echo '<new-pub-key>' >> ~/.ssh/authorized_keys` and use the new key. |
| `RDS_MASTER_USER` | Postgres superuser on the RDS instance | **AWS Console → RDS → Databases → `fie-db`** → "Configuration" tab → "Master username". |
| `RDS_MASTER_PW` | Current RDS master password | What you set when creating the RDS instance. **If lost:** rotate it via `aws rds modify-db-instance --db-instance-identifier fie-db --master-user-password '<new>' --apply-immediately --region ap-south-1`. |
| `AWS_ACCESS_KEY_ID` | IAM access key ID, scoped to `rds:Modify*`, `secretsmanager:*`, `ec2:Describe*` (minimum) | **IAM Console → Users → your user → Security credentials** → "Create access key" → choose "Application running outside AWS" → copy the Access Key ID. |
| `AWS_SECRET_ACCESS_KEY` | Secret half of the above | Shown once at creation — copy immediately. If lost, deactivate the key and create a new one. |

Constants (already known, no lookup needed):
- `RDS_HOST` = `fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com`
- `RDS_DATABASE` = `client_portal`
- `AWS_DEFAULT_REGION` = `ap-south-1`
- App container name on EC2: `client-portal`
- App port on EC2: `8007`
- Health check: `curl -sf http://localhost:8007/api/health`

### Step 2 — Paste them into Claude Code project settings

In the Claude Code web app: **your project → Settings → Environment Variables**. Add each row from the table above. The Claude Code platform stores these encrypted and injects them into every future session's container.

### Step 3 — Add the startup script (same settings panel, "Setup script" field)

```bash
#!/bin/bash
set -e

# SSH key
if [ -n "$SSH_PRIVATE_KEY" ]; then
  mkdir -p ~/.ssh && chmod 700 ~/.ssh
  printf '%s\n' "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
  chmod 600 ~/.ssh/id_ed25519
  if [ -n "$EC2_HOST" ]; then
    ssh-keyscan -H "${EC2_HOST##*@}" >> ~/.ssh/known_hosts 2>/dev/null || true
  fi
fi

# AWS CLI (install if absent)
command -v aws >/dev/null 2>&1 || pip install --quiet awscli

# AWS creds → ~/.aws/credentials (CLI reads env vars too, but file is more universal)
if [ -n "$AWS_ACCESS_KEY_ID" ]; then
  mkdir -p ~/.aws
  cat > ~/.aws/credentials <<EOF
[default]
aws_access_key_id = $AWS_ACCESS_KEY_ID
aws_secret_access_key = $AWS_SECRET_ACCESS_KEY
EOF
  cat > ~/.aws/config <<EOF
[default]
region = ${AWS_DEFAULT_REGION:-ap-south-1}
output = json
EOF
  chmod 600 ~/.aws/credentials ~/.aws/config
fi
```

---

## How Claude verifies access (session-start check)

Future sessions run these silently and report a single ✓/✗ line per capability:

```bash
# SSH
ssh -o ConnectTimeout=5 -o BatchMode=yes "$EC2_HOST" 'true' && echo "✓ SSH"

# AWS
aws sts get-caller-identity >/dev/null && echo "✓ AWS"

# RDS via SSH tunnel (sandbox IP almost never on the RDS security group directly)
ssh -fN -L 15432:fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com:5432 "$EC2_HOST"
PGPASSWORD="$RDS_MASTER_PW" psql -h 127.0.0.1 -p 15432 -U "$RDS_MASTER_USER" \
  -d client_portal -c '\conninfo' >/dev/null 2>&1 && echo "✓ RDS (tunneled)"
```

If any of the three fails, Claude reports which one and refuses to proceed with the corresponding capability until it's fixed.

---

## What Claude can do once this is wired

- **Rotate RDS passwords** end-to-end (run the C1 playbook without operator intervention).
- **Deploy** — push to `main`, GitHub Action handles it, then Claude SSHs in to verify `docker logs client-portal | tail` and the health check.
- **Run live recomputes** — `POST /api/admin/recompute-risk` against the deployed system after a math fix lands.
- **Inspect production data** — `psql` to read `cpp_nav_series`, `cpp_risk_metrics` etc. for client-specific debugging (e.g., the drawdown-on-9901 investigation).
- **Update .env on EC2** — credential rotations, JWT secret rotations, feature flags.
- **Restart the container** — `docker restart client-portal` after env changes.
- **Tail logs** — `docker logs -f client-portal` during an incident.

---

## What this file MUST NOT contain (repeat for emphasis)

- ❌ DB passwords (use `RDS_MASTER_PW` env var)
- ❌ IAM access keys (use `AWS_*` env vars)
- ❌ SSH private keys (use `SSH_PRIVATE_KEY` env var)
- ❌ JWT secrets, encryption keys, OAuth client secrets
- ❌ The contents of `.env` on the EC2 box

If a value needs to be available to Claude AND is sensitive, it goes in Claude Code project env vars — never in this file, never in `CLAUDE.md`, never in `DECISIONS_LOG.md`, never in any tracked file. C1 (the `fie_admin:FieAdmin2026!` leak that's currently being scrubbed from git history) is the cautionary tale.

---

## Change log

| Date | Author | Change |
|---|---|---|
| 2026-05-26 | Claude (session synthesis) | Initial — created during Sprint 1 ramp-up after the operator asked for a persistent access path. |
