# JSL Client Portfolio Portal

**A multi-tenant client portfolio dashboard for Jhaveri Securities**

Clients log in and see their complete portfolio — interactive performance charts, risk analytics, holdings with P&L, drawdown analysis, and transaction history — all dynamically rendered from their data.

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL (or access to RDS)
- Docker (for production builds)

### 1. Clone & Setup Backend

```bash
git clone https://github.com/nimishshah1989/jsl-client-portal.git
cd jsl-client-portal

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env from template
cp .env.example .env
# Edit .env with your database credentials and JWT secret
```

### 2. Initialize Database

```bash
# Option A: Run SQL script directly
psql -h fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com -U fie_admin -d client_portal -f scripts/init_db.sql

# Option B: Let SQLAlchemy create tables
cd backend && python -c "from database import engine, Base; from models import *; import asyncio; asyncio.run(Base.metadata.create_all(engine))"
```

### 3. Seed Test Data

```bash
python scripts/seed_test_clients.py
# Creates 3 test clients with synthetic NAV series + transactions
# Test credentials printed to stdout
```

### 4. Start Backend

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# API docs: http://localhost:8000/docs
```

### 5. Start Frontend

```bash
cd frontend
npm install
npm run dev
# Open: http://localhost:3000
```

---

## Architecture

```
clients.jslwealth.in
        │
   Nginx (SSL)
        │
   Docker :8007
   ┌────────────┐
   │ Next.js    │ → Pages: /login, /dashboard, /admin
   │   :3000    │
   │     │      │
   │ FastAPI    │ → API: /api/auth/*, /api/portfolio/*, /api/admin/*
   │   :8000    │
   └────┬───────┘
        │
   RDS PostgreSQL
   (fie-db instance)
```

Single Docker container bundles Next.js + FastAPI. Next.js proxies `/api/*` to FastAPI internally — zero CORS issues.

---

## Database

PostgreSQL on existing RDS (`fie-db`). All tables prefixed with `cpp_`.

| Table | Purpose | Key Columns |
|-------|---------|------------|
| `cpp_clients` | Client accounts + auth | username, password_hash, is_admin |
| `cpp_portfolios` | Portfolio metadata | client_id, portfolio_name, benchmark |
| `cpp_nav_series` | Daily NAV time series | nav_date, nav_value, benchmark_value, cash_pct |
| `cpp_transactions` | Buy/sell/SIP history | txn_date, type, symbol, amount |
| `cpp_holdings` | Current position snapshot | symbol, qty, avg_cost, current_value, pnl |
| `cpp_risk_metrics` | Computed risk analytics | sharpe, sortino, max_dd, alpha, beta, capture ratios |
| `cpp_drawdown_series` | Drawdown time series | dd_date, drawdown_pct |
| `cpp_upload_log` | Admin upload audit trail | file_type, rows_processed, errors |

---

## Data Flow

```
Admin uploads 2 CSV files (all ~200 clients in each)
    │
    ├── nav_data.csv ──────→ Parse → Column Map → Validate → Upsert cpp_nav_series
    │                                                              │
    │                                                    Risk Engine computes
    │                                                              │
    │                                                    cpp_risk_metrics
    │                                                    cpp_drawdown_series
    │
    └── transactions.csv ──→ Parse → Column Map → Validate → Upsert cpp_transactions
                                                                   │
                                                         Holdings Engine
                                                                   │
                                                         cpp_holdings (aggregated)
```

---

## Client Dashboard Sections

The dashboard is a single scrollable page with 12 sections:

| # | Section | Description |
|---|---------|-------------|
| 1 | Client Header | Welcome, portfolio name, as-of date |
| 2 | Summary Cards | Invested, Current Value, Profit, CAGR, YTD, Max DD |
| 3 | NAV Chart | Base-100 performance vs benchmark with cash overlay |
| 4 | Performance Table | Multi-period returns (1M→inception) with risk metrics |
| 5 | Growth Visualization | "What your ₹X became" vs Nifty vs FD |
| 6 | Allocation Charts | Donut by class + sector, allocation shift over time |
| 7 | Holdings Table | Sortable holdings with P&L, asset class filter |
| 8 | Underwater Chart | Drawdown analysis vs benchmark |
| 9 | Risk Scorecard | Capture ratios, beta, stress metrics, cash analysis |
| 10 | Monthly Returns | Hit rate, heatmap, best/worst month, correlation |
| 11 | Transaction History | Paginated, filterable transaction log |
| 12 | Commentary | Monthly fund manager notes |
| 13 | Methodology | Every metric explained with formula, inputs, worked example |

---

## Authentication

- **Method:** Username + Password (bcrypt hashed)
- **Session:** JWT in httpOnly Secure cookie (48hr expiry)
- **Scoping:** Every API query filters by `client_id` from JWT — clients can only see their own data
- **Admin:** `is_admin` flag in JWT grants access to upload and client management

### Default Admin Account
Set up during deployment — see `.env.example` for initial admin credentials.

### Client Credentials
Generated in bulk via `scripts/generate_credentials.py`:
```bash
python scripts/generate_credentials.py --input client_list.csv --output credentials.csv
# Output: CSV with username, plain password (for distribution), hash (for DB)
```

---

## API Reference

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login with username/password |
| POST | `/api/auth/logout` | Clear session cookie |
| GET | `/api/auth/me` | Current user info |
| POST | `/api/auth/change-password` | Update password |

### Portfolio (JWT required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/portfolio/summary` | Summary stats for cards |
| GET | `/api/portfolio/nav-series?range=1Y` | NAV time series |
| GET | `/api/portfolio/performance-table` | Multi-period returns |
| GET | `/api/portfolio/growth` | Growth comparison data |
| GET | `/api/portfolio/allocation` | Asset allocation breakdowns |
| GET | `/api/portfolio/holdings` | Current holdings with P&L |
| GET | `/api/portfolio/drawdown-series` | Drawdown chart data |
| GET | `/api/portfolio/risk-scorecard` | Risk metrics |
| GET | `/api/portfolio/transactions?page=1` | Transaction history |
| GET | `/api/portfolio/xirr` | Client-specific XIRR |
| GET | `/api/portfolio/methodology` | All metrics with formulae + inputs for methodology page |

### Admin (Admin JWT required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/upload-nav` | Upload NAV CSV |
| POST | `/api/admin/upload-transactions` | Upload transactions CSV |
| POST | `/api/admin/upload-preview` | Preview file + column mapping |
| POST | `/api/admin/recompute-risk` | Trigger risk recalculation |
| GET | `/api/admin/clients` | List all clients |
| POST | `/api/admin/clients/bulk-create` | Bulk create from CSV |

---

## Deployment

### Production (EC2)

```bash
# On EC2 server
cd ~/apps/client-portal
git pull origin main
docker build -t client-portal .
docker stop client-portal || true && docker rm client-portal || true
docker run -d --name client-portal \
  --env-file .env \
  -p 8007:3000 \
  --restart unless-stopped \
  client-portal
```

### Nginx Config

```nginx
server {
    server_name clients.jslwealth.in;

    location / {
        proxy_pass http://127.0.0.1:8007;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
# SSL via: sudo certbot --nginx -d clients.jslwealth.in
```

### GitHub Actions
Auto-deploys on push to `main`. See `.github/workflows/deploy.yml`.

---

## Port Map (JIP Ecosystem)

| Port | Module | Domain |
|------|--------|--------|
| 8002 | India Horizon | horizon.jslwealth.in |
| 8003 | Champion Trader | champion.jslwealth.in |
| 8004 | Market Pulse | marketpulse.jslwealth.in |
| 8005 | MF Pulse | mfpulse.jslwealth.in |
| 8007 | **Client Portal** | **clients.jslwealth.in** |

---

## Environment Variables

```bash
# .env.example
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/client_portal
DATABASE_URL_SYNC=postgresql://user:pass@host:5432/client_portal
JWT_SECRET=your-secret-here
JWT_EXPIRY_HOURS=48
APP_NAME=JSL Client Portfolio Portal
APP_PORT=8007
APP_ENV=production
CORS_ORIGINS=https://clients.jslwealth.in
RISK_FREE_RATE=6.50
```

---

## Development Notes

- **Financial precision:** All money values use `Decimal` (Python) / `NUMERIC` (PostgreSQL) — never `float`
- **Indian formatting:** ₹1,23,456 (Indian grouping), L for Lakhs, Cr for Crores
- **Design system:** JIP light theme — white backgrounds, teal-600 primary, Inter font, font-mono for numbers
- **Data scoping:** Every portfolio query MUST include `WHERE client_id = X` from JWT — enforced in middleware

---

## License

Proprietary — Jhaveri Securities Limited. All rights reserved.
