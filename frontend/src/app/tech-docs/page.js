'use client';

import { useState } from 'react';
import {
  Server, Database, Shield, Globe, Lock, Code2, GitBranch,
  Monitor, FileText, AlertTriangle, CheckCircle2, XCircle,
  ChevronDown, ChevronRight, Terminal, Layers, Network,
  HardDrive, KeyRound, Eye, FileWarning, Activity
} from 'lucide-react';

const ACCENT = 'text-teal-600';
const CARD = 'bg-white rounded-xl border border-slate-200 p-5 sm:p-6';
const CODE_BLOCK = 'bg-slate-900 text-slate-100 rounded-lg p-4 text-xs sm:text-sm font-mono overflow-x-auto whitespace-pre';
const BADGE_OK = 'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200';
const BADGE_WARN = 'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200';
const BADGE_FAIL = 'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200';

function Section({ id, icon: Icon, title, children }) {
  return (
    <section id={id} className="scroll-mt-20">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 bg-teal-50 rounded-lg">
          <Icon className="h-5 w-5 text-teal-600" />
        </div>
        <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Accordion({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={CARD}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="font-medium text-slate-700">{title}</span>
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
      </button>
      {open && <div className="mt-4 text-sm text-slate-600 space-y-3">{children}</div>}
    </div>
  );
}

function StatusBadge({ status }) {
  if (status === 'ok') return <span className={BADGE_OK}><CheckCircle2 className="h-3 w-3" />Implemented</span>;
  if (status === 'warn') return <span className={BADGE_WARN}><AlertTriangle className="h-3 w-3" />Needs Attention</span>;
  return <span className={BADGE_FAIL}><XCircle className="h-3 w-3" />Not Done</span>;
}

function Table({ headers, rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            {headers.map((h, i) => (
              <th key={i} className="text-left py-2 px-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="py-2 px-3 text-slate-600">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const NAV_ITEMS = [
  { id: 'overview', label: 'System Overview' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'infrastructure', label: 'Infrastructure' },
  { id: 'backend', label: 'Backend (FastAPI)' },
  { id: 'frontend', label: 'Frontend (Next.js)' },
  { id: 'database', label: 'Database Schema' },
  { id: 'auth', label: 'Authentication' },
  { id: 'security', label: 'Security Measures' },
  { id: 'api', label: 'API Reference' },
  { id: 'deployment', label: 'Deployment' },
  { id: 'monitoring', label: 'Monitoring' },
  { id: 'data-pipeline', label: 'Data Pipeline' },
  { id: 'compliance', label: 'SEBI Compliance' },
  { id: 'attention', label: 'Areas for Attention' },
];

export default function TechDocsPage() {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-800">JSL Client Portfolio Portal</h1>
            <p className="text-sm text-slate-500">Technical Documentation &mdash; System Handover</p>
          </div>
          <div className="text-right text-xs text-slate-400">
            <p>Version 1.0.0</p>
            <p>Last updated: April 2026</p>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex gap-8">
        {/* Sidebar nav */}
        <nav className="hidden lg:block w-56 shrink-0">
          <div className="sticky top-24 space-y-1">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Contents</p>
            {NAV_ITEMS.map(item => (
              <a
                key={item.id}
                href={`#${item.id}`}
                className="block text-sm text-slate-500 hover:text-teal-600 py-1 transition-colors"
              >
                {item.label}
              </a>
            ))}
          </div>
        </nav>

        {/* Main content */}
        <main className="flex-1 min-w-0 space-y-10">

          {/* ─── SYSTEM OVERVIEW ─── */}
          <Section id="overview" icon={Globe} title="System Overview">
            <div className={CARD}>
              <p className="text-sm text-slate-600 leading-relaxed">
                The <strong>JSL Client Portfolio Portal (CPP)</strong> is a multi-tenant portfolio dashboard
                serving ~200 PMS/advisory clients of Jhaveri Securities Limited. Each client logs in with
                credentials and views their complete portfolio: NAV performance, risk metrics, holdings with P&L,
                drawdowns, allocation breakdowns, and transaction history.
              </p>
              <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  ['Domain', 'clients.jslwealth.in'],
                  ['Module', 'CPP (Client Portfolio Portal)'],
                  ['Clients', '~200 PMS accounts'],
                  ['Status', 'Production'],
                ].map(([label, value]) => (
                  <div key={label} className="bg-slate-50 rounded-lg p-3">
                    <p className="text-xs text-slate-400">{label}</p>
                    <p className="text-sm font-medium text-slate-700 font-mono">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          {/* ─── ARCHITECTURE ─── */}
          <Section id="architecture" icon={Layers} title="Architecture">
            <div className={CARD}>
              <p className="text-sm text-slate-500 mb-4">
                Single Docker container running both frontend and backend. Nginx terminates SSL and routes traffic.
              </p>
              <pre className={CODE_BLOCK}>{`┌─────────────────────────────────────────────────────┐
│  clients.jslwealth.in (Nginx :443 — SSL termination)│
│                                                     │
│  /api/*  ──────►  127.0.0.1:8008 (FastAPI)          │
│  /*      ──────►  127.0.0.1:8007 (Next.js)          │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│  Docker Container: client-portal                     │
│                                                     │
│  ┌──────────────┐    ┌──────────────┐               │
│  │  Next.js      │    │  FastAPI     │               │
│  │  :3000        │    │  :8000      │               │
│  │  (Frontend)   │    │  (API)      │               │
│  └──────────────┘    └──────┬───────┘               │
│                             │                        │
└─────────────────────────────┼────────────────────────┘
                              │
                ┌─────────────▼──────────────┐
                │  AWS RDS (PostgreSQL 15)    │
                │  Database: client_portal    │
                │  Table prefix: cpp_         │
                └────────────────────────────┘`}</pre>
            </div>

            <Accordion title="Port Mapping" defaultOpen>
              <Table
                headers={['Service', 'Container Port', 'EC2 Port', 'External']}
                rows={[
                  ['Next.js (Frontend)', '3000', '8007', 'clients.jslwealth.in/* (via Nginx)'],
                  ['FastAPI (Backend)', '8000', '8008', 'clients.jslwealth.in/api/* (via Nginx)'],
                  ['Nginx (SSL)', '—', '443/80', 'Public internet'],
                ]}
              />
            </Accordion>

            <Accordion title="Key Design Decisions">
              <ul className="list-disc list-inside space-y-2">
                <li><strong>Single Dockerfile pattern</strong> — Frontend and backend bundled in one container. Eliminates CORS issues, simplifies deployment. Same pattern as Market Pulse (marketpulse.jslwealth.in).</li>
                <li><strong>Nginx routes /api/ directly to FastAPI:8008</strong> — bypasses Next.js proxy for API calls. This avoids Next.js body size limits on file uploads (up to 50MB).</li>
                <li><strong>No Vercel / no separate frontend deployment</strong> — everything runs on the same EC2 instance.</li>
                <li><strong>Client-Side Rendering (CSR)</strong> — dashboard pages use React hooks to fetch data. No SSR needed since all pages are auth-protected.</li>
              </ul>
            </Accordion>
          </Section>

          {/* ─── INFRASTRUCTURE ─── */}
          <Section id="infrastructure" icon={HardDrive} title="Infrastructure">
            <Accordion title="EC2 Instance" defaultOpen>
              <Table
                headers={['Property', 'Value']}
                rows={[
                  ['Type', 't3.large (2 vCPU, 8GB RAM)'],
                  ['OS', 'Ubuntu 22.04 LTS'],
                  ['Region', 'ap-south-1 (Mumbai)'],
                  ['Apps Path', '~/apps/client-portal'],
                  ['Docker', 'Managed via docker run (not docker-compose in prod)'],
                  ['Nginx', 'Reverse proxy with Let\'s Encrypt SSL'],
                  ['Access', 'SSH via GitHub Actions secrets (EC2_HOST, EC2_SSH_KEY)'],
                ]}
              />
            </Accordion>

            <Accordion title="RDS Database">
              <Table
                headers={['Property', 'Value']}
                rows={[
                  ['Engine', 'PostgreSQL 15'],
                  ['Instance', 'Shared RDS (hosts multiple databases)'],
                  ['Database', 'client_portal'],
                  ['Table Prefix', 'cpp_ (to avoid collisions)'],
                  ['Connection', 'Async via asyncpg (SQLAlchemy 2.0)'],
                  ['SSL', 'Enabled (CERT_REQUIRED in production)'],
                  ['Pooling', 'pool_size=10, max_overflow=20, pool_pre_ping=True'],
                ]}
              />
            </Accordion>

            <Accordion title="Nginx Configuration">
              <pre className={CODE_BLOCK}>{`server {
    server_name clients.jslwealth.in;
    client_max_body_size 60m;

    # API calls → FastAPI (port 8008)
    location /api/ {
        proxy_pass http://127.0.0.1:8008;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }

    # Everything else → Next.js (port 8007)
    location / {
        proxy_pass http://127.0.0.1:8007;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/.../fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name clients.jslwealth.in;
    return 301 https://$host$request_uri;
}`}</pre>
            </Accordion>

            <Accordion title="Environment Variables (.env)">
              <p className="text-amber-600 text-xs font-medium mb-2">Located at ~/apps/client-portal/.env on EC2. Never committed to git.</p>
              <Table
                headers={['Variable', 'Purpose', 'Example']}
                rows={[
                  ['DATABASE_URL', 'Async PostgreSQL connection string', 'postgresql+asyncpg://user:pass@host:5432/client_portal'],
                  ['DATABASE_URL_SYNC', 'Sync connection for scripts', 'Auto-derived if blank'],
                  ['JWT_SECRET', 'HS256 signing key (min 32 chars)', 'openssl rand -hex 32'],
                  ['JWT_EXPIRY_HOURS', 'Token lifetime', '24'],
                  ['ENCRYPTION_KEY', 'Fernet key for PII encryption', 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'],
                  ['APP_ENV', 'Environment flag', 'production'],
                  ['CORS_ORIGINS', 'Allowed origins', 'https://clients.jslwealth.in'],
                  ['RISK_FREE_RATE', 'Risk-free rate for calculations', '6.50'],
                  ['LOG_LEVEL', 'Logging verbosity', 'INFO'],
                ]}
              />
            </Accordion>
          </Section>

          {/* ─── BACKEND ─── */}
          <Section id="backend" icon={Server} title="Backend (FastAPI)">
            <Accordion title="Tech Stack" defaultOpen>
              <Table
                headers={['Technology', 'Version', 'Purpose']}
                rows={[
                  ['FastAPI', '0.115.6', 'Async web framework'],
                  ['SQLAlchemy', '2.0.36', 'ORM with async support'],
                  ['asyncpg', '0.30.0', 'PostgreSQL async driver'],
                  ['Pydantic', '2.10.4', 'Request/response validation'],
                  ['PyJWT', '2.9.0', 'JWT token handling'],
                  ['bcrypt', '4.2.1', 'Password hashing (cost factor 12)'],
                  ['cryptography', '44.0.0', 'Fernet encryption for PII'],
                  ['pandas', '2.2.3', 'Risk metric computation'],
                  ['scipy', '1.15.0', 'XIRR calculation (brentq solver)'],
                  ['yfinance', '>=1.2.0', 'Benchmark data (NIFTY 50)'],
                  ['slowapi', '0.1.9', 'Rate limiting'],
                  ['openpyxl', '3.1.5', 'Excel file parsing (read_only mode)'],
                  ['apscheduler', '3.10.4', 'Scheduled price refresh'],
                ]}
              />
            </Accordion>

            <Accordion title="Directory Structure">
              <pre className={CODE_BLOCK}>{`backend/
├── main.py                    # FastAPI app entry + middleware
├── config.py                  # Pydantic settings (validates .env)
├── database.py                # SQLAlchemy engine + session
├── models/
│   ├── client.py              # cpp_clients (auth, PII, RBAC, soft-delete)
│   ├── portfolio.py           # cpp_portfolios
│   ├── nav_series.py          # cpp_nav_series (daily NAV time series)
│   ├── transaction.py         # cpp_transactions (buy/sell, soft-delete)
│   ├── holding.py             # cpp_holdings (computed from transactions)
│   ├── risk_metric.py         # cpp_risk_metrics (computed from NAV)
│   ├── drawdown.py            # cpp_drawdown_series
│   ├── cash_flow.py           # cpp_cash_flows (XIRR inputs)
│   ├── upload_log.py          # cpp_upload_log (admin upload audit)
│   ├── audit_log.py           # cpp_audit_log (SEBI compliance)
│   └── consent.py             # cpp_client_consents (SEBI compliance)
├── routers/
│   ├── auth.py                # Login, logout, change-password, consent
│   ├── portfolio.py           # Summary, performance table, growth, allocation
│   ├── portfolio_nav.py       # NAV series, benchmark data
│   ├── portfolio_detail.py    # Holdings, transactions, drawdown
│   ├── portfolio_methodology.py # Calculation methodology data
│   ├── admin.py               # Risk recompute, price update, impersonate
│   ├── admin_upload.py        # File upload (background processing)
│   ├── admin_clients.py       # Client CRUD, bulk create
│   ├── admin_aggregate.py     # Firm-wide analytics
│   └── admin_reconciliation.py # Backoffice reconciliation
├── services/
│   ├── risk_engine.py         # All financial metric calculations
│   ├── risk_db.py             # Risk metric DB operations
│   ├── ingestion_service.py   # NAV + transaction file parsing orchestration
│   ├── ingestion_helpers.py   # Client/portfolio upsert, holdings recompute
│   ├── nav_parser.py          # Stateful .xlsx NAV file parser
│   ├── txn_parser.py          # Stateful .xlsx transaction file parser
│   ├── holdings_service.py    # FIFO cost basis calculation
│   ├── live_prices.py         # NSE current price fetcher
│   ├── isin_resolver.py       # ISIN → NSE ticker resolution
│   ├── benchmark_service.py   # NIFTY 50 data via yfinance
│   ├── aggregate_service.py   # Firm-wide composite metrics
│   ├── reconciliation_service.py # Holdings reconciliation engine
│   ├── audit_service.py       # Audit logging helper
│   └── scheduler.py           # APScheduler for periodic tasks
├── middleware/
│   ├── auth_middleware.py     # JWT extraction, password hashing
│   └── security.py            # Request ID, CSRF, security headers
├── schemas/
│   ├── auth.py                # Login/register/consent schemas
│   ├── portfolio.py           # Portfolio response schemas
│   └── admin.py               # Admin operation schemas
└── utils/
    ├── encryption.py          # Fernet PII encryption/decryption
    └── indian_format.py       # ₹ formatting, lakh/crore conversion`}</pre>
            </Accordion>

            <Accordion title="Middleware Stack (execution order)">
              <ol className="list-decimal list-inside space-y-2">
                <li><strong>CORSMiddleware</strong> — handles preflight, sets Access-Control-* headers</li>
                <li><strong>RequestIdMiddleware</strong> — attaches UUID to every request (X-Request-ID header)</li>
                <li><strong>CSRFMiddleware</strong> — validates double-submit cookie token on POST/PUT/DELETE</li>
                <li><strong>SecurityHeadersMiddleware</strong> — adds HSTS, CSP, X-Frame-Options, X-Content-Type-Options</li>
                <li><strong>Rate Limiting (slowapi)</strong> — per-endpoint limits (5/min on login, uploads)</li>
              </ol>
            </Accordion>
          </Section>

          {/* ─── FRONTEND ─── */}
          <Section id="frontend" icon={Monitor} title="Frontend (Next.js)">
            <Accordion title="Tech Stack" defaultOpen>
              <Table
                headers={['Technology', 'Version', 'Purpose']}
                rows={[
                  ['Next.js', '14.2.x', 'React framework (App Router)'],
                  ['React', '18.3.x', 'UI library'],
                  ['Tailwind CSS', '3.x', 'Utility-first styling'],
                  ['Recharts', '2.15.x', 'Charts (line, area, bar, pie, composed)'],
                  ['Lucide React', '—', 'Icon library'],
                  ['Inter', '—', 'Primary font (Google Fonts)'],
                ]}
              />
            </Accordion>

            <Accordion title="Route Structure">
              <Table
                headers={['Route', 'Auth', 'Purpose']}
                rows={[
                  ['/', 'None', 'Redirects to /login or /dashboard'],
                  ['/login', 'None', 'Login page with SEBI notice'],
                  ['/dashboard', 'Client JWT', 'Main dashboard (12 scrollable sections)'],
                  ['/dashboard/methodology', 'Client JWT', 'Calculation methodology with worked examples'],
                  ['/admin', 'Admin JWT', 'Admin dashboard (upload, client mgmt)'],
                  ['/admin/upload', 'Admin JWT', 'File upload with preview'],
                  ['/admin/reconciliation', 'Admin JWT', 'Holdings reconciliation'],
                  ['/tech-docs', 'None', 'This page'],
                ]}
              />
            </Accordion>

            <Accordion title="Dashboard Sections (scroll order)">
              <ol className="list-decimal list-inside space-y-1">
                <li>ClientHeader — welcome, portfolio name, as-of date</li>
                <li>SummaryCards — 6 stat cards (invested, current, profit, CAGR, YTD, max DD)</li>
                <li>NavChart — base-100 performance chart with cash overlay + time selectors</li>
                <li>PerformanceTable — multi-period returns (1M → inception)</li>
                <li>GrowthViz — &quot;What your money became&quot; bar comparison</li>
                <li>AllocationBar — asset class allocation labels</li>
                <li>HoldingsTable — sortable holdings with P&L + ISIN</li>
                <li>UnderwaterChart — drawdown chart with benchmark overlay</li>
                <li>RiskScorecard — capture ratios, beta, Sharpe, Sortino, etc.</li>
                <li>MonthlyReturns — hit rate, heatmap grid, best/worst months</li>
                <li>TransactionHistory — paginated, filterable transaction log</li>
                <li>MethodologyLink — link to calculation methodology page</li>
                <li>RegulatoryDisclaimer — SEBI compliance disclosures</li>
              </ol>
            </Accordion>

            <Accordion title="Design System (JIP)">
              <Table
                headers={['Element', 'Value']}
                rows={[
                  ['Primary color', '#0d9488 (teal-600)'],
                  ['Background', '#f8fafc (slate-50)'],
                  ['Cards', 'White, rounded-xl, border-slate-200'],
                  ['Profit', '#059669 (emerald-600)'],
                  ['Loss', '#dc2626 (red-600)'],
                  ['Font', 'Inter (Google Fonts)'],
                  ['Numbers', 'font-mono tabular-nums'],
                  ['Currency', '₹ with Indian grouping (1,23,456)'],
                  ['Theme', 'Light only (no dark mode)'],
                ]}
              />
            </Accordion>
          </Section>

          {/* ─── DATABASE ─── */}
          <Section id="database" icon={Database} title="Database Schema">
            <Accordion title="Tables (11 total)" defaultOpen>
              <Table
                headers={['Table', 'Rows (est.)', 'Purpose', 'Key Indexes']}
                rows={[
                  ['cpp_clients', '~200', 'Client/admin accounts', 'username (unique), client_code (unique)'],
                  ['cpp_portfolios', '~200', 'One per client (PMS Equity)', 'client_id, (client_id, portfolio_name) unique'],
                  ['cpp_nav_series', '~200K', 'Daily NAV time series', '(client_id, portfolio_id, nav_date) unique + index'],
                  ['cpp_transactions', '~100K', 'Buy/sell/bonus trades', '(client_id, portfolio_id, txn_date) index, ISIN index'],
                  ['cpp_holdings', '~5K', 'Current positions (computed)', '(client_id, portfolio_id, symbol) unique, ISIN index'],
                  ['cpp_risk_metrics', '~200', 'Latest risk metrics per client', 'client_id index'],
                  ['cpp_drawdown_series', '~200K', 'Daily drawdown values', '(client_id, portfolio_id, dd_date) index'],
                  ['cpp_cash_flows', '~2K', 'XIRR cash flow inputs', '(client_id, portfolio_id, flow_date) index'],
                  ['cpp_upload_log', '~100', 'Admin upload audit trail', 'uploaded_by index'],
                  ['cpp_audit_log', 'Growing', 'All data access/modification log', 'user_id, target_client_id, action+created_at'],
                  ['cpp_client_consents', '~200', 'SEBI consent tracking', 'client_id index'],
                ]}
              />
            </Accordion>

            <Accordion title="Financial Data Types">
              <ul className="list-disc list-inside space-y-2">
                <li><strong>NAV values</strong>: NUMERIC(18,6) — 6 decimal places</li>
                <li><strong>Prices</strong>: NUMERIC(18,4) — 4 decimal places</li>
                <li><strong>Amounts</strong>: NUMERIC(18,2) — 2 decimal places</li>
                <li><strong>Percentages</strong>: NUMERIC(8,4) — 4 decimal places</li>
                <li><strong>Never float</strong> — all financial values use Decimal in Python, NUMERIC in PostgreSQL</li>
              </ul>
            </Accordion>

            <Accordion title="Soft Delete & Audit Fields">
              <p>Added for SEBI 7-year retention compliance:</p>
              <Table
                headers={['Table', 'Soft Delete', 'updated_at', 'Notes']}
                rows={[
                  ['cpp_clients', 'is_deleted, deleted_at, deleted_by', 'Yes', '+ role field for RBAC'],
                  ['cpp_transactions', 'is_deleted, deleted_at, deleted_by', 'Yes', 'Source records — must retain 7 years'],
                  ['cpp_portfolios', '—', 'Yes', 'Cascade-linked to client'],
                  ['cpp_holdings', '—', 'Yes', 'Computed data, regenerated from transactions'],
                ]}
              />
            </Accordion>
          </Section>

          {/* ─── AUTH ─── */}
          <Section id="auth" icon={KeyRound} title="Authentication">
            <div className={CARD}>
              <h3 className="font-medium text-slate-700 mb-3">Authentication Flow</h3>
              <pre className={CODE_BLOCK}>{`1. Client enters username + password at /login
2. POST /api/auth/login validates credentials (bcrypt verify)
3. Returns JWT token (HS256, 24hr expiry)
   Payload: { sub: client_id, admin: bool, exp: timestamp }
4. Token set in httpOnly Secure SameSite=Strict cookie
5. CSRF token set in separate readable cookie
6. Every /api/portfolio/* extracts client_id from JWT
   → adds WHERE client_id = X to ALL queries
7. Every /api/admin/* additionally checks admin == true
8. Login success + failure audit-logged to cpp_audit_log`}</pre>
            </div>

            <Accordion title="Password Security">
              <ul className="list-disc list-inside space-y-2">
                <li><strong>Hashing</strong>: bcrypt with cost factor 12</li>
                <li><strong>Minimum length</strong>: 8 characters</li>
                <li><strong>Complexity required</strong>: uppercase + lowercase + digit + special character</li>
                <li><strong>Storage</strong>: Only bcrypt hash stored, never plaintext</li>
                <li><strong>Transmission</strong>: HTTPS only (HSTS enforced in production)</li>
              </ul>
            </Accordion>

            <Accordion title="JWT Configuration">
              <Table
                headers={['Property', 'Value']}
                rows={[
                  ['Algorithm', 'HS256'],
                  ['Default Expiry', '24 hours'],
                  ['Secret', 'Minimum 32 chars (validated at startup)'],
                  ['Storage', 'httpOnly Secure SameSite=Strict cookie'],
                  ['Never in', 'localStorage, sessionStorage, URL params, headers'],
                ]}
              />
            </Accordion>

            <Accordion title="RBAC Roles">
              <Table
                headers={['Role', 'Access Level', 'Status']}
                rows={[
                  ['CLIENT', 'Own portfolio data only', <StatusBadge key="c" status="ok" />],
                  ['ADMIN_FULL', 'All admin operations', <StatusBadge key="af" status="ok" />],
                  ['ADMIN_DATA_ENTRY', 'Upload files, update prices', <StatusBadge key="ade" status="warn" />],
                  ['ADMIN_READONLY', 'View audit logs, dashboards', <StatusBadge key="aro" status="warn" />],
                ]}
              />
              <p className="text-xs text-amber-600 mt-2">
                Note: Role field exists in database. Granular permission enforcement per role is defined
                but not yet fully implemented in middleware — currently binary admin/client check.
                See &quot;Areas for Attention&quot; section.
              </p>
            </Accordion>
          </Section>

          {/* ─── SECURITY ─── */}
          <Section id="security" icon={Shield} title="Security Measures">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[
                ['Transport Security', [
                  ['HTTPS (TLS 1.2+)', 'ok'],
                  ['HSTS header (production)', 'ok'],
                  ['HTTP → HTTPS redirect', 'ok'],
                  ['SSL on DB connection', 'ok'],
                ]],
                ['Cookie Security', [
                  ['httpOnly flag', 'ok'],
                  ['Secure flag (production)', 'ok'],
                  ['SameSite=Strict', 'ok'],
                  ['No localStorage tokens', 'ok'],
                ]],
                ['Headers', [
                  ['X-Content-Type-Options: nosniff', 'ok'],
                  ['X-Frame-Options: DENY', 'ok'],
                  ['X-XSS-Protection', 'ok'],
                  ['Content-Security-Policy', 'ok'],
                  ['Referrer-Policy', 'ok'],
                  ['Permissions-Policy', 'ok'],
                ]],
                ['CSRF Protection', [
                  ['Double-submit cookie pattern', 'ok'],
                  ['Token on POST/PUT/DELETE', 'ok'],
                  ['Login endpoint exempt', 'ok'],
                ]],
                ['Input Validation', [
                  ['Pydantic schemas on all endpoints', 'ok'],
                  ['Parameterized SQL (no injection)', 'ok'],
                  ['File type whitelist (xlsx/xls/csv)', 'ok'],
                  ['50MB upload size limit', 'ok'],
                ]],
                ['Rate Limiting', [
                  ['Login: 5 requests/minute', 'ok'],
                  ['File uploads: 5/minute', 'ok'],
                  ['Portfolio endpoints', 'warn'],
                ]],
                ['Data Isolation', [
                  ['client_id from JWT on every query', 'ok'],
                  ['No client_id in request params', 'ok'],
                  ['Admin impersonation audit-logged', 'ok'],
                ]],
                ['Audit Trail', [
                  ['Login success/failure logging', 'ok'],
                  ['Admin impersonation logging', 'ok'],
                  ['Password change logging', 'ok'],
                  ['File upload logging', 'ok'],
                  ['Portfolio view logging', 'warn'],
                ]],
              ].map(([title, items]) => (
                <div key={title} className={CARD}>
                  <h3 className="font-medium text-slate-700 mb-3 text-sm">{title}</h3>
                  <div className="space-y-2">
                    {items.map(([label, status]) => (
                      <div key={label} className="flex items-center justify-between">
                        <span className="text-xs text-slate-600">{label}</span>
                        <StatusBadge status={status} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <Accordion title="PII Encryption">
              <ul className="list-disc list-inside space-y-2">
                <li><strong>Algorithm</strong>: Fernet (AES-128-CBC + HMAC-SHA256)</li>
                <li><strong>Library</strong>: Python cryptography 44.0.0</li>
                <li><strong>Key</strong>: ENCRYPTION_KEY in .env (Fernet.generate_key())</li>
                <li><strong>Fields targeted</strong>: client name, email, phone</li>
                <li><strong>Graceful degradation</strong>: If key not set, PII stored unencrypted with warning log</li>
                <li><strong>Utility</strong>: backend/utils/encryption.py — encrypt_pii() / decrypt_pii()</li>
              </ul>
            </Accordion>
          </Section>

          {/* ─── API REFERENCE ─── */}
          <Section id="api" icon={Code2} title="API Reference">
            <Accordion title="Auth Endpoints (/api/auth)" defaultOpen>
              <Table
                headers={['Method', 'Path', 'Auth', 'Purpose']}
                rows={[
                  ['POST', '/api/auth/login', 'None', 'Authenticate, set JWT + CSRF cookies'],
                  ['POST', '/api/auth/logout', 'JWT', 'Clear cookies'],
                  ['GET', '/api/auth/me', 'JWT', 'Current user profile'],
                  ['POST', '/api/auth/change-password', 'JWT', 'Change password (complexity enforced)'],
                  ['POST', '/api/auth/consent', 'JWT', 'Accept/decline consent (SEBI)'],
                  ['GET', '/api/auth/consents', 'JWT', 'List consent records'],
                ]}
              />
            </Accordion>

            <Accordion title="Portfolio Endpoints (/api/portfolio) — All JWT-protected, client-scoped">
              <Table
                headers={['Method', 'Path', 'Purpose']}
                rows={[
                  ['GET', '/api/portfolio/summary', 'Summary cards (invested, current, profit, CAGR, YTD, DD)'],
                  ['GET', '/api/portfolio/nav-series?range=1Y', 'NAV time series for chart'],
                  ['GET', '/api/portfolio/performance-table', 'Multi-period returns table'],
                  ['GET', '/api/portfolio/growth', 'Growth comparison (portfolio vs Nifty vs FD)'],
                  ['GET', '/api/portfolio/allocation', 'Asset class allocation'],
                  ['GET', '/api/portfolio/holdings?sort=weight', 'Current holdings with P&L'],
                  ['GET', '/api/portfolio/drawdown-series?range=ALL', 'Drawdown underwater chart data'],
                  ['GET', '/api/portfolio/risk-scorecard', 'Risk metrics (capture ratios, beta, etc.)'],
                  ['GET', '/api/portfolio/transactions?page=1', 'Paginated transaction history'],
                  ['GET', '/api/portfolio/monthly-returns', 'Monthly hit rate, heatmap data'],
                  ['GET', '/api/portfolio/methodology', 'All metrics with formulae + inputs'],
                ]}
              />
            </Accordion>

            <Accordion title="Admin Endpoints (/api/admin) — Admin JWT required">
              <Table
                headers={['Method', 'Path', 'Purpose']}
                rows={[
                  ['POST', '/api/admin/recompute-risk', 'Trigger risk recomputation'],
                  ['POST', '/api/admin/recompute-holdings', 'Recalculate all holdings from transactions'],
                  ['POST', '/api/admin/update-prices', 'Fetch latest prices from NSE'],
                  ['POST', '/api/admin/impersonate/{client_id}', 'View as client (audit-logged)'],
                  ['POST', '/api/admin/deduplicate-symbols', 'Soft-delete duplicate transactions'],
                  ['GET', '/api/admin/upload-log', 'Upload history'],
                  ['GET', '/api/admin/dashboard', 'Admin analytics summary'],
                  ['GET', '/api/admin/data-status', 'Data freshness report'],
                  ['POST', '/api/admin/upload-nav', 'Upload NAV file (background)'],
                  ['POST', '/api/admin/upload-transactions', 'Upload transaction file (background)'],
                  ['POST', '/api/admin/upload-holdings', 'Upload holdings reconciliation file'],
                  ['POST', '/api/admin/upload-cashflows', 'Upload cash flow file'],
                  ['GET', '/api/admin/clients', 'List all clients'],
                  ['POST', '/api/admin/clients', 'Create client'],
                  ['POST', '/api/admin/clients/bulk', 'Bulk create from CSV'],
                  ['GET', '/api/admin/aggregate/nav-series', 'Firm-wide composite NAV'],
                  ['GET', '/api/admin/aggregate/metrics', 'Firm-wide risk metrics'],
                  ['POST', '/api/admin/reconciliation/upload', 'Upload holdings report for reconciliation'],
                  ['GET', '/api/admin/reconciliation/summary', 'Reconciliation results'],
                ]}
              />
            </Accordion>

            <Accordion title="Health Check">
              <pre className={CODE_BLOCK}>{`GET /api/health
→ { "status": "healthy", "timestamp": "2026-04-18T12:00:00Z" }

# Version info only shown in non-production environments`}</pre>
            </Accordion>
          </Section>

          {/* ─── DEPLOYMENT ─── */}
          <Section id="deployment" icon={GitBranch} title="Deployment">
            <Accordion title="CI/CD Pipeline" defaultOpen>
              <pre className={CODE_BLOCK}>{`Push to main branch
    ↓
GitHub Actions (.github/workflows/deploy.yml)
    ↓
SSH into EC2 (appleboy/ssh-action)
    ↓
1. git fetch + reset to origin/main
2. docker build -t client-portal .
3. docker rm -f client-portal
4. docker run -d --name client-portal \\
     --env-file .env \\
     -p 8007:3000 -p 8008:8000 \\
     --restart unless-stopped \\
     client-portal
    ↓
5. Wait 45s for boot
6. Health check: curl http://localhost:8008/api/health
7. Update Nginx config if needed
    ↓
Live at clients.jslwealth.in`}</pre>
            </Accordion>

            <Accordion title="Dockerfile (Multi-stage)">
              <pre className={CODE_BLOCK}>{`Stage 1: node:20-slim
  → npm ci + npm run build (Next.js static build)

Stage 2: python:3.11-slim
  → Install Node.js 20 (for Next.js runtime)
  → pip install -r requirements.txt
  → Copy backend/ source
  → Copy frontend/ build from Stage 1
  → Copy scripts/, start.sh
  → EXPOSE 3000 8000
  → CMD ["./start.sh"]`}</pre>
            </Accordion>

            <Accordion title="start.sh (Container Entrypoint)">
              <pre className={CODE_BLOCK}>{`#!/bin/bash
# Starts FastAPI on :8000 and Next.js on :3000 in parallel.
# If either process exits, the container stops.

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1 &
cd frontend && npx next start -p 3000 &
wait -n  # Exit when either process dies`}</pre>
            </Accordion>

            <Accordion title="Manual Operations">
              <p className="font-medium text-slate-700 mb-2">SSH Access:</p>
              <pre className={CODE_BLOCK}>{`ssh ubuntu@<EC2_HOST>
cd ~/apps/client-portal`}</pre>

              <p className="font-medium text-slate-700 mb-2 mt-4">View Logs:</p>
              <pre className={CODE_BLOCK}>{`docker logs client-portal --tail 100 -f`}</pre>

              <p className="font-medium text-slate-700 mb-2 mt-4">Restart Container:</p>
              <pre className={CODE_BLOCK}>{`docker restart client-portal`}</pre>

              <p className="font-medium text-slate-700 mb-2 mt-4">Run Database Migration:</p>
              <pre className={CODE_BLOCK}>{`psql -h <RDS_HOST> -U fie_admin -d client_portal \\
  -f scripts/migration_security_hardening.sql`}</pre>

              <p className="font-medium text-slate-700 mb-2 mt-4">Generate Encryption Key:</p>
              <pre className={CODE_BLOCK}>{`python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add result to .env as ENCRYPTION_KEY=<key>`}</pre>
            </Accordion>
          </Section>

          {/* ─── MONITORING ─── */}
          <Section id="monitoring" icon={Activity} title="Monitoring & Health">
            <Accordion title="Health Check" defaultOpen>
              <pre className={CODE_BLOCK}>{`# Backend API health
curl https://clients.jslwealth.in/api/health

# Docker container status
docker ps | grep client-portal

# Container resource usage
docker stats client-portal --no-stream

# Nginx status
sudo systemctl status nginx

# SSL certificate expiry
sudo certbot certificates`}</pre>
            </Accordion>

            <Accordion title="Database Health">
              <pre className={CODE_BLOCK}>{`-- Table sizes
SELECT relname, n_live_tup
FROM pg_stat_user_tables
WHERE relname LIKE 'cpp_%'
ORDER BY n_live_tup DESC;

-- Connection count
SELECT count(*) FROM pg_stat_activity
WHERE datname = 'client_portal';

-- Recent audit log entries
SELECT action, count(*), max(created_at)
FROM cpp_audit_log
GROUP BY action
ORDER BY max(created_at) DESC;`}</pre>
            </Accordion>

            <Accordion title="Key Metrics to Watch">
              <ul className="list-disc list-inside space-y-2">
                <li><strong>API response time</strong> — /api/portfolio/summary should be &lt;500ms</li>
                <li><strong>Container memory</strong> — should stay under 4GB (of 8GB available)</li>
                <li><strong>DB connections</strong> — pool_size=10, max_overflow=20 (30 max)</li>
                <li><strong>Upload processing time</strong> — 35MB NAV file should process in &lt;5 minutes</li>
                <li><strong>SSL certificate</strong> — Let&apos;s Encrypt, auto-renews via certbot cron</li>
              </ul>
            </Accordion>
          </Section>

          {/* ─── DATA PIPELINE ─── */}
          <Section id="data-pipeline" icon={FileText} title="Data Pipeline">
            <Accordion title="File Upload Flow" defaultOpen>
              <pre className={CODE_BLOCK}>{`Admin uploads .xlsx file via /admin/upload
    ↓
1. Validate file (extension, size ≤ 50MB)
2. Save to temp path
3. Start background processing
4. Frontend polls /api/admin/upload-status/{job_id}
    ↓
5. Parse .xlsx row-by-row (stateful parser)
   → NAV file: extract client code, date, NAV, corpus, cash%
   → Transaction file: extract trades, split buy/sell
    ↓
6. Upsert to database (ON CONFLICT UPDATE)
7. Auto-create clients + portfolios if new
    ↓
8. Post-processing:
   → Fetch NIFTY 50 benchmark data (yfinance)
   → Detect corpus changes → generate XIRR cash flows
   → Run risk engine → compute all metrics
   → Store in cpp_risk_metrics + cpp_drawdown_series
    ↓
9. Log upload in cpp_upload_log
10. Return summary (rows processed, failures, errors)`}</pre>
            </Accordion>

            <Accordion title="Risk Engine Metrics (24 total)">
              <Table
                headers={['Category', 'Metrics']}
                rows={[
                  ['Returns', 'Absolute Return, CAGR, XIRR, TWR Index (Base 100)'],
                  ['Risk', 'Volatility, Max Drawdown, Sharpe Ratio, Sortino Ratio'],
                  ['Benchmark', 'Alpha, Beta, Information Ratio, Tracking Error'],
                  ['Capture', 'Up Capture Ratio, Down Capture Ratio'],
                  ['Stress', 'Ulcer Index, Max Consecutive Loss, Market Correlation'],
                  ['Cash', 'Average Cash Held, Maximum Cash Held, Current Cash'],
                  ['Monthly', 'Monthly Hit Rate, Best/Worst Month, Win/Loss Counts'],
                  ['Holdings', 'FIFO Cost Basis, Unrealized P&L, Weight %'],
                ]}
              />
            </Accordion>

            <Accordion title="Scheduled Tasks">
              <Table
                headers={['Task', 'Schedule', 'Purpose']}
                rows={[
                  ['Price Refresh', 'APScheduler (configurable)', 'Fetch latest NSE prices for holdings'],
                  ['Benchmark Data', 'On NAV upload', 'Fetch/align NIFTY 50 data via yfinance'],
                  ['Risk Recompute', 'On NAV upload + manual trigger', 'Recalculate all metrics'],
                ]}
              />
            </Accordion>
          </Section>

          {/* ─── SEBI COMPLIANCE ─── */}
          <Section id="compliance" icon={FileWarning} title="SEBI Compliance">
            <div className={CARD}>
              <h3 className="font-medium text-slate-700 mb-3">Compliance Infrastructure</h3>
              <div className="space-y-2">
                {[
                  ['Audit trail (logins, admin actions)', 'ok'],
                  ['Soft-delete (7-year retention on source records)', 'ok'],
                  ['Client consent tracking (acceptance + versioning)', 'ok'],
                  ['Regulatory disclaimers on dashboard + login', 'ok'],
                  ['SEBI registration notice', 'ok'],
                  ['Client data isolation (multi-tenancy)', 'ok'],
                  ['Password complexity enforcement', 'ok'],
                  ['Audit trail on portfolio data views', 'warn'],
                  ['Granular RBAC enforcement (per-role permissions)', 'warn'],
                  ['Consent acceptance flow (first-login gate)', 'warn'],
                  ['Automated compliance report generation', 'fail'],
                  ['Data retention auto-purge (after 7 years)', 'fail'],
                  ['Email/notification audit logging', 'fail'],
                ].map(([label, status]) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-sm text-slate-600">{label}</span>
                    <StatusBadge status={status} />
                  </div>
                ))}
              </div>
            </div>
          </Section>

          {/* ─── AREAS FOR ATTENTION ─── */}
          <Section id="attention" icon={AlertTriangle} title="Areas for Attention">
            <p className="text-sm text-slate-500 mb-4">
              Items the tech team should address to achieve full production hardening.
              Ordered by priority.
            </p>

            <div className="space-y-3">
              {[
                {
                  priority: 'HIGH',
                  title: 'Granular RBAC enforcement',
                  detail: 'The role column exists on cpp_clients (CLIENT, ADMIN_DATA_ENTRY, ADMIN_READONLY, ADMIN_FULL) but middleware currently only checks is_admin boolean. Need to add permission checks per role in get_admin_user() middleware.',
                  file: 'backend/middleware/auth_middleware.py',
                },
                {
                  priority: 'HIGH',
                  title: 'PII encryption activation',
                  detail: 'Encryption utility exists (backend/utils/encryption.py) but is not yet called on client model fields. Need to add encrypt_pii()/decrypt_pii() calls in Client model property getters/setters and in auth response serialization. Also need to run a one-time migration to encrypt existing plaintext PII.',
                  file: 'backend/models/client.py + backend/routers/auth.py',
                },
                {
                  priority: 'HIGH',
                  title: 'Consent gate on first login',
                  detail: 'Consent endpoints exist (POST /api/auth/consent, GET /api/auth/consents) but there is no frontend gate that blocks dashboard access until client accepts required consents (RISK_DISCLOSURE, TERMS_OF_SERVICE). Need to add a consent check in the dashboard layout.',
                  file: 'frontend/src/app/dashboard/layout.js',
                },
                {
                  priority: 'MEDIUM',
                  title: 'Portfolio view audit logging',
                  detail: 'Login/admin actions are audit-logged but individual portfolio data views (GET /api/portfolio/*) are not. Add audit logging middleware or per-endpoint log_audit() calls to track who viewed which portfolio data and when.',
                  file: 'backend/routers/portfolio.py',
                },
                {
                  priority: 'MEDIUM',
                  title: 'Rate limiting on portfolio endpoints',
                  detail: 'Rate limiting exists on login (5/min) and uploads (5/min) but portfolio data endpoints have no rate limit. An automated script could scrape all client data rapidly. Add sensible limits (30-60/min) to portfolio routes.',
                  file: 'backend/routers/portfolio.py, portfolio_nav.py, portfolio_detail.py',
                },
                {
                  priority: 'MEDIUM',
                  title: 'NAV/transaction ingestion validation',
                  detail: 'File uploads validate extension and size but not business rules. Should add validation: NAV > 0, price > 0, quantity > 0, cash_pct between 0-100, amount ≈ quantity × price. Log validation warnings without blocking import.',
                  file: 'backend/services/nav_parser.py, txn_parser.py',
                },
                {
                  priority: 'MEDIUM',
                  title: 'JWT refresh token mechanism',
                  detail: 'Currently using single JWT with 24hr expiry. For better security, implement short-lived access tokens (1hr) + long-lived refresh tokens. Refresh endpoint rotates tokens.',
                  file: 'backend/middleware/auth_middleware.py, routers/auth.py',
                },
                {
                  priority: 'LOW',
                  title: 'Centralized logging (CloudWatch/ELK)',
                  detail: 'Application logs go to stdout only. For production observability, configure Docker to forward logs to CloudWatch or ELK stack. Set up alerts for error rate spikes.',
                  file: 'docker-compose.yml, Dockerfile',
                },
                {
                  priority: 'LOW',
                  title: 'Database backup documentation',
                  detail: 'RDS likely has automated backups but RTO/RPO are not documented. Document backup schedule, retention period, and test restore procedures.',
                  file: 'Operational documentation',
                },
                {
                  priority: 'LOW',
                  title: 'Two-factor authentication for admins',
                  detail: 'Admin accounts use password-only auth. Consider adding TOTP-based 2FA for admin accounts to prevent unauthorized access even with compromised credentials.',
                  file: 'backend/routers/auth.py, frontend login flow',
                },
                {
                  priority: 'LOW',
                  title: 'API versioning',
                  detail: 'All endpoints live under /api/ without version prefix. Consider adding /api/v1/ prefix to allow non-breaking API evolution in future.',
                  file: 'backend/main.py, backend/routers/*',
                },
              ].map((item, i) => (
                <div key={i} className={CARD}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                          item.priority === 'HIGH' ? 'bg-red-100 text-red-700' :
                          item.priority === 'MEDIUM' ? 'bg-amber-100 text-amber-700' :
                          'bg-slate-100 text-slate-600'
                        }`}>{item.priority}</span>
                        <span className="font-medium text-slate-700 text-sm">{item.title}</span>
                      </div>
                      <p className="text-xs text-slate-500 leading-relaxed mt-1">{item.detail}</p>
                      <p className="text-xs text-slate-400 mt-1 font-mono">{item.file}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* ─── FOOTER ─── */}
          <div className="border-t border-slate-200 pt-6 mt-10 text-center text-xs text-slate-400 space-y-1">
            <p>JSL Client Portfolio Portal — Technical Documentation</p>
            <p>Jhaveri Securities Limited | SEBI PMS Reg. No: INP000006888</p>
            <p>Generated April 2026</p>
          </div>
        </main>
      </div>
    </div>
  );
}
