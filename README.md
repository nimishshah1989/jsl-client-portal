# JSL Client Portfolio Portal (CPP)

**Multi-tenant portfolio dashboard for ~200 PMS/advisory clients of Jhaveri Securities Limited**

Clients log in and see their complete portfolio — NAV performance charts, risk analytics, holdings with P&L, drawdown analysis, allocation breakdowns, and transaction history. All dynamically rendered from their data.

**Live:** [clients.jslwealth.in](https://clients.jslwealth.in)
**Tech Docs:** [clients.jslwealth.in/tech-docs](https://clients.jslwealth.in/tech-docs)

---

## Architecture

```
clients.jslwealth.in (Nginx :443 — SSL)
        │
        ├── /api/*  ──► 127.0.0.1:8008 (FastAPI)
        └── /*      ──► 127.0.0.1:8007 (Next.js)
                │
┌───────────────┴───────────────────────┐
│  Docker Container: client-portal      │
│                                       │
│  Next.js :3000   │   FastAPI :8000    │
│  (Frontend)      │   (API + Auth)     │
└──────────────────┼────────────────────┘
                   │
         RDS PostgreSQL 15
         Database: client_portal
         Table prefix: cpp_
```

Single Dockerfile bundles Next.js + FastAPI. Nginx terminates SSL, routes `/api/*` directly to FastAPI (port 8008) and everything else to Next.js (port 8007).

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL (or RDS access)
- Docker (for production builds)

### Setup

```bash
# Clone
git clone <repo-url>
cd maal-client-reporting

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env from template
cp env.example .env
# Edit .env — fill in DATABASE_URL, JWT_SECRET, ENCRYPTION_KEY

# Initialize database
psql -h <DB_HOST> -U <DB_USER> -d client_portal -f init_db.sql
psql -h <DB_HOST> -U <DB_USER> -d client_portal -f scripts/migration_security_hardening.sql

# Start backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
# Open: http://localhost:3000
```

### Generate Required Secrets

```bash
# JWT Secret (min 32 chars)
openssl rand -hex 32

# Encryption Key (Fernet — for PII encryption)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | Next.js (App Router) | 14.2.x |
| UI | React + Tailwind CSS | 18.3.x |
| Charts | Recharts | 2.15.x |
| Icons | Lucide React | — |
| Backend | FastAPI (async) | 0.115.6 |
| ORM | SQLAlchemy 2.0 (async) | 2.0.36 |
| Database | PostgreSQL 15 (RDS) | — |
| Auth | bcrypt + PyJWT | bcrypt 4.2.1 |
| Encryption | cryptography (Fernet) | 44.0.0 |
| Data | pandas + scipy | 2.2.3 / 1.15.0 |
| Rate Limiting | slowapi | 0.1.9 |
| Docker | Multi-stage build | node:20 + python:3.11 |
| CI/CD | GitHub Actions | Auto-deploy on push to main |

---

## Database Schema (11 tables)

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `cpp_clients` | Client accounts + auth + RBAC | username, password_hash, role, is_deleted |
| `cpp_portfolios` | Portfolio metadata | client_id, portfolio_name, benchmark |
| `cpp_nav_series` | Daily NAV time series (~200K rows) | nav_date, nav_value, benchmark_value, cash_pct |
| `cpp_transactions` | Buy/sell/bonus trades (~100K rows) | txn_date, txn_type, symbol, isin, amount, is_deleted |
| `cpp_holdings` | Current positions (computed) | symbol, isin, qty, avg_cost, current_value, pnl |
| `cpp_risk_metrics` | Computed risk analytics | sharpe, sortino, max_dd, alpha, beta, capture ratios |
| `cpp_drawdown_series` | Drawdown time series | dd_date, drawdown_pct |
| `cpp_cash_flows` | XIRR cash flow inputs | flow_date, flow_amount, flow_type |
| `cpp_upload_log` | Admin upload audit trail | file_type, rows_processed, errors |
| `cpp_audit_log` | SEBI compliance audit trail | action, resource_type, ip_address, request_id |
| `cpp_client_consents` | Client consent tracking | consent_type, accepted, document_version |

### Data Types
- All financial values: `NUMERIC` (Decimal in Python) — **never float**
- NAV values: NUMERIC(18,6) | Prices: NUMERIC(18,4) | Amounts: NUMERIC(18,2)
- Dates: DATE type, never VARCHAR
- Every table has `created_at` and `updated_at` timestamps

### Soft Delete (SEBI 7-year retention)
- `cpp_clients`: `is_deleted`, `deleted_at`, `deleted_by`
- `cpp_transactions`: `is_deleted`, `deleted_at`, `deleted_by`
- Records are never hard-deleted — marked inactive for regulatory compliance

---

## Authentication & Security

### Auth Flow
1. `POST /api/auth/login` validates bcrypt hash (cost factor 12)
2. JWT (HS256, 24hr expiry) set in httpOnly Secure SameSite=Strict cookie
3. CSRF token set in separate readable cookie (double-submit pattern)
4. Every `/api/portfolio/*` scopes queries by `client_id` from JWT
5. Every `/api/admin/*` additionally checks `is_admin`
6. All login success + failure events audit-logged

### Security Measures
- **Transport**: HTTPS (Let's Encrypt), HSTS enforced in production
- **Headers**: CSP, X-Frame-Options: DENY, X-Content-Type-Options, Referrer-Policy
- **CSRF**: Double-submit cookie pattern on all POST/PUT/DELETE
- **Request tracing**: UUID per request (X-Request-ID header)
- **Rate limiting**: 5/min on login + uploads
- **Password complexity**: min 8 chars, upper + lower + digit + special
- **PII encryption**: Fernet (AES-128-CBC + HMAC) via ENCRYPTION_KEY
- **SQL injection**: Parameterized queries only (SQLAlchemy text() + named params)
- **Audit trail**: `cpp_audit_log` tracks logins, admin actions, impersonation
- **No secrets in code**: All credentials in `.env`, validated at startup

### RBAC Roles
| Role | Access |
|------|--------|
| `CLIENT` | Own portfolio data only |
| `ADMIN_FULL` | All admin operations |
| `ADMIN_DATA_ENTRY` | Upload files, update prices |
| `ADMIN_READONLY` | View audit logs, dashboards |

---

## Dashboard Sections (13)

| # | Component | Description |
|---|-----------|-------------|
| 1 | ClientHeader | Welcome, portfolio name, as-of date |
| 2 | SummaryCards | Invested, current, profit, CAGR, YTD, max DD |
| 3 | NavChart | Base-100 performance vs benchmark with cash overlay + time selectors |
| 4 | PerformanceTable | Multi-period returns (1M → inception) with risk metrics |
| 5 | GrowthViz | "What your money became" vs Nifty vs FD |
| 6 | AllocationBar | Asset class allocation labels |
| 7 | HoldingsTable | Sortable holdings with P&L, ISIN, sector |
| 8 | UnderwaterChart | Drawdown analysis vs benchmark |
| 9 | RiskScorecard | Capture ratios, beta, Sharpe, Sortino, stress metrics |
| 10 | MonthlyReturns | Hit rate, heatmap, best/worst month, correlation |
| 11 | TransactionHistory | Paginated, filterable transaction log |
| 12 | MethodologyLink | Link to calculation methodology page |
| 13 | RegulatoryDisclaimer | SEBI compliance disclosures |

### Methodology Page (`/dashboard/methodology`)
Expandable accordion for every metric: plain-English explanation, exact formula, client's actual inputs, worked example with real numbers.

---

## API Reference

### Auth (`/api/auth/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/login` | None | Authenticate, set JWT + CSRF cookies |
| POST | `/logout` | JWT | Clear cookies |
| GET | `/me` | JWT | Current user profile |
| POST | `/change-password` | JWT | Change password (complexity enforced) |
| POST | `/consent` | JWT | Accept/decline consent (SEBI) |
| GET | `/consents` | JWT | List consent records |

### Portfolio (`/api/portfolio/`) — JWT required, client-scoped
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/summary` | Summary cards data |
| GET | `/nav-series?range=1Y` | NAV time series |
| GET | `/performance-table` | Multi-period returns with metrics |
| GET | `/growth` | Growth comparison (portfolio vs Nifty vs FD) |
| GET | `/allocation` | Asset class + sector allocation |
| GET | `/holdings?sort=weight` | Current holdings with P&L |
| GET | `/drawdown-series?range=ALL` | Drawdown underwater chart |
| GET | `/risk-scorecard` | Risk metrics (capture ratios, beta, etc.) |
| GET | `/transactions?page=1` | Paginated transactions |
| GET | `/monthly-returns` | Monthly hit rate + heatmap |
| GET | `/methodology` | All metrics with formulae + inputs |

### Admin (`/api/admin/`) — Admin JWT required
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload-nav` | Upload NAV file (background) |
| POST | `/upload-transactions` | Upload transactions file |
| POST | `/upload-holdings` | Upload holdings reconciliation |
| POST | `/upload-cashflows` | Upload cash flow file |
| POST | `/recompute-risk` | Trigger risk recomputation |
| POST | `/recompute-holdings` | Recalculate holdings from transactions |
| POST | `/update-prices` | Fetch latest NSE prices |
| POST | `/impersonate/{id}` | View as client (audit-logged) |
| POST | `/deduplicate-symbols` | Soft-delete duplicate transactions |
| GET | `/clients` | List all clients |
| POST | `/clients` | Create client |
| POST | `/clients/bulk` | Bulk create from CSV |
| GET | `/upload-log` | Upload history |
| GET | `/dashboard` | Admin analytics |
| GET | `/data-status` | Data freshness report |
| GET | `/aggregate/nav-series` | Firm-wide composite NAV |
| GET | `/aggregate/metrics` | Firm-wide risk metrics |
| POST | `/reconciliation/upload` | Upload holdings for reconciliation |
| GET | `/reconciliation/summary` | Reconciliation results |

### Health
```
GET /api/health → { "status": "healthy", "timestamp": "..." }
```

---

## Data Pipeline

```
Admin uploads .xlsx file (up to 50MB, ~200 clients per file)
    │
    ├── NAV file (.xlsx)
    │   → Stateful row-by-row parser (openpyxl read_only)
    │   → Upsert to cpp_nav_series
    │   → Fetch NIFTY 50 benchmark (yfinance)
    │   → Detect corpus changes → generate XIRR cash flows
    │   → Run risk engine → compute 24 metrics
    │   → Store in cpp_risk_metrics + cpp_drawdown_series
    │
    └── Transaction file (.xlsx)
        → Stateful parser (buy/sell split, ISIN resolution)
        → Upsert to cpp_transactions
        → Recompute cpp_holdings (FIFO cost basis)
```

### Risk Metrics (24 total)
Returns: Absolute, CAGR, XIRR, TWR | Risk: Volatility, Max Drawdown, Sharpe, Sortino | Benchmark: Alpha, Beta, Information Ratio, Tracking Error, Up/Down Capture | Stress: Ulcer Index, Max Consecutive Loss, Market Correlation | Cash: Avg/Max/Current | Monthly: Hit Rate, Best/Worst Month, Win/Loss

---

## Deployment

### CI/CD (GitHub Actions)
Push to `main` triggers auto-deploy:
1. SSH into EC2 → `git pull`
2. `docker build -t client-portal .`
3. Stop old container, start new one
4. Health check: `curl http://localhost:8008/api/health`
5. Update Nginx config

### Port Mapping
| Port | Service | External |
|------|---------|----------|
| 3000 (container) | Next.js | 8007 (EC2) → clients.jslwealth.in/* |
| 8000 (container) | FastAPI | 8008 (EC2) → clients.jslwealth.in/api/* |

### JIP Ecosystem
| Port | Module | Domain |
|------|--------|--------|
| 8002 | India Horizon | horizon.jslwealth.in |
| 8003 | Champion Trader | champion.jslwealth.in |
| 8004 | Market Pulse | marketpulse.jslwealth.in |
| 8005 | MF Pulse | mfpulse.jslwealth.in |
| **8007** | **Client Portal** | **clients.jslwealth.in** |

### Manual Operations
```bash
# SSH to server
ssh ubuntu@<EC2_HOST>
cd ~/apps/client-portal

# View logs
docker logs client-portal --tail 100 -f

# Restart
docker restart client-portal

# Run migration
psql -h <RDS_HOST> -U fie_admin -d client_portal \
  -f scripts/migration_security_hardening.sql
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://user:pass@host:5432/client_portal` |
| `JWT_SECRET` | Yes | Min 32 chars. `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | Yes | Fernet key for PII encryption |
| `APP_ENV` | No | `development` (default) or `production` |
| `JWT_EXPIRY_HOURS` | No | Default: 24 |
| `CORS_ORIGINS` | No | Default: `http://localhost:3000` |
| `RISK_FREE_RATE` | No | Default: 6.50 (India 10Y yield proxy) |
| `LOG_LEVEL` | No | Default: INFO |

---

## SEBI Compliance

| Feature | Status |
|---------|--------|
| Audit trail (logins, admin actions) | Implemented |
| Soft-delete (7-year retention) | Implemented |
| Client consent tracking | Implemented |
| Regulatory disclaimers | Implemented |
| Client data isolation | Implemented |
| Password complexity | Implemented |
| CSRF protection | Implemented |
| Security headers (HSTS, CSP) | Implemented |

---

## Project Structure

```
├── backend/
│   ├── main.py              # FastAPI app + middleware
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLAlchemy engine
│   ├── models/              # 11 ORM models (cpp_* tables)
│   ├── routers/             # 9 route modules
│   ├── services/            # 14 service modules
│   ├── middleware/           # Auth + security middleware
│   ├── schemas/             # Pydantic request/response schemas
│   └── utils/               # Encryption, Indian formatting
├── frontend/
│   └── src/
│       ├── app/             # Next.js App Router pages
│       ├── components/      # React components (dashboard, auth, admin, ui)
│       ├── hooks/           # useAuth, usePortfolio, useAdmin
│       ├── lib/             # API wrapper, formatters, constants
│       └── styles/          # Tailwind globals
├── scripts/                 # SQL migrations, seed scripts
├── Dockerfile               # Multi-stage (node:20 + python:3.11)
├── start.sh                 # Container entrypoint
├── docker-compose.yml       # Local development
├── .github/workflows/       # CI/CD deploy
├── init_db.sql              # Initial schema
└── env.example              # Environment template
```

---

## Development Conventions

- **Financial precision**: Decimal/NUMERIC — never float
- **Indian formatting**: 1,23,456 (Indian grouping), L for Lakhs, Cr for Crores
- **Design system**: JIP light theme — white cards, teal-600 primary, Inter font
- **Data scoping**: Every query includes `WHERE client_id = X` from JWT
- **Font**: `font-mono tabular-nums` for all numbers
- **Colors**: emerald-600 for profit, red-600 for loss

---

## License

Proprietary — Jhaveri Securities Limited. All rights reserved.
