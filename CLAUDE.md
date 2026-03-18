# CLAUDE.md — JSL Client Portfolio Portal (CPP)

## ⚠️ GLOBAL ENGINEERING OS — READ FIRST
**This project operates under the Jhaveri Engineering OS installed at `~/.claude/`.**
Before starting any work on this project:
1. Read `~/.claude/CLAUDE.md` (master orchestration, session protocol, absolute prohibitions)
2. Read the agent files relevant to this session from `~/.claude/agents/`
3. Read `~/.claude/standards/CODING_STANDARDS.md` (MAANG-grade code quality rules)
4. Read `~/.claude/protocols/PROTOCOLS.md` (collaboration, review, self-improvement)
5. Then read THIS file for project-specific context

### Active Agents for This Project
| Agent | File | Role in CPP |
|-------|------|-------------|
| **ARCHITECT** | `~/.claude/agents/ARCHITECT.md` | Always active — orchestrates all sessions, enforces design |
| **BACKEND** | `~/.claude/agents/BACKEND.md` | FastAPI APIs, SQLAlchemy models, risk engine, ingestion pipeline |
| **FRONTEND** | `~/.claude/agents/FRONTEND.md` | Next.js dashboard, Recharts visualizations, JIP design system |
| **FULLSTACK** | `~/.claude/agents/FULLSTACK.md` | End-to-end data flow: file upload → parse → DB → API → chart |
| **DEVOPS** | `~/.claude/agents/DEVOPS.md` | Dockerfile, GitHub Actions, Nginx, EC2 deployment |
| **QA** | `~/.claude/agents/QA.md` | Verify metrics match Market Pulse reference, test edge cases |
| **SECURITY** | `~/.claude/agents/SECURITY.md` | Always active — JWT auth, client_id scoping, SQL injection prevention |

### Project-Specific Standards (supplement global standards)
- `DECISIONS_LOG.md` — Append-only architectural decisions for this project
- `LEARNINGS.md` — Claude's self-improvement log for this project
- `FILE_FORMAT_SPEC.md` — PMS backoffice file parsing (critical for ingestion)
- Global `~/.claude/standards/CODING_STANDARDS.md` applies PLUS the financial-specific rules below

### Session Opening Protocol (CPP-Specific)
```
[ARCHITECT] Reading ~/.claude/CLAUDE.md (global OS)...
[ARCHITECT] Reading project CLAUDE.md (CPP context)...
[ARCHITECT] Task analysis: [describe task]
[ARCHITECT] Activating: BACKEND + FRONTEND + SECURITY + QA
[ARCHITECT] CPP-specific rules active:
  → Decimal for all financial values (never float)
  → Indian number formatting (₹1,23,456)
  → Every query scoped by client_id from JWT
  → JIP design system (teal-600 primary, Inter font, light theme)
  → All metrics must match formulae in Risk Computation Engine section
[SECURITY] Confirming: JWT httpOnly cookies, bcrypt cost 12, no client data in URLs
```

---

## Project Identity
- **Module:** Client Portfolio Portal (CPP)
- **Repo:** `jsl-client-portal`
- **Domain:** `clients.jslwealth.in`
- **Port:** 8007 (EC2 internal)
- **Pattern:** MF Pulse (single Dockerfile: Next.js frontend + FastAPI backend)
- **Database:** Existing RDS — `fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com`
- **DB Name:** `client_portal` (new database on existing RDS instance)
- **Table Prefix:** `cpp_` (to avoid collisions if sharing DB)
- **Status:** Active Development

---

## What This Project Is

A multi-tenant client portfolio dashboard for ~200 Jhaveri Securities PMS/advisory clients. Each client logs in with username/password and sees their complete portfolio — NAV performance charts, risk scorecard, holdings with P&L, drawdowns, allocation breakdowns, and transaction history. All rendered dynamically from their data.

The **existing reference implementation** is the Model Portfolios page on Market Pulse (`marketpulse.jslwealth.in/portfolios?id=4`). The client portal takes that exact visual language — NAV chart with cash overlay, performance summary table, allocation donuts, underwater chart, risk management scorecard, monthly return profile — and extends it for per-client use with additional sections (holdings table, transaction history, growth visualization, personalized XIRR).

**Admin side:** Nimish/Jeet upload two consolidated CSV files (one for NAVs, one for transactions) covering all clients. The system parses, ingests, computes risk metrics, and makes data available per-client.

---

## Architecture

```
clients.jslwealth.in (Nginx SSL :443)
        │
        ▼
┌──────────────────┐
│  Docker :8007    │
│                  │
│  Next.js :3000   │  ← /login, /dashboard, /admin
│       │          │
│  FastAPI :8000   │  ← /api/auth/*, /api/portfolio/*, /api/admin/*
│       │          │
└───────┼──────────┘
        │
  RDS PostgreSQL
  (fie-db instance)
  database: client_portal
```

**Critical architectural rule:** This follows the MF Pulse single-Dockerfile pattern. Frontend (Next.js) and backend (FastAPI) are bundled in ONE Docker container. Next.js proxies /api/* to FastAPI internally. This eliminates CORS issues entirely. DO NOT create separate frontend/backend deployments or use Vercel for frontend.

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Frontend | Next.js 14 (App Router) | Single page dashboard, no SSR needed for dashboard — CSR with loading states |
| UI | React 18 + Tailwind CSS | JIP design system (see below) |
| Charts | Recharts | Line, Area, Bar, Pie/Donut, ComposedChart |
| Icons | Lucide React | Consistent with other JIP modules |
| Backend | FastAPI (Python 3.11) | Async endpoints, SQLAlchemy ORM |
| Database | PostgreSQL 15 (RDS) | Existing `fie-db` instance |
| ORM | SQLAlchemy 2.0 (async) | With asyncpg driver |
| Auth | bcrypt + JWT | passlib for hashing, python-jose for tokens |
| Data Processing | pandas + numpy + scipy | Risk metric computation, XIRR via brentq |
| File Parsing | openpyxl (read_only mode) | Memory-efficient .xlsx parsing for 35MB files |
| Benchmark Data | yfinance | Fetch Nifty 50 index data for comparison |
| Docker | Single Dockerfile (multi-stage) | Node build stage → Python runtime stage |
| CI/CD | GitHub Actions | Auto-deploy on push to main |

---

## Project Structure

```
jsl-client-portal/
├── CLAUDE.md                       ← This file (project-specific, references global ~/.claude/ OS)
├── FILE_FORMAT_SPEC.md             ← Exact PMS backoffice file format + parsing algorithms
├── DECISIONS_LOG.md                ← Append-only architectural decisions (per global OS protocol)
├── LEARNINGS.md                    ← Claude's self-improvement log (per global OS protocol)
├── README.md
├── Dockerfile
├── start.sh
├── docker-compose.yml
├── .github/
│   └── workflows/
│       └── deploy.yml
│
├── backend/
│   ├── main.py                     ← FastAPI app entry point
│   ├── requirements.txt
│   ├── config.py                   ← Environment config
│   ├── database.py                 ← SQLAlchemy engine + session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── client.py               ← cpp_clients table
│   │   ├── portfolio.py            ← cpp_portfolios table
│   │   ├── nav_series.py           ← cpp_nav_series table
│   │   ├── transaction.py          ← cpp_transactions table
│   │   ├── holding.py              ← cpp_holdings table
│   │   ├── risk_metric.py          ← cpp_risk_metrics table
│   │   ├── drawdown.py             ← cpp_drawdown_series table
│   │   └── upload_log.py           ← cpp_upload_log table
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py                 ← Login request/response schemas
│   │   ├── portfolio.py            ← Portfolio data response schemas
│   │   └── admin.py                ← Upload/admin schemas
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py                 ← POST /api/auth/login, /logout, /me, /change-password
│   │   ├── portfolio.py            ← GET /api/portfolio/* (JWT-protected, client-scoped)
│   │   └── admin.py                ← POST /api/admin/* (admin-only)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py         ← Password hashing, JWT create/verify
│   │   ├── nav_parser.py           ← Parse NAV .xlsx (stateful row-by-row, see FILE_FORMAT_SPEC.md)
│   │   ├── txn_parser.py           ← Parse Transaction .xlsx (stateful, buy/sell split)
│   │   ├── ingestion_service.py    ← Orchestrates parsing → validation → upsert → risk compute
│   │   ├── risk_engine.py          ← Compute all risk metrics from NAV series
│   │   ├── holdings_service.py     ← Compute current holdings from transactions
│   │   ├── benchmark_service.py    ← Fetch Nifty 50 data via yfinance, align dates
│   │   └── xirr_service.py         ← XIRR calculation from corpus change detection
│   ├── middleware/
│   │   └── auth_middleware.py      ← JWT extraction + client_id scoping
│   └── utils/
│       └── indian_format.py        ← ₹ formatting, lakh/crore, Indian number grouping
│
├── frontend/
│   ├── package.json
│   ├── next.config.js              ← Proxy /api/* to FastAPI :8000
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── public/
│   │   └── favicon.ico
│   └── src/
│       ├── app/
│       │   ├── layout.js           ← Root layout with Inter font
│       │   ├── page.js             ← Redirect to /login or /dashboard
│       │   ├── login/
│       │   │   └── page.js         ← Login page
│       │   ├── dashboard/
│       │   │   ├── layout.js       ← Dashboard layout with sidebar
│       │   │   ├── page.js         ← Main dashboard (single scrollable page, all 12 sections)
│       │   │   └── methodology/
│       │   │       └── page.js     ← Calculation methodology (accordion with all formulae + worked examples)
│       │   └── admin/
│       │       ├── layout.js       ← Admin layout
│       │       ├── page.js         ← Admin dashboard (upload, client list)
│       │       └── upload/
│       │           └── page.js     ← CSV upload with column mapper preview
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.jsx         ← JIP sidebar with client name
│       │   │   └── MarketTicker.jsx    ← Top-right market ticker strip
│       │   ├── dashboard/
│       │   │   ├── SummaryCards.jsx     ← 6 stat cards (invested, current, profit, CAGR, YTD, max DD)
│       │   │   ├── NavChart.jsx        ← Base-100 performance chart with cash overlay + time range selectors
│       │   │   ├── PerformanceTable.jsx ← Multi-period returns table (abs, CAGR, vol, DD, Sharpe, Sortino)
│       │   │   ├── GrowthViz.jsx       ← "What your ₹X became" bar chart (portfolio vs Nifty vs FD)
│       │   │   ├── AllocationCharts.jsx ← Donut by class + donut by sector + allocation shift area chart
│       │   │   ├── HoldingsTable.jsx    ← Sortable holdings with P&L, filtering by asset class
│       │   │   ├── UnderwaterChart.jsx  ← Drawdown chart with benchmark comparison
│       │   │   ├── RiskScorecard.jsx    ← Risk gauge cards + capture ratios + stress metrics
│       │   │   ├── MonthlyReturns.jsx   ← Monthly hit rate + heatmap grid + best/worst
│       │   │   ├── TransactionHistory.jsx ← Paginated, filterable transaction table
│       │   │   ├── Commentary.jsx       ← Monthly fund manager commentary section
│       │   │   └── MethodologyAccordion.jsx ← Expandable metrics with formulae + worked examples
│       │   ├── auth/
│       │   │   └── LoginForm.jsx
│       │   ├── admin/
│       │   │   ├── FileUpload.jsx       ← Drag-drop CSV upload
│       │   │   ├── ColumnMapper.jsx     ← Preview + confirm column mapping
│       │   │   └── ClientManager.jsx    ← Create/edit client credentials
│       │   └── ui/
│       │       ├── Card.jsx
│       │       ├── Badge.jsx
│       │       ├── Button.jsx
│       │       ├── Table.jsx
│       │       └── Spinner.jsx
│       ├── hooks/
│       │   ├── useAuth.js           ← JWT token management, login/logout
│       │   ├── usePortfolio.js      ← Fetch portfolio data hooks
│       │   └── useAdmin.js          ← Admin operations hooks
│       ├── lib/
│       │   ├── api.js               ← Fetch wrapper with JWT header injection
│       │   ├── format.js            ← Indian number formatting, date formatting
│       │   └── constants.js         ← Chart colors, time ranges, etc.
│       └── styles/
│           └── globals.css          ← Tailwind imports + custom scrollbar + font imports
│
├── scripts/
│   ├── init_db.sql                  ← Create all cpp_ tables
│   ├── seed_test_clients.py         ← Seed 3 test clients with synthetic data
│   └── generate_credentials.py      ← Bulk generate credentials from client list CSV
│
└── data/
    ├── sample_nav.csv               ← Sample NAV file for testing
    └── sample_transactions.csv      ← Sample transactions file for testing
```

---

## Database Schema

All tables use `cpp_` prefix. Database: `client_portal` on existing RDS.

### Tables (8 total)
1. **cpp_clients** — client_code, name, email, phone, username (unique, lowercase), password_hash (bcrypt), is_active, is_admin, last_login
2. **cpp_portfolios** — client_id FK, portfolio_name, benchmark (default 'NIFTY500'), inception_date, status
3. **cpp_nav_series** — client_id, portfolio_id, nav_date, nav_value (NUMERIC 18,6), invested_amount, current_value, benchmark_value, cash_pct. UNIQUE(client_id, portfolio_id, nav_date). INDEX on (client_id, portfolio_id, nav_date)
4. **cpp_transactions** — client_id, portfolio_id, txn_date, txn_type (BUY/SELL/SIP/DIVIDEND/SWITCH_IN/SWITCH_OUT/REDEMPTION), symbol, asset_name, asset_class, quantity, price, amount
5. **cpp_holdings** — client_id, portfolio_id, symbol, asset_name, asset_class, quantity, avg_cost, current_price, current_value, unrealized_pnl, weight_pct, sector. UNIQUE(client_id, portfolio_id, symbol)
6. **cpp_risk_metrics** — client_id, portfolio_id, computed_date, absolute_return, cagr, xirr, volatility, sharpe_ratio, sortino_ratio, max_drawdown, max_dd_start/end/recovery, alpha, beta, information_ratio, tracking_error, up_capture, down_capture, ulcer_index, monthly_hit_rate, return_1m/3m/6m/1y/2y/3y/5y/inception, risk_free_rate (default 6.50)
7. **cpp_drawdown_series** — client_id, portfolio_id, dd_date, drawdown_pct, peak_nav, current_nav. INDEX on (client_id, portfolio_id, dd_date)
8. **cpp_upload_log** — uploaded_by FK, file_type, filename, rows_processed, rows_failed, errors (JSONB), uploaded_at

### Critical Data Rules
- ALL financial values use NUMERIC (Decimal in Python) — NEVER float
- Prices stored with 4 decimal places (NUMERIC 18,4)
- NAV values stored with 6 decimal places (NUMERIC 18,6)
- Amounts stored with 2 decimal places (NUMERIC 18,2)
- Dates stored as DATE type, never VARCHAR
- client_id scoping on EVERY query — no exceptions

---

## Authentication

### Flow
1. Client enters username + password at `/login`
2. `POST /api/auth/login` validates credentials (bcrypt verify)
3. Returns JWT token (HS256, 48hr expiry) containing `{ sub: client_id, admin: bool }`
4. Token stored in httpOnly Secure SameSite=Strict cookie
5. Every `/api/portfolio/*` endpoint extracts client_id from JWT and adds `WHERE client_id = X` to all queries
6. `/api/admin/*` endpoints additionally check `admin == true`

### Password Rules
- bcrypt with cost factor 12
- Min 8 characters for admin-set passwords
- Bulk credential generation script outputs CSV with plain passwords for WhatsApp distribution + hashed passwords for DB insert
- Clients can change password via `/dashboard` settings

### JWT Secret
- Generated via `openssl rand -hex 32`
- Stored in `.env` as `JWT_SECRET`
- Never hardcoded, never committed

---

## API Endpoints

### Auth (`/api/auth/`)
```
POST /login              { username, password } → { token, client_name, portfolio_count }
POST /logout             Clear httpOnly cookie
POST /change-password    { old_password, new_password } → { success }
GET  /me                 → { client_id, name, email, is_admin, last_login }
```

### Portfolio (`/api/portfolio/`) — All JWT-protected, all scoped to client_id
```
GET /summary                           → Summary cards data (invested, current, profit, CAGR, YTD, max DD)
GET /nav-series?range=1Y               → NAV time series [{date, nav, benchmark, cash_pct}]
GET /performance-table                 → Multi-period returns table with all metrics
GET /growth                            → Growth comparison (portfolio vs benchmark vs FD)
GET /allocation                        → {by_class: [...], by_sector: [...], over_time: [...]}
GET /holdings?sort=weight&order=desc   → Current holdings with P&L
GET /drawdown-series?range=ALL         → Drawdown underwater chart data
GET /risk-scorecard?range=ALL          → Risk metrics (capture ratios, stress metrics, monthly profile)
GET /transactions?page=1&per_page=50   → Paginated transactions with filters
GET /xirr                              → Client-specific XIRR based on their cash flows
GET /methodology                       → All metrics with values, formulae, inputs for methodology page
```

### Admin (`/api/admin/`) — Admin JWT required
```
POST /upload-nav                → Upload NAV CSV, parse, ingest, return summary
POST /upload-transactions       → Upload transactions CSV, parse, ingest, return summary
POST /recompute-risk            → Trigger risk recomputation for all or specific clients
GET  /clients                   → List all clients with summary stats
POST /clients                   → Create single client with credentials
POST /clients/bulk-create       → Bulk create from CSV
PUT  /clients/{id}              → Update client info/credentials
GET  /upload-log                → Upload history with row counts and errors
POST /upload-preview            → Preview file: show first 10 rows + auto-mapped columns
```

---

## Dashboard Page Structure (Single Scrollable Page)

The client dashboard is ONE page (`/dashboard/page.js`) with 12 sections rendered in scroll order. Each section is a self-contained React component that fetches its own data. Use section anchors for sidebar navigation.

### Section Order
```
1.  ClientHeader        — Welcome message, portfolio name, as-of date, download button
2.  SummaryCards        — 6 stat cards in a row
3.  NavChart            — Relative performance (base 100) with cash overlay + time selectors
4.  PerformanceTable    — Multi-period returns (1M → inception) × (Abs, CAGR, Vol, DD, Sharpe, Sortino)
5.  GrowthViz           — "What your ₹X became" bar comparison
6.  AllocationCharts    — Donut by class + donut by sector + allocation shift area chart
7.  HoldingsTable       — Sortable holdings with P&L + asset class filter
8.  UnderwaterChart     — Drawdown chart with benchmark dashed line
9.  RiskScorecard       — Capture ratios, beta, info ratio, ulcer index, consecutive loss, cash metrics
10. MonthlyReturns      — Hit rate, best/worst, heatmap grid, win/loss bar
11. TransactionHistory  — Paginated table with date/type/class filters
12. Commentary          — Monthly fund manager notes (static or from DB)
13. MethodologyLink     — "View Calculation Methodology" button → /dashboard/methodology
```

### Methodology Page (`/dashboard/methodology`)
Separate page (not inline accordion on dashboard) — accessible from sidebar nav "📐 Methodology"
and from the link at the bottom of the dashboard. Contains expandable accordion for every metric 
with: plain-English explanation, exact formula, client's actual inputs, worked example with real numbers.
See "Section 13: Calculation Methodology Page" below for full spec.

### How Each Section Maps to Market Pulse Reference

| CPP Section | Market Pulse Equivalent | What Changes |
|-------------|------------------------|-------------|
| SummaryCards | Current NAV / Corpus / CAGR / Max DD cards | Show client's invested ₹, current ₹, profit ₹/%, add YTD |
| NavChart | "Relative Performance (Base 100)" chart | Same — keep cash overlay, add client investment date markers |
| PerformanceTable | "Performance Summary — Portfolio vs NIFTY 50" table | Same structure — add XIRR row for client-specific return |
| AllocationCharts | "Portfolio Allocation" donuts + shift chart | Same — add horizontal asset class bar |
| UnderwaterChart | "Underwater Chart (Drawdown %)" | Same — add investment date markers |
| RiskScorecard | "Risk Management Scorecard" cards | Same — add simplified risk gauge at top |
| MonthlyReturns | "Monthly Return Profile" + Win/Loss bar | Same — add monthly heatmap grid |
| GrowthViz | NEW | Personalized "what your money became" |
| HoldingsTable | NEW | Client-specific holdings with P&L |
| TransactionHistory | NEW | Client-specific transaction log |
| Commentary | NEW | Fund manager monthly notes |
| MethodologyLink | "View calculation methodology" at bottom of Market Pulse | Full page with accordion, formulae, worked examples using client's actual numbers |

---

## Data Ingestion Pipeline

**CRITICAL: See FILE_FORMAT_SPEC.md for complete parsing logic with code examples.**

The input files are PMS backoffice .xlsx exports — NOT simple flat CSVs. They have embedded client name headers, date separator rows, merged buy/sale columns, and subtotal rows. Stateful row-by-row parsing is required.

### Input Files (Admin uploads — 2 files, each ~35MB for 200 clients)

**File 1 — NAV Report (.xlsx)**
Columns: UCC, Date, Corpus, Equity Holding At Mkt, Cash And Cash Equivalent, Bank Balance, NAV, Liquidity %, High Water Mark
- Row types: Client name header "[NAME [CODE]]" → data rows → subtotal → next client
- Date format: DD-MMM-YYYY (e.g., "28-Sep-2020")
- NAV is ABSOLUTE ₹ value (e.g., ₹50,80,100), NOT normalized base-100
- Corpus = total invested (steps up on new infusions — detect changes for XIRR cash flows)
- Liquidity % = cash as % of NAV (already computed)
- NO benchmark data in file — fetch Nifty separately via yfinance

**File 2 — Transaction Report (.xlsx)**
20 columns: UCC, Script, Exch, Stno, then 8 Buy cols, then 8 Sale cols
- Row types: Sub-header (row 0) → Client name header → Date separator ("Date :DD/MM/YY") → data rows → daily subtotal → next date/client
- Script format: "RELIANCE     EQ" — parse into (symbol, instrument_type)
- Stno types: "Corpus" (initial positions), "BONUS" (bonus shares), settlement numbers (regular trades)
- A row can have BOTH buy and sell data — check buy_qty AND sale_qty independently
- Cash instruments: LIQUIDBEES, LIQUIDETF, LIQUIDCASE → asset_class = "CASH"

### Processing Steps
1. Read .xlsx with openpyxl read_only mode (memory efficient for 35MB files)
2. Parse row-by-row with state tracking (current_client, current_date)
3. For each client_code: find-or-create in cpp_clients (use extracted name from header row)
4. Auto-create portfolio in cpp_portfolios (portfolio_name = "PMS Equity", inception from first NAV date)
5. Upsert NAV rows (ON CONFLICT nav_date DO UPDATE)
6. Upsert transaction rows (splitting buy/sell into separate records)
7. After NAV upload: fetch Nifty benchmark data → store in cpp_nav_series.benchmark_value
8. After NAV upload: detect corpus changes → compute XIRR cash flows
9. After NAV upload: run risk engine → cpp_risk_metrics + cpp_drawdown_series
10. After transactions: recompute cpp_holdings (aggregate buys/sells per symbol)
11. Admin UI shows progress: "Processing client 47 of 203..."
12. Log upload in cpp_upload_log with row counts + any parse errors

---

## Risk Computation Engine — COMPLETE FORMULAE

Triggered after every NAV data upload. Operates per (client_id, portfolio_id).
Every formula below MUST be implemented exactly as specified — these are displayed
to clients on the Calculation Methodology page, so the code must match the math.

### Input Data
```python
# nav_df: DataFrame with columns [nav_date, nav_value, benchmark_value, cash_pct]
# nav_value = absolute portfolio value in ₹ (from NAV file)
# benchmark_value = Nifty 50 close price (fetched via yfinance)
# cash_pct = Liquidity % from NAV file
# risk_free_rate = 6.50% (India 10Y govt bond yield proxy)

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from decimal import Decimal
```

### 1. TWR Index (Time-Weighted Return — Base 100)
```python
# The NAV file gives absolute ₹ values. For fair comparison, normalize both
# portfolio and benchmark to a base of 100 from the inception date.
# TWR eliminates the effect of cash inflows/outflows.

port_index = (nav_df['nav_value'] / nav_df['nav_value'].iloc[0]) * 100
bench_index = (nav_df['benchmark_value'] / nav_df['benchmark_value'].iloc[0]) * 100

# These are what the chart plots — both start at 100, diverge based on performance.
```

### 2. Daily Returns
```python
# Simple daily returns (NOT log returns)
daily_port_ret = nav_df['nav_value'].pct_change().dropna()   # (P_t - P_{t-1}) / P_{t-1}
daily_bench_ret = nav_df['benchmark_value'].pct_change().dropna()

# Excess daily returns (portfolio minus benchmark)
daily_excess_ret = daily_port_ret - daily_bench_ret
```

### 3. Period Returns (Absolute Return)
```python
def absolute_return(nav_series: pd.Series, days: int) -> float:
    """
    Trailing absolute return over N calendar days.
    Formula: (NAV_end / NAV_start) - 1
    Expressed as percentage.
    """
    end_val = nav_series.iloc[-1]
    # Find the NAV closest to (end_date - N days)
    target_date = nav_series.index[-1] - pd.Timedelta(days=days)
    start_val = nav_series.asof(target_date)
    return ((end_val / start_val) - 1) * 100

# Periods:
# 1M  = 30 days, 3M = 91 days, 6M = 182 days
# 1Y  = 365 days, 2Y = 730 days, 3Y = 1095 days
# 4Y  = 1461 days, 5Y = 1826 days
# Inception = from first NAV date to latest
```

### 4. CAGR (Compound Annual Growth Rate)
```python
def cagr(start_value: float, end_value: float, days: int) -> float:
    """
    Formula: ((end / start) ^ (365.25 / days)) - 1
    Uses 365.25 to account for leap years.
    Expressed as percentage.
    """
    if days <= 0 or start_value <= 0:
        return 0.0
    years = days / 365.25
    return ((end_value / start_value) ** (1 / years) - 1) * 100

# Compute for each period: 1M, 3M, 6M, 1Y, 2Y, 3Y, 4Y, 5Y, Inception
# Also compute for benchmark over same periods
```

### 5. XIRR (Extended Internal Rate of Return — Client-Specific)
```python
def compute_xirr(cash_flows: list[tuple], guess: float = 0.1) -> float:
    """
    XIRR = the rate r that makes NPV of all cash flows = 0.
    
    Formula: Σ (CF_i / (1 + r) ^ ((date_i - date_0) / 365)) = 0
    
    Cash flows derived from Corpus changes in NAV file:
    - Corpus goes from ₹3.33L to ₹5.33L on date X → CF = +₹2.00L on date X
    - Final entry: CF = -(current portfolio value) on latest date
    
    Uses scipy.optimize.brentq to solve for r.
    
    This is the client's TRUE personalized return accounting for
    when they actually invested money.
    """
    dates = [cf[0] for cf in cash_flows]
    amounts = [cf[1] for cf in cash_flows]
    
    # Days from first cash flow
    d0 = dates[0]
    day_offsets = [(d - d0).days / 365.0 for d in dates]
    
    def npv(rate):
        return sum(amt / (1 + rate) ** t for amt, t in zip(amounts, day_offsets))
    
    try:
        return brentq(npv, -0.99, 10.0) * 100  # Return as percentage
    except ValueError:
        return 0.0  # No solution found
```

### 6. Volatility (Annualized Standard Deviation)
```python
def annualized_volatility(daily_returns: pd.Series) -> float:
    """
    Formula: σ_annual = σ_daily × √252
    Where σ_daily = standard deviation of daily returns
    252 = trading days per year (India: NSE has ~248-252 trading days)
    Expressed as percentage.
    """
    return daily_returns.std() * np.sqrt(252) * 100
```

### 7. Sharpe Ratio
```python
def sharpe_ratio(cagr_pct: float, volatility_pct: float, risk_free_rate: float = 6.50) -> float:
    """
    Formula: (R_p - R_f) / σ_p
    Where:
      R_p = portfolio CAGR (annualized return) — already in %
      R_f = risk-free rate (6.50% = India 10Y govt bond yield)
      σ_p = annualized volatility — already in %
    
    Interpretation:
      > 1.0 = Good risk-adjusted returns
      > 2.0 = Excellent
      < 0   = Returns below risk-free rate
    """
    if volatility_pct == 0:
        return 0.0
    return (cagr_pct - risk_free_rate) / volatility_pct
```

### 8. Sortino Ratio
```python
def sortino_ratio(cagr_pct: float, daily_returns: pd.Series, risk_free_rate: float = 6.50) -> float:
    """
    Formula: (R_p - R_f) / σ_downside
    Where:
      σ_downside = √(252) × √(mean(min(R_daily, 0)²))
      Only NEGATIVE daily returns contribute to downside deviation.
    
    Sortino penalizes only downside volatility — upside volatility is a good thing.
    More appropriate than Sharpe for portfolios with asymmetric returns.
    """
    downside = daily_returns[daily_returns < 0]
    if len(downside) == 0:
        return 0.0
    downside_dev = np.sqrt((downside ** 2).mean()) * np.sqrt(252) * 100
    if downside_dev == 0:
        return 0.0
    return (cagr_pct - risk_free_rate) / downside_dev
```

### 9. Maximum Drawdown
```python
def max_drawdown(nav_series: pd.Series) -> dict:
    """
    Formula: Max DD = max( (Peak_t - NAV_t) / Peak_t ) over all t
    Where Peak_t = max(NAV_0, NAV_1, ..., NAV_t) = running maximum
    
    Returns dict with:
      max_dd_pct:  maximum drawdown as negative percentage (e.g., -18.48%)
      dd_start:    date when the peak before the max drawdown was reached
      dd_end:      date when the trough (lowest point) was reached
      dd_recovery: date when NAV recovered to the peak (None if not recovered)
    """
    running_max = nav_series.cummax()
    drawdown = (nav_series - running_max) / running_max
    
    max_dd_pct = drawdown.min() * 100
    trough_idx = drawdown.idxmin()
    peak_idx = nav_series[:trough_idx].idxmax()
    
    # Recovery: first date after trough where NAV >= peak value
    peak_value = nav_series[peak_idx]
    recovery = nav_series[trough_idx:][nav_series[trough_idx:] >= peak_value]
    recovery_idx = recovery.index[0] if len(recovery) > 0 else None
    
    return {
        'max_dd_pct': max_dd_pct,
        'dd_start': peak_idx,
        'dd_end': trough_idx,
        'dd_recovery': recovery_idx,
    }
```

### 10. Drawdown Series (for Underwater Chart)
```python
def compute_drawdown_series(nav_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each date, compute how far the portfolio has fallen from its peak.
    
    Formula: DD_t = (NAV_t - Peak_t) / Peak_t × 100
    Where Peak_t = max(NAV from inception to date t)
    
    A value of 0% = at or above the peak (no drawdown)
    A value of -18.5% = portfolio is 18.5% below its all-time high
    The deepest red area represents the worst peak-to-trough decline.
    
    Also compute benchmark drawdown for comparison overlay.
    
    Uses TWR-adjusted NAV values so drawdowns reflect true investment 
    performance excluding the effect of capital inflows/outflows.
    """
    port_peak = nav_df['nav_value'].cummax()
    port_dd = ((nav_df['nav_value'] - port_peak) / port_peak) * 100
    
    bench_peak = nav_df['benchmark_value'].cummax()
    bench_dd = ((nav_df['benchmark_value'] - bench_peak) / bench_peak) * 100
    
    return pd.DataFrame({
        'dd_date': nav_df['nav_date'],
        'drawdown_pct': port_dd,
        'bench_drawdown': bench_dd,
        'peak_nav': port_peak,
        'current_nav': nav_df['nav_value'],
    })
```

### 11. Beta
```python
def beta(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Formula: β = Cov(R_p, R_b) / Var(R_b)
    
    Measures portfolio sensitivity to market movements.
      β = 1.0: moves exactly with the market
      β < 1.0: less volatile than the market (defensive)
      β > 1.0: more volatile than the market (aggressive)
    
    Jhaveri Multi-Asset Alpha typically shows β < 1 due to tactical cash positioning.
    """
    cov_matrix = np.cov(daily_port_ret, daily_bench_ret)
    return cov_matrix[0, 1] / cov_matrix[1, 1]
```

### 12. Alpha (Jensen's Alpha)
```python
def alpha(port_cagr: float, bench_cagr: float, beta_val: float, risk_free_rate: float = 6.50) -> float:
    """
    Formula: α = R_p - [R_f + β × (R_b - R_f)]
    
    Excess return beyond what the portfolio's market risk (beta) would predict.
    Positive alpha = manager skill / strategy adds value above market exposure.
    """
    expected_return = risk_free_rate + beta_val * (bench_cagr - risk_free_rate)
    return port_cagr - expected_return
```

### 13. Up Capture Ratio
```python
def up_capture(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Formula: Up Capture = (mean of port returns on UP days) / (mean of bench returns on UP days) × 100
    
    "UP days" = days when benchmark return > 0
    
    Measures what % of the benchmark's gains the portfolio captures on up days.
    > 100% = we gain MORE than the market when it rises
    < 100% = we gain less than the market when it rises (acceptable if down capture is also low)
    """
    up_days = daily_bench_ret > 0
    if up_days.sum() == 0:
        return 0.0
    port_up = daily_port_ret[up_days].mean()
    bench_up = daily_bench_ret[up_days].mean()
    return (port_up / bench_up) * 100
```

### 14. Down Capture Ratio
```python
def down_capture(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Formula: Down Capture = (mean of port returns on DOWN days) / (mean of bench returns on DOWN days) × 100
    
    "DOWN days" = days when benchmark return < 0
    
    Measures what % of the benchmark's losses the portfolio absorbs on down days.
    < 100% = we lose LESS than the market when it falls (this is the goal)
    > 100% = we lose more than the market when it falls (bad)
    
    Ideal: Low down capture + reasonable up capture = asymmetric returns
    """
    down_days = daily_bench_ret < 0
    if down_days.sum() == 0:
        return 0.0
    port_down = daily_port_ret[down_days].mean()
    bench_down = daily_bench_ret[down_days].mean()
    return (port_down / bench_down) * 100
```

### 15. Information Ratio
```python
def information_ratio(port_cagr: float, bench_cagr: float, tracking_error_val: float) -> float:
    """
    Formula: IR = (R_p - R_b) / TE
    Where TE = Tracking Error (annualized std of excess returns)
    
    Measures risk-adjusted excess return over the benchmark.
    > 0.5 = good active management
    > 1.0 = excellent
    """
    if tracking_error_val == 0:
        return 0.0
    return (port_cagr - bench_cagr) / tracking_error_val
```

### 16. Tracking Error
```python
def tracking_error(daily_excess_ret: pd.Series) -> float:
    """
    Formula: TE = σ(R_p - R_b) × √252
    Annualized standard deviation of the difference between portfolio and benchmark returns.
    
    Low TE = portfolio closely tracks the benchmark
    High TE = portfolio deviates significantly (active management)
    """
    return daily_excess_ret.std() * np.sqrt(252) * 100
```

### 17. Ulcer Index
```python
def ulcer_index(nav_series: pd.Series) -> float:
    """
    Formula: UI = √(mean(DD_i²))
    Where DD_i = percentage drawdown from peak on day i
    
    Unlike Max Drawdown (which shows only the worst), Ulcer Index measures the
    DEPTH AND DURATION of ALL drawdowns via their root-mean-square.
    
    Scale interpretation:
      0–2:   Very low stress (rare, deep drawdowns)
      2–5:   Low stress
      5–10:  Moderate stress
      10–20: High stress
      20+:   Severe stress
    """
    running_max = nav_series.cummax()
    drawdown_pct = ((nav_series - running_max) / running_max) * 100  # Negative values
    return np.sqrt((drawdown_pct ** 2).mean())
```

### 18. Monthly Return Profile
```python
def monthly_return_profile(nav_df: pd.DataFrame) -> dict:
    """
    Resample daily NAV to monthly, compute month-over-month returns.
    
    Monthly return = (NAV_last_day_of_month / NAV_last_day_of_prev_month) - 1
    
    Returns:
      monthly_returns:    Series of monthly returns
      hit_rate:           % of months with positive returns
      best_month:         highest single-month return
      worst_month:        lowest single-month return
      avg_positive_month: average return in positive months
      avg_negative_month: average return in negative months
      max_consecutive_loss: longest streak of negative months
      win_loss_counts:    (win_count, loss_count)
    """
    monthly = nav_df.set_index('nav_date')['nav_value'].resample('ME').last()
    monthly_ret = monthly.pct_change().dropna() * 100
    
    positive = monthly_ret[monthly_ret > 0]
    negative = monthly_ret[monthly_ret <= 0]
    
    # Max consecutive loss streak
    is_loss = (monthly_ret <= 0).astype(int)
    streaks = is_loss.groupby((is_loss != is_loss.shift()).cumsum()).sum()
    max_consec = streaks.max() if len(streaks) > 0 else 0
    
    return {
        'monthly_returns': monthly_ret,
        'hit_rate': (len(positive) / len(monthly_ret)) * 100,
        'best_month': monthly_ret.max(),
        'worst_month': monthly_ret.min(),
        'avg_positive_month': positive.mean() if len(positive) > 0 else 0,
        'avg_negative_month': negative.mean() if len(negative) > 0 else 0,
        'max_consecutive_loss': int(max_consec),
        'win_count': len(positive),
        'loss_count': len(negative),
    }
```

### 19. Market Correlation
```python
def market_correlation(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Formula: ρ = Pearson correlation coefficient between daily portfolio and benchmark returns
    
    Range: -1 to +1
    ρ close to 1.0 = portfolio moves closely with market
    ρ below 0.7 = meaningful independent return sources
    ρ close to 0 = almost no relationship to market (rare for equity portfolios)
    """
    return daily_port_ret.corr(daily_bench_ret)
```

### 20. Cash Position Metrics
```python
def cash_metrics(nav_df: pd.DataFrame) -> dict:
    """
    Computed directly from the Liquidity % column in NAV file.
    
    avg_cash_held:  Average cash + liquid fund allocation as % of NAV across all days.
                    Higher = more defensive average positioning.
    max_cash_held:  Peak defensive positioning — the highest % of portfolio held in 
                    cash on any single day. Shows willingness to go heavily defensive.
    
    Note: Current cash % is from the latest NAV row.
    """
    cash = nav_df['cash_pct']
    return {
        'avg_cash_held': cash.mean(),
        'max_cash_held': cash.max(),
        'current_cash': cash.iloc[-1],
    }
```

### 21. Holdings P&L Computation
```python
def compute_holdings(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate all BUY/SELL/BONUS/CORPUS_IN transactions per symbol
    to compute current holdings with average cost.
    
    Weighted Average Cost Method:
      When buying:  new_avg = (old_qty × old_avg + buy_qty × buy_price) / (old_qty + buy_qty)
      When selling: avg_cost unchanged, just reduce quantity
      For BONUS:    avg_cost recalculated: new_avg = (old_qty × old_avg) / (old_qty + bonus_qty)
                    (bonus shares have zero cost, diluting the average)
    
    Unrealized P&L:
      pnl_absolute = (current_price - avg_cost) × quantity
      pnl_percent  = ((current_price / avg_cost) - 1) × 100
    
    Weight:
      weight_pct = current_value / total_portfolio_value × 100
    """
```

### 22. Growth Visualization Data
```python
def compute_growth(invested_amount: float, current_value: float, 
                   bench_start: float, bench_end: float,
                   inception_date, latest_date, fd_rate: float = 7.0) -> dict:
    """
    "What your ₹X became" comparison.
    
    Portfolio:  actual current_value
    Nifty:      invested_amount × (bench_end / bench_start)
    FD:         invested_amount × (1 + fd_rate/100) ^ years
    
    Note: For clients with multiple infusions, use the total corpus as invested_amount
    and compute Nifty/FD equivalents using the same cash flow timing (simplified).
    """
    years = (latest_date - inception_date).days / 365.25
    fd_value = invested_amount * ((1 + fd_rate / 100) ** years)
    nifty_value = invested_amount * (bench_end / bench_start)
    
    return {
        'invested': invested_amount,
        'portfolio': current_value,
        'nifty': nifty_value,
        'fd': fd_value,
    }
```

### 23. Win/Loss Analysis (Trade-Level)
```python
def win_loss_analysis(transactions_df: pd.DataFrame, current_prices: dict) -> dict:
    """
    For scripts with completed BUY → SELL cycles:
    
    Win:  trades where sell_amount > buy_amount (profit)
    Loss: trades where sell_amount < buy_amount (loss)
    
    Win Rate:     winning_trades / total_trades × 100
    Profit Factor: sum(profits) / sum(losses)
    Avg Win:      mean profit of winning trades (₹)
    Avg Loss:     mean loss of losing trades (₹)
    
    Only computed for scripts that have BOTH buy and sell transactions.
    CORPUS_IN → SELL is treated as a valid trade cycle.
    """
```

### 24. Performance Summary Table (Multi-Period)
```python
def performance_table(nav_df: pd.DataFrame, risk_free_rate: float = 6.50) -> list[dict]:
    """
    Generate the rows for the Performance Summary table matching Market Pulse format.
    
    For each period (1M, 3M, 6M, 1Y, 2Y, 3Y, 4Y, 5Y, Since Inception):
      - Slice nav_df to trailing N days
      - Compute: absolute_return, cagr, volatility, max_drawdown, sharpe, sortino
      - Compute same metrics for benchmark
    
    Returns list of dicts, one per period:
    {
        'period': '1 Year',
        'port_abs_return': +27.12,
        'bench_abs_return': +3.37,
        'port_cagr': +27.14,
        'bench_cagr': +3.37,
        'port_volatility': +8.12,
        'bench_volatility': +12.54,
        'port_max_dd': -5.05,
        'bench_max_dd': -12.07,
        'port_sharpe': 1.22,
        'bench_sharpe': -0.23,
        'port_sortino': 1.42,
        'bench_sortino': -0.23,
    }
    """
    periods = [
        ('1 Month', 30), ('3 Months', 91), ('6 Months', 182),
        ('1 Year', 365), ('2 Years', 730), ('3 Years', 1095),
        ('4 Years', 1461), ('5 Years', 1826),
        ('Since Inception', None),  # None = use full series
    ]
    
    results = []
    for label, days in periods:
        if days is None:
            slice_df = nav_df
        else:
            cutoff = nav_df['nav_date'].iloc[-1] - pd.Timedelta(days=days)
            slice_df = nav_df[nav_df['nav_date'] >= cutoff]
        
        if len(slice_df) < 2:
            continue
        
        # Compute all metrics for this slice...
        # (calls the individual functions above)
        results.append({...})
    
    return results
```

### Risk Engine — Orchestration
```python
def run_risk_engine(client_id: int, portfolio_id: int, db_session):
    """
    Master function called after every NAV upload.
    
    1. Fetch nav_df from cpp_nav_series for this client+portfolio
    2. Fetch benchmark data (Nifty 50) and align dates
    3. Compute ALL metrics using functions above
    4. Compute drawdown series
    5. Compute performance table for all periods
    6. Compute monthly return profile
    7. Upsert into cpp_risk_metrics (latest computed_date)
    8. Upsert into cpp_drawdown_series (full series)
    
    All computations use Decimal where stored, float only for numpy operations.
    Convert back to Decimal before database write.
    """
```

---

## Section 13: Calculation Methodology Page

**This is a MANDATORY section on every client dashboard.**
Accessible via: sidebar nav item "📐 Methodology" AND a "View Calculation Methodology"
link at the bottom of the dashboard page (matching the Market Pulse pattern).

This page displays an expandable accordion of every metric, showing:
1. The metric name and current value for this client
2. A plain-English explanation (what it means, why it matters)
3. The exact mathematical formula
4. The actual inputs used for this client
5. A worked example with the client's real numbers

### Structure
```
📐 Calculation Methodology
"How every number on your dashboard is computed"

▸ Portfolio Returns
  ├── Absolute Return
  ├── CAGR (Compound Annual Growth Rate)
  └── XIRR (Extended Internal Rate of Return)

▸ Risk Metrics
  ├── Volatility (Annualized Standard Deviation)
  ├── Maximum Drawdown
  ├── Sharpe Ratio
  └── Sortino Ratio

▸ Benchmark Comparison
  ├── Alpha (Jensen's Alpha)
  ├── Beta
  ├── Information Ratio
  ├── Tracking Error
  ├── Up Capture Ratio
  └── Down Capture Ratio

▸ Drawdown & Stress
  ├── Ulcer Index
  ├── Maximum Consecutive Loss
  ├── Average Cash Held
  └── Maximum Cash Held

▸ Monthly Return Profile
  ├── Monthly Hit Rate
  ├── Best / Worst Month
  ├── Market Correlation
  └── Win / Loss Analysis

▸ Portfolio Valuation
  ├── NAV Calculation
  ├── TWR Index (Base 100)
  ├── Holdings P&L (Weighted Average Cost)
  └── Growth Comparison Methodology

▸ Data Sources & Assumptions
  ├── NAV Data Source (PMS backoffice daily valuation)
  ├── Benchmark (NIFTY 50 Total Return Index)
  ├── Risk-Free Rate (6.50% — India 10Y Govt Bond Yield)
  ├── Trading Days (252 per year)
  ├── Cash Instruments (LIQUIDBEES, LIQUIDETF treated as cash)
  └── As-of Date and Data Freshness
```

### Accordion Item Template
```jsx
<AccordionItem>
  <AccordionTrigger>
    <div className="flex justify-between w-full">
      <span className="font-semibold text-slate-800">Sharpe Ratio</span>
      <span className="font-mono text-teal-600">0.80</span>
    </div>
  </AccordionTrigger>
  <AccordionContent>
    <div className="space-y-4 text-sm text-slate-600">
      {/* What it means */}
      <p>
        The Sharpe Ratio measures how much excess return you receive for each 
        unit of risk (volatility) taken. It tells you whether the returns are 
        coming from smart investment decisions or from taking excessive risk.
      </p>
      
      {/* Formula */}
      <div className="bg-slate-50 rounded-lg p-4 font-mono text-sm">
        Sharpe Ratio = (Portfolio CAGR − Risk-Free Rate) / Portfolio Volatility
      </div>
      
      {/* Worked example with client's actual numbers */}
      <div className="bg-slate-50 rounded-lg p-4">
        <p className="font-medium text-slate-700 mb-2">Your numbers:</p>
        <p>Portfolio CAGR = +35.64%</p>
        <p>Risk-Free Rate = 6.50% (India 10Y Govt Bond)</p>
        <p>Portfolio Volatility = 15.00%</p>
        <p className="mt-2 font-semibold text-slate-800">
          = (35.64 − 6.50) / 15.00 = <span className="text-teal-600">0.80</span>
        </p>
      </div>
      
      {/* Interpretation */}
      <div className="text-xs text-slate-500">
        <p>Interpretation: &gt; 1.0 = Good | &gt; 2.0 = Excellent | &lt; 0 = Below risk-free rate</p>
        <p>Benchmark (NIFTY 50) Sharpe: 0.53</p>
      </div>
    </div>
  </AccordionContent>
</AccordionItem>
```

### API Endpoint for Methodology Data
```
GET /api/portfolio/methodology
→ Returns all metrics with their current values, formulas, and computed inputs
  so the frontend can render the worked examples dynamically.

Response shape:
{
  "as_of_date": "2026-03-13",
  "risk_free_rate": 6.50,
  "trading_days_per_year": 252,
  "benchmark_name": "NIFTY 50",
  "metrics": {
    "sharpe_ratio": {
      "value": 0.80,
      "inputs": {
        "portfolio_cagr": 35.64,
        "risk_free_rate": 6.50,
        "portfolio_volatility": 15.00
      },
      "benchmark_value": 0.53
    },
    // ... all other metrics
  }
}
```

---

## JIP Design System (MANDATORY)

Every component MUST follow the Jhaveri Intelligence Platform design system. This is a LIGHT THEME professional financial platform.

### Colors
```
Primary Teal:       #0d9488 (headers, active sidebar, primary buttons)
Brand Navy:         #1e293b (page titles, headings)
Page Background:    #f8fafc (slate-50)
Card Background:    #ffffff (white, border border-slate-200, rounded-xl)
Profit/Positive:    #059669 (emerald-600)
Loss/Negative:      #dc2626 (red-600)
Warning:            #d97706 (amber-600)
```

### Typography
- Font: Inter (Google Fonts) — `font-family: 'Inter', system-ui, sans-serif`
- Page titles: `text-xl font-semibold text-slate-800` with emoji prefix
- Card labels: `text-sm text-slate-500`
- Card values: `text-2xl font-bold font-mono text-slate-800`
- Table headers: `text-xs font-semibold text-slate-400 uppercase tracking-wider`
- ALL financial numbers: `font-mono tabular-nums`

### Chart Colors (Recharts)
```
Primary series:   #0d9488 (teal — portfolio)
Benchmark:        #94a3b8 (slate-400 — dashed line)
Cash overlay:     #d97706 (amber — semi-transparent bars)
Positive fill:    #059669 (emerald)
Negative fill:    #dc2626 (red — drawdown area)
Grid lines:       #f1f5f9 (slate-100)
```

### Indian Number Formatting (ABSOLUTE RULE)
```
₹1,23,45,678.00      (Indian grouping — NOT ₹12,345,678)
₹48.50L               (Lakhs — values between ₹1L and ₹1Cr)
₹67.45 Cr             (Crores — values above ₹1Cr)
+35.64%               (Always show + or − prefix on percentages)
```

### Card Pattern
```jsx
<div className="bg-white rounded-xl border border-slate-200 p-5">
  <p className="text-sm text-slate-500">Label</p>
  <p className="text-2xl font-bold font-mono text-slate-800">₹48.50L</p>
  <p className="text-xs text-slate-400">subtitle</p>
</div>
```

---

## Deployment

### Docker (Single Container)
```dockerfile
# Stage 1: Build Next.js frontend
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with both
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/.next ./frontend/.next
COPY --from=frontend /app/frontend/public ./frontend/public
COPY --from=frontend /app/frontend/node_modules ./frontend/node_modules
COPY --from=frontend /app/frontend/package.json ./frontend/
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*
COPY start.sh ./
RUN chmod +x start.sh
EXPOSE 8007
CMD ["./start.sh"]
```

### start.sh
```bash
#!/bin/bash
cd /app/frontend && npx next start -p 3000 &
cd /app/backend && uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 &
wait
```

### Next.js Proxy Config (next.config.js)
```javascript
module.exports = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' }];
  },
};
```

### Nginx
```nginx
server {
    server_name clients.jslwealth.in;
    location / {
        proxy_pass http://127.0.0.1:8007;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### GitHub Actions
```yaml
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.EC2_HOST }}
          username: ubuntu
          key: ${{ secrets.EC2_SSH_KEY }}
          script: |
            cd ~/apps/client-portal
            git pull origin main
            docker build -t client-portal .
            docker stop client-portal || true
            docker rm client-portal || true
            docker run -d --name client-portal --env-file .env -p 8007:3000 --restart unless-stopped client-portal
            sleep 5
            curl -sf http://localhost:8007/api/health
```

Note: `-p 8007:3000` maps EC2 port 8007 to Next.js port 3000 inside container. Next.js proxies /api/* to FastAPI :8000 internally.

---

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://fie_admin:FieAdmin2026!@fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com:5432/client_portal
DATABASE_URL_SYNC=postgresql://fie_admin:FieAdmin2026!@fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com:5432/client_portal

# Auth
JWT_SECRET=                          # openssl rand -hex 32
JWT_EXPIRY_HOURS=48

# App
APP_NAME=JSL Client Portfolio Portal
APP_PORT=8007
APP_ENV=production
CORS_ORIGINS=https://clients.jslwealth.in

# Risk computation
RISK_FREE_RATE=6.50                  # India 10Y yield proxy
```

---

## Build Sequence (for Claude Code sessions)

### Session 1: Foundation
```
1. Initialize project structure (backend/ + frontend/ + scripts/)
2. backend/database.py — SQLAlchemy async engine
3. backend/models/ — All 8 table models
4. scripts/init_db.sql — CREATE TABLE statements
5. backend/main.py — FastAPI app with health check
6. backend/routers/auth.py — Login/logout/me endpoints
7. backend/services/auth_service.py — bcrypt + JWT
8. frontend/ — Next.js project with next.config.js proxy
9. frontend/src/app/login/page.js — Login page
10. Test: login works end-to-end with test user
```

### Session 2: Data Pipeline
```
1. backend/services/nav_parser.py — Stateful .xlsx parser (see FILE_FORMAT_SPEC.md)
2. backend/services/txn_parser.py — Stateful .xlsx parser with buy/sell split
3. backend/services/ingestion_service.py — Orchestrate parse → validate → upsert
4. backend/services/benchmark_service.py — Fetch Nifty 50 via yfinance, date-align
5. backend/routers/admin.py — Upload endpoints with progress tracking
6. backend/services/risk_engine.py — All metric computations
7. backend/services/holdings_service.py — Aggregate holdings from transactions
8. backend/services/xirr_service.py — Detect corpus changes → compute XIRR
9. scripts/seed_test_clients.py — Parse the BJ53 sample files as test data
10. Test: upload BJ53 files → data appears in DB → risk metrics computed → verify against Market Pulse values
```

### Session 3: Dashboard (Core)
```
1. frontend/src/app/dashboard/layout.js — Sidebar + layout
2. SummaryCards component
3. NavChart component (Recharts ComposedChart — line + area + bar)
4. PerformanceTable component
5. GrowthViz component
6. AllocationCharts component (donut + shift area)
7. Test: dashboard renders with test client data
```

### Session 4: Dashboard (Advanced) + Admin + Methodology
```
1. HoldingsTable component
2. UnderwaterChart component
3. RiskScorecard component
4. MonthlyReturns component (including heatmap)
5. TransactionHistory component
6. Methodology page — accordion with all metrics, formulae, worked examples
7. GET /api/portfolio/methodology endpoint — returns all metric values + inputs
8. Admin upload page with column mapper preview
9. Admin client management page
```

### Session 5: Verify, Polish + Deploy
```
1. VERIFICATION: Load BJ53 data, compare every metric against marketpulse.jslwealth.in/portfolios?id=4
   - Match: CAGR, absolute returns, max DD, Sharpe, Sortino for all periods
   - Match: Up Capture, Down Capture, Beta, Information Ratio
   - Match: Ulcer Index, Monthly Hit Rate, Max Consecutive Loss
   - Match: Avg Cash Held, Max Cash Held, Market Correlation
   - Match: Win/Loss analysis numbers
   - If any metric differs by >0.5%, investigate and fix before proceeding
2. Loading states (skeleton loaders)
3. Error states and empty states
4. Responsive design pass
5. Dockerfile + start.sh
6. GitHub Actions deploy.yml
7. Nginx config + SSL
8. Test with real client data
```

---

## Non-Negotiables

### From Global Engineering OS (`~/.claude/standards/CODING_STANDARDS.md`)
- No file exceeds 400 lines — refactor and modularize
- No hardcoded secrets — environment variables only
- Every input validated server-side (not just frontend)
- Every function has error handling — no bare try/except
- TypeScript strict mode for frontend (or JSDoc type annotations)
- SECURITY agent reviews every session — no deploy without ✅ PASS
- QA agent signs off on test coverage before task is marked complete
- All decisions logged in DECISIONS_LOG.md
- All corrections logged in LEARNINGS.md

### CPP Project-Specific Rules
1. **NEVER use float for financial data** — always Decimal/NUMERIC
2. **EVERY portfolio query MUST include `WHERE client_id = X`** — extracted from JWT, never from request params
3. **Indian number formatting everywhere** — ₹1,23,456 not ₹123,456
4. **font-mono for all numbers** — prices, returns, amounts
5. **Green for profit, Red for loss** — emerald-600 and red-600, never reversed
6. **Single Dockerfile pattern** — never deploy frontend separately
7. **No Supabase** — this project uses RDS directly via SQLAlchemy
8. **bcrypt cost factor 12** — never lower
9. **JWT in httpOnly cookie** — never in localStorage, never in URL params
10. **Admin routes check is_admin** — not just any valid JWT
11. **Every metric formula must match the Risk Computation Engine section exactly** — these are shown to clients on the Methodology page
12. **Session must end with SECURITY verdict** — ✅ PASS / ⚠️ NEEDS ATTENTION / ❌ BLOCKED

---

## Health Check

```python
@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "client-portfolio-portal",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "timestamp": datetime.utcnow().isoformat()
    }
```
