# FILE FORMAT SPECIFICATION — PMS Backoffice Export
# Addendum to CLAUDE.md — append this after the "Data Ingestion Pipeline" section
# Based on actual BJ53 sample files (identical format for all ~200 clients)

---

## ACTUAL FILE FORMATS (PMS Backoffice Export)

Both files are .xlsx (Excel), NOT simple CSVs. The 200-client versions are ~35MB each.
The format is a PMS backoffice report — NOT a flat table. It has embedded headers,
date separator rows, and merged column structures that need stateful parsing.

---

### FILE 1: NAV Report (.xlsx)

#### Raw Column Headers (contain literal newlines and `_x000D_` carriage returns)
```
Col 0: "UCC"
Col 1: "Date"
Col 2: "Corpus"
Col 3: "Equity\nHolding\nAt Mkt"
Col 4: "Investments\nin\nETF"
Col 5: "Cash And\nCash\nEquivalent"
Col 6: "Bank\nBalance"
Col 7: "NAV"
Col 8: "Liquidity\n%"
Col 9: "High\nWater\nMark"
```

#### Date Formats (both observed in backoffice exports)
- `DD-MMM-YYYY` — e.g., `28-Sep-2020` (older exports)
- `DD/MM/YYYY` — e.g., `26/03/2026` (newer exports)

#### Row Types (parse in order)
```
TYPE 1 — Client Name Header:
  UCC = "BHADERESH JITENDRA JHAVERI [BJ53]"    ← Full name with [CODE]
  All other columns = NaN
  → Extract client_name and client_code using regex: (.+?) \[(\w+)\]

TYPE 2 — Data Row:
  UCC = "BJ53      "                            ← Client code (with trailing spaces)
  Date = "28-Sep-2020" or "26/03/2026"          ← DD-MMM-YYYY or DD/MM/YYYY format
  Corpus = 333000.0                             ← Total invested (cumulative)
  Equity Holding At Mkt = 427667.70             ← Market value of stocks
  Investments in ETF = 0.00                     ← ETF holdings value
  Cash And Cash Equivalent = 0.00               ← Cash + liquid funds
  Bank Balance = 0.0                            ← Bank balance
  NAV = 427667.70                               ← Total portfolio value
  Liquidity % = 0.00                            ← Cash as % of NAV
  High Water Mark = 333000.0                    ← HWM for fee calc

TYPE 3 — Grand Total Row (last row):
  UCC = NaN, Date = NaN
  Numeric columns contain grand totals across ALL clients
  → SKIP this row entirely

TYPE 4 — Next Client Header (multi-client file):
  UCC = "NEXT CLIENT NAME [CODE2]"
  → Same as Type 1, sets new client context
```

#### Multi-Client File Structure
```
Row: "RAJESH MEHTA [RM42]"           ← Client 1 name header
Row: RM42, 01-Apr-2021, ...          ← Client 1 data
Row: RM42, 02-Apr-2021, ...
...
Row: NaN, NaN, subtotal...           ← Client 1 subtotal (optional)
Row: "PRIYA SHARMA [PS17]"           ← Client 2 name header
Row: PS17, 01-Jun-2022, ...          ← Client 2 data
...
Row: NaN, NaN, grand total...        ← Grand total (last row)
```

#### Parsing Algorithm (NAV)
```python
def parse_nav_file(filepath: str) -> pd.DataFrame:
    """
    Returns clean DataFrame with columns:
    client_code, client_name, date, corpus, equity_value, cash_value,
    bank_balance, nav, liquidity_pct, high_water_mark
    """
    df = pd.read_excel(filepath)
    
    # Normalize column names (strip newlines and extra spaces)
    df.columns = [str(c).replace('\n', ' ').strip() for c in df.columns]
    # Now: ['UCC', 'Date', 'Corpus', 'Equity Holding At Mkt', 
    #        'Cash And Cash Equivalent', 'Bank Balance', 'NAV', 
    #        'Liquidity %', 'High Water Mark']
    
    records = []
    current_client_code = None
    current_client_name = None
    
    for _, row in df.iterrows():
        ucc = str(row['UCC']).strip() if pd.notna(row['UCC']) else None
        
        if ucc is None:
            continue  # Skip NaN rows (totals)
        
        # Check if this is a client name header: "FULL NAME [CODE]"
        import re
        name_match = re.match(r'^(.+?)\s*\[(\w+)\]$', ucc)
        if name_match:
            current_client_name = name_match.group(1).strip()
            current_client_code = name_match.group(2).strip()
            continue
        
        # Check if this is a data row (UCC is the client code)
        if current_client_code and ucc == current_client_code:
            date_str = str(row['Date']).strip()
            if date_str == 'nan' or not date_str:
                continue
            
            records.append({
                'client_code': current_client_code,
                'client_name': current_client_name,
                'date': pd.to_datetime(date_str, format='%d-%b-%Y'),
                'corpus': float(row['Corpus']) if pd.notna(row['Corpus']) else 0,
                'equity_value': float(row.get('Equity Holding At Mkt', 0)) if pd.notna(row.get('Equity Holding At Mkt')) else 0,
                'cash_value': float(row.get('Cash And Cash Equivalent', 0)) if pd.notna(row.get('Cash And Cash Equivalent')) else 0,
                'bank_balance': float(row.get('Bank Balance', 0)) if pd.notna(row.get('Bank Balance')) else 0,
                'nav': float(row['NAV']) if pd.notna(row['NAV']) else 0,
                'liquidity_pct': float(row.get('Liquidity %', 0)) if pd.notna(row.get('Liquidity %')) else 0,
                'high_water_mark': float(row.get('High Water Mark', 0)) if pd.notna(row.get('High Water Mark')) else 0,
            })
    
    return pd.DataFrame(records)
```

#### NAV → Database Mapping
```
client_code      → cpp_clients.client_code (find-or-create)
client_name      → cpp_clients.name
date             → cpp_nav_series.nav_date
corpus           → cpp_nav_series.invested_amount
nav              → cpp_nav_series.current_value
nav / corpus     → cpp_nav_series.nav_value (compute: NAV as index, base = first corpus)
                   OR store raw NAV as nav_value and corpus as invested_amount
liquidity_pct    → cpp_nav_series.cash_pct
```

**Critical decision:** The NAV column in the file is the absolute portfolio value in ₹ (e.g., ₹50,80,100), NOT a normalized NAV index (like base 100). For the base-100 chart, compute:
```python
nav_index = (nav_on_date / nav_on_inception_date) * 100
```

---

### FILE 2: Transaction Report (.xlsx)

#### Raw Column Structure (20 columns)
The Excel has merged headers. Row 0 contains sub-headers. Actual column positions:

```
Col  0: UCC              — Client code, OR "Date :DD/MM/YY", OR "CLIENT NAME [CODE]", OR NaN (subtotal)
Col  1: Script           — Stock symbol + type, e.g., "RELIANCE     EQ"
Col  2: Exch             — Exchange, e.g., "CM  " (Cash Market)
Col  3: Stno             — Settlement no / "Corpus" / "BONUS"

--- BUY SIDE (cols 4-11) ---
Col  4: Buy Quantity     — Number of shares bought (0 if sell-only)
Col  5: Buy Net Rate     — Price per share
Col  6: Buy GST          — GST charges
Col  7: Buy Other Charges
Col  8: Buy STT          — Securities Transaction Tax
Col  9: Buy Cost Rate    — All-in cost per share (rate + taxes)
Col 10: Buy Amount       — Total buy amount including all costs
Col 11: Buy Amount (ex-STT) — Buy amount excluding STT

--- SALE SIDE (cols 12-19) ---
Col 12: Sale Quantity    — Number of shares sold (0 if buy-only)
Col 13: Sale Net Rate    — Price per share
Col 14: Sale GST
Col 15: Sale STT
Col 16: Sale Other Charges
Col 17: Sale Cost Rate   — All-in cost per share
Col 18: Sale Amount      — Total sale amount including all costs
Col 19: Sale Amount (ex-STT)
```

#### Row Types (stateful parsing)
```
TYPE 0 — Sub-Header Row (Row 0):
  Col 4 = "Quantity", Col 5 = "Net\nRate", etc.
  → SKIP (use fixed column positions instead)

TYPE 1 — Client Name Header:
  UCC = "BHADERESH JITENDRA JHAVERI [BJ53]"
  All other cols = NaN
  → Set current_client_code and current_client_name

TYPE 2 — Date Separator:
  UCC = "     Date :28/09/20"              ← Note: leading spaces, DD/MM/YY format
  All other cols = NaN
  → Parse date: extract with regex, set current_date
  → Format: "Date :DD/MM/YY" — parse as datetime(DD/MM/20YY)

TYPE 3 — Transaction Data Row:
  UCC = "BJ53      "                       ← Client code (padded)
  Script = "RELIANCE     EQ"               ← Symbol + instrument type (padded)
  Exch = "CM  "                            ← Exchange
  Stno = "2020187N" / "Corpus" / "BONUS"   ← Settlement type
  Cols 4-11: Buy data
  Cols 12-19: Sale data
  → This is an actual transaction to store

TYPE 4 — Daily Subtotal:
  UCC = NaN, Script = NaN
  Buy/Sale columns have daily totals
  → SKIP

TYPE 5 — Grand Total (last row):
  UCC = NaN
  Contains grand totals across all dates and clients
  → SKIP
```

#### Script Name Parsing
```python
def parse_script(script_raw: str) -> tuple[str, str]:
    """
    Input:  "RELIANCE     EQ"
    Output: ("RELIANCE", "EQ")  → symbol, instrument_type
    
    Input:  "LIQUIDBEES   EQ"
    Output: ("LIQUIDBEES", "EQ")
    """
    parts = script_raw.strip().split()
    symbol = parts[0].strip()
    instrument = parts[-1].strip() if len(parts) > 1 else "EQ"
    return symbol, instrument
```

#### Settlement Type (Stno) Interpretation
```
"Corpus"     → Initial portfolio holdings (day 1 positions). 
               These are SELL-side entries showing what the client started with.
               Treat as: txn_type = "CORPUS_IN" — initial positions at inception.
               
"BONUS"      → Bonus share credits. Always buy-side. qty > 0, rate = 0.
               Treat as: txn_type = "BONUS"

"2020187N"   → Regular settlement trade. Settlement number format: YYYYSSSD
               where YYYY=year, SSS=settlement sequence, D=direction(?)
               Treat as: txn_type = "BUY" if buy_qty > 0, "SELL" if sale_qty > 0
               A single row can have BOTH buy and sell (rare but possible)
```

#### Determining Buy vs Sell
```python
# A row can be buy-only, sell-only, or both
buy_qty = float(row[4]) if pd.notna(row[4]) and row[4] != 0 else 0
sale_qty = float(row[12]) if pd.notna(row[12]) and row[12] != 0 else 0

if buy_qty > 0:
    # Record a BUY transaction
    txn_type = "BONUS" if stno == "BONUS" else "BUY"
    quantity = buy_qty
    price = float(row[5])        # Buy Net Rate
    cost_rate = float(row[9])    # Buy Cost Rate (all-in)
    amount = float(row[10])      # Buy Amount With Cost

if sale_qty > 0:
    # Record a SELL transaction (or CORPUS_IN for initial positions)
    txn_type = "CORPUS_IN" if stno == "Corpus" else "SELL"
    quantity = sale_qty
    price = float(row[13])       # Sale Net Rate
    cost_rate = float(row[17])   # Sale Cost Rate (all-in)
    amount = float(row[18])      # Sale Amount With Cost
```

#### Cash/Liquid Instruments
These scripts are cash equivalents — flag them as asset_class = "CASH":
```python
CASH_INSTRUMENTS = {"LIQUIDBEES", "LIQUIDETF", "LIQUIDCASE", "LIQUIDPLUS"}
```

#### Parsing Algorithm (Transactions)
```python
def parse_transaction_file(filepath: str) -> pd.DataFrame:
    """
    Returns clean DataFrame with columns:
    client_code, client_name, date, txn_type, symbol, instrument_type,
    exchange, settlement_no, quantity, price, cost_rate, amount, asset_class
    """
    df = pd.read_excel(filepath)
    
    records = []
    current_client_code = None
    current_client_name = None
    current_date = None
    
    for idx, row in df.iterrows():
        ucc = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
        
        if ucc is None:
            continue  # Skip subtotal/total rows
        
        # Type 1: Client name header
        name_match = re.match(r'^(.+?)\s*\[(\w+)\]$', ucc)
        if name_match:
            current_client_name = name_match.group(1).strip()
            current_client_code = name_match.group(2).strip()
            continue
        
        # Type 2: Date separator
        date_match = re.search(r'Date\s*:\s*(\d{2}/\d{2}/\d{2})', ucc)
        if date_match:
            current_date = pd.to_datetime(date_match.group(1), format='%d/%m/%y')
            continue
        
        # Type 3: Transaction data row
        script = row.iloc[1]
        if current_client_code and ucc == current_client_code and pd.notna(script):
            symbol, inst_type = parse_script(str(script))
            stno = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""
            
            asset_class = "CASH" if symbol in CASH_INSTRUMENTS else "EQUITY"
            
            buy_qty = safe_float(row.iloc[4])
            sale_qty = safe_float(row.iloc[12])
            
            if buy_qty > 0:
                records.append({
                    'client_code': current_client_code,
                    'client_name': current_client_name,
                    'date': current_date,
                    'txn_type': 'BONUS' if 'BONUS' in stno else 'BUY',
                    'symbol': symbol,
                    'instrument_type': inst_type,
                    'exchange': str(row.iloc[2]).strip(),
                    'settlement_no': stno,
                    'quantity': buy_qty,
                    'price': safe_float(row.iloc[5]),
                    'cost_rate': safe_float(row.iloc[9]),
                    'amount': safe_float(row.iloc[10]),
                    'asset_class': asset_class,
                })
            
            if sale_qty > 0:
                records.append({
                    'client_code': current_client_code,
                    'client_name': current_client_name,
                    'date': current_date,
                    'txn_type': 'CORPUS_IN' if 'Corpus' in stno else 'SELL',
                    'symbol': symbol,
                    'instrument_type': inst_type,
                    'exchange': str(row.iloc[2]).strip(),
                    'settlement_no': stno,
                    'quantity': sale_qty,
                    'price': safe_float(row.iloc[13]),
                    'cost_rate': safe_float(row.iloc[17]),
                    'amount': safe_float(row.iloc[18]),
                    'asset_class': asset_class,
                })
    
    return pd.DataFrame(records)

def safe_float(val):
    """Safely convert to float, return 0 for non-numeric"""
    try:
        f = float(val)
        return f if not pd.isna(f) else 0.0
    except (ValueError, TypeError):
        return 0.0
```

#### Transaction → Database Mapping
```
client_code   → cpp_clients.client_code (find-or-create)
date          → cpp_transactions.txn_date
txn_type      → cpp_transactions.txn_type (BUY/SELL/BONUS/CORPUS_IN)
symbol        → cpp_transactions.symbol
symbol + type → cpp_transactions.asset_name (we can enrich later with full names)
asset_class   → cpp_transactions.asset_class (EQUITY or CASH)
quantity      → cpp_transactions.quantity
price         → cpp_transactions.price (Net Rate)
amount        → cpp_transactions.amount (Amount With Cost = total outflow/inflow)
settlement_no → cpp_transactions.notes (store for audit trail)
```

---

## BENCHMARK DATA

The NAV file does NOT include benchmark (NIFTY 50/500) values. These must be fetched separately.

### Approach
```python
import yfinance as yf

# Fetch Nifty 50 data for the same date range
nifty = yf.download("^NSEI", start="2020-09-28", end="2026-03-06")
# Use 'Close' column, align dates with NAV data

# Store in cpp_nav_series.benchmark_value
# Missing dates (holidays): forward-fill from last available
```

Or use the existing Nifty data from Market Pulse if already stored in the RDS.

---

## NAV INDEX COMPUTATION

The raw NAV is absolute ₹ value (e.g., ₹50,80,100). For the base-100 chart:

```python
def compute_nav_index(nav_series: pd.Series, base: float = 100) -> pd.Series:
    """Convert absolute NAV to base-100 index from inception"""
    return (nav_series / nav_series.iloc[0]) * base

# Portfolio: base 100 from inception
# Benchmark: rebase to same starting point
# Both start at 100, diverge based on performance
```

---

## PERFORMANCE SUMMARY TABLE COMPUTATION

For the multi-period table (matching Market Pulse format):

| PERIOD | ABSOLUTE RETURN | CAGR | VOLATILITY | MAX DD | SHARPE | SORTINO |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|
| | Port / Bench | Port / Bench | Port / Bench | Port / Bench | Port / Bench | Port / Bench |

Periods: 1 Month, 3 Months, 6 Months, 1 Year, 2 Years, 3 Years, 4 Years, 5 Years, Since Inception

Each metric computed over the TRAILING period from the latest NAV date.

---

## CORPUS CHANGES (Investment Cash Flows)

The NAV file's Corpus column shows total invested amount — it STEPS UP when new money comes in:
```
28-Sep-2020: Corpus = 3,33,000     ← Initial investment
...
02-Nov-2020: Corpus = 5,33,000     ← +₹2,00,000 added
...
04-Jan-2021: Corpus = 10,33,000    ← +₹5,00,000 added
...
```

Detect corpus changes to:
1. Track XIRR cash flows (investment dates + amounts)
2. Show "Amount Invested" correctly on summary cards
3. Mark investment dates on NAV chart with markers

```python
def extract_cash_flows(nav_df: pd.DataFrame) -> list[tuple]:
    """
    Returns list of (date, amount) for XIRR computation
    Positive = money in, Negative = money out (redemption)
    Final entry = -current_value on latest date
    """
    flows = []
    prev_corpus = 0
    for _, row in nav_df.iterrows():
        corpus = row['corpus']
        if corpus != prev_corpus:
            delta = corpus - prev_corpus
            flows.append((row['date'], delta))
            prev_corpus = corpus
    
    # Add terminal value as negative (money "out")
    latest = nav_df.iloc[-1]
    flows.append((latest['date'], -latest['nav']))
    
    return flows
```

---

## 35MB FILE HANDLING

For 200-client files (~35MB each):
1. **Do NOT load entire file into memory at once** — use openpyxl read_only mode or chunked reading
2. **Process client by client** — parse one client's block, upsert, move to next
3. **Progress tracking** — admin UI shows "Processing client 47 of 203..."
4. **Background job** — ingestion runs async, admin polls for status
5. **Estimated time:** ~2-5 minutes per file on EC2

```python
# Memory-efficient reading for large files
from openpyxl import load_workbook

wb = load_workbook(filepath, read_only=True, data_only=True)
ws = wb.active
for row in ws.iter_rows(values_only=True):
    # Process row by row — constant memory
    pass
wb.close()
```
