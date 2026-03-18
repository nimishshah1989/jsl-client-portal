"""
stock_reference.py — NSE symbol → sector mapping for CPP holdings classification.

Rules:
  - ETFs tracked separately (BANKBEES, NIFTYBEES, etc.) → mapped by underlying exposure
  - Liquid ETFs (LIQUIDBEES, LIQUIDETF, LIQUIDCASE) → asset_class=CASH, not a sector
  - Gold ETFs (GOLDBEES, SILVERBEES) → 'Gold'
  - Unrecognised symbols → 'Other'
"""

# Symbols whose asset_class must be overridden to 'Cash' regardless of sector mapping.
# These are liquid fund instruments, not equity holdings.
CASH_INSTRUMENTS: set[str] = {
    "LIQUIDBEES",
    "LIQUIDETF",
    "LIQUIDCASE",
}

# fmt: off
SECTOR_MAP: dict[str, str] = {
    # ── Banking & Finance ────────────────────────────────────────────────────
    "AXISBANK":     "Banking",
    "AUBANK":       "Banking",
    "BANKBARODA":   "Banking",
    "FEDERALBNK":   "Banking",
    "HDFCBANK":     "Banking",
    "ICICIBANK":    "Banking",
    "ICICI":        "Banking",
    "IDBI":         "Banking",
    "INDIANB":      "Banking",
    "INDUS":        "Banking",
    "SBIN":         "Banking",
    "UNIONBANK":    "Banking",

    "ABCAPITAL":    "Financial Services",
    "ANGEL":        "Financial Services",
    "BSE":          "Financial Services",
    "CDSL":         "Financial Services",
    "CHOLAFIN":     "Financial Services",
    "GROWWAMC":     "Financial Services",
    "HDFCAMC":      "Financial Services",
    "IEX":          "Financial Services",
    "MCX":          "Financial Services",
    "MFSL":         "Financial Services",
    "POONAWALLA":   "Financial Services",
    "SUNDARMFIN":   "Financial Services",

    # ── Hospitals ────────────────────────────────────────────────────────────
    "APOLLO":       "Healthcare",   # Apollo Hospitals

    # ── Insurance ────────────────────────────────────────────────────────────
    "GICRE":        "Insurance",
    "HDFCLIFE":     "Insurance",
    "ICICIPRULI":   "Insurance",
    "MAXHEALTH":    "Healthcare",   # Max Healthcare is hospitals, not insurance
    "SBILIFE":      "Insurance",

    # ── Information Technology ───────────────────────────────────────────────
    "BSOFT":        "IT",
    "CYIENT":       "IT",
    "HGS":          "IT",
    "INFY":         "IT",
    "KPITTECH":     "IT",
    "LTI":          "IT",
    "PERSISTENT":   "IT",
    "TCS":          "IT",
    "TATAELXSI":    "IT",
    "TECHM":        "IT",
    "WIPRO":        "IT",

    # ── Pharmaceuticals & Healthcare ─────────────────────────────────────────
    "ALKEM":        "Pharma",
    "ASTERDM":      "Healthcare",
    "DIVISLAB":     "Pharma",
    "DRREDDY":      "Pharma",
    "FORTIS":       "Healthcare",
    "GLENMARK":     "Pharma",
    "LUPIN":        "Pharma",
    "NAVINFLUOR":   "Pharma",
    "PFIZER":       "Pharma",
    "SUNPHARMA":    "Pharma",
    "SUVENPHAR":    "Pharma",
    "TORNTPHARM":   "Pharma",
    "WOCKPHARMA":   "Pharma",

    # ── Oil, Gas & Petrochemicals ────────────────────────────────────────────
    "DEEPAKFERT":   "Chemicals",
    "DEEPAKNTR":    "Chemicals",
    "GUJGASLTD":    "Oil & Gas",
    "HINDPETRO":    "Oil & Gas",
    "OIL":          "Oil & Gas",
    "ONGC":         "Oil & Gas",
    "RELIANCE":     "Oil & Gas",

    # ── Chemicals & Specialty ────────────────────────────────────────────────
    "ALKYLAMINE":   "Chemicals",
    "BASF":         "Chemicals",
    "FINEORG":      "Chemicals",
    "GSFC":         "Chemicals",
    "NFL":          "Chemicals",
    "PIDILITIND":   "Chemicals",
    "POLYPLEX":     "Chemicals",
    "PRIVI":        "Chemicals",
    "RCF":          "Chemicals",
    "SRF":          "Chemicals",
    "TATACHEM":     "Chemicals",

    # ── Automobiles & Auto Ancillaries ──────────────────────────────────────
    "ASHOKLEY":     "Automobiles",
    "BAJAJ-AUTO":   "Automobiles",
    "EICHERMOT":    "Automobiles",
    "ESCORTS":      "Automobiles",
    "HEROMOTOCO":   "Automobiles",
    "M&M":          "Automobiles",
    "MARUTI":       "Automobiles",
    "TATAMOTORS":   "Automobiles",
    "TIINDIA":      "Auto Ancillaries",
    "TVSMOTOR":     "Automobiles",

    "EXIDEIND":     "Auto Ancillaries",
    "HBLENGINE":    "Auto Ancillaries",
    "MINDACORP":    "Auto Ancillaries",
    "MINDAIND":     "Auto Ancillaries",
    "BELRISE":      "Auto Ancillaries",

    # ── Metals & Mining ──────────────────────────────────────────────────────
    "COALINDIA":    "Metals & Mining",
    "HINDALCO":     "Metals & Mining",
    "HINDZINC":     "Metals & Mining",
    "JSWSTEEL":     "Metals & Mining",
    "NATIONALUM":   "Metals & Mining",
    "SAIL":         "Metals & Mining",
    "TATASTEEL":    "Metals & Mining",
    "VEDL":         "Metals & Mining",

    # ── Capital Goods & Engineering ──────────────────────────────────────────
    "ABB":          "Capital Goods",
    "BDL":          "Capital Goods",
    "BEL":          "Capital Goods",
    "BEML":         "Capital Goods",
    "BHEL":         "Capital Goods",
    "CUMMINSIND":   "Capital Goods",
    "ENGINERSIN":   "Capital Goods",
    "HAL":          "Capital Goods",
    "KEC":          "Capital Goods",
    "LT":           "Capital Goods",
    "POLYCAB":      "Capital Goods",
    "SIEMENS":      "Capital Goods",
    "TRITURBINE":   "Capital Goods",

    # ── Infrastructure ───────────────────────────────────────────────────────
    "ADANIPORTS":   "Infrastructure",
    "GMR":          "Infrastructure",
    "GMRINFRA":     "Infrastructure",
    "IRB":          "Infrastructure",
    "IRCON":        "Infrastructure",
    "NCC":          "Infrastructure",
    "PNCINFRA":     "Infrastructure",
    "RAILTEL":      "Infrastructure",

    # ── Power & Utilities ────────────────────────────────────────────────────
    "ADANITRANS":   "Power",
    "ADANIGREEN":   "Power",
    "NTPC":         "Power",
    "PFC":          "Power",
    "POWERGRID":    "Power",
    "RECLTD":       "Power",
    "SWANENERGY":   "Power",
    "TATAPOWER":    "Power",

    # ── FMCG & Consumer ──────────────────────────────────────────────────────
    "BATAINDIA":    "Consumer",
    "HINDUNILVR":   "FMCG",
    "ITC":          "FMCG",
    "MARICO":       "FMCG",
    "RELAXO":       "Consumer",
    "VBL":          "FMCG",

    # ── Consumer Durables ────────────────────────────────────────────────────
    "AMBER":        "Consumer Durables",
    "BUTTERFLY":    "Consumer Durables",
    "HAVELLS":      "Consumer Durables",
    "HIL":          "Consumer Durables",
    "TITAN":        "Consumer Durables",

    # ── Paints & Building Materials ──────────────────────────────────────────
    "ASIANPAINT":   "Paints",
    "ASTRAL":       "Building Materials",
    "BIRLACORPN":   "Cement",
    "CENTURYPLY":   "Building Materials",
    "CENTURYTEX":   "Textiles",
    "SUPREMEIND":   "Building Materials",
    "TINPLATE":     "Metals & Mining",
    "ULTRACEMCO":   "Cement",

    # ── Real Estate ──────────────────────────────────────────────────────────
    "ADANI":        "Conglomerate",
    "ADANIENT":     "Conglomerate",
    "DLF":          "Real Estate",

    # ── Logistics & Transport ────────────────────────────────────────────────
    "GDL":          "Logistics",
    "INDIGO":       "Aviation",

    # ── Media & Entertainment ────────────────────────────────────────────────
    "DELTACORP":    "Gaming & Entertainment",
    "PVR":          "Media & Entertainment",
    "SAREGAMA":     "Media & Entertainment",
    "ONMOBILE":     "Media & Entertainment",

    # ── Hospitality & Travel ─────────────────────────────────────────────────
    "INDHOTEL":     "Hospitality",

    # ── Telecom ──────────────────────────────────────────────────────────────
    "BHARTIARTL":   "Telecom",
    "HFCL":         "Telecom",
    "TATACOMM":     "Telecom",

    # ── Agri & Fertilisers ───────────────────────────────────────────────────
    "DHAMPURSUG":   "Agri & Sugar",
    "TRIVENI":      "Agri & Sugar",

    # ── Diversified / Conglomerate ───────────────────────────────────────────
    "TATAINVEST":   "Conglomerate",
    "RAYMOND":      "Diversified",

    # ── Housing Finance ──────────────────────────────────────────────────────
    "AAVAS":        "Housing Finance",

    # ── Staffing & HR ────────────────────────────────────────────────────────
    "TEAMLEASE":    "Staffing",

    # ── Internet / New Age ───────────────────────────────────────────────────
    "JUSTDIAL":     "Internet & E-Commerce",
    "NAUKRI":       "Internet & E-Commerce",
    "ZOMATO":       "Internet & E-Commerce",

    # ── Jubilant group ───────────────────────────────────────────────────────
    "JUBILANT":     "FMCG",

    # ── ETFs — Equity Indices ────────────────────────────────────────────────
    "BANKBEES":     "ETF - Banking",
    "CPSEETF":      "ETF - PSU",
    "FMCGIETF":     "ETF - FMCG",
    "HNGSNGBEES":   "ETF - International",
    "JUNIORBEES":   "ETF - Equity",
    "NIFTYBEES":    "ETF - Equity",
    "PHARMABEES":   "ETF - Pharma",
    "PSUBNKBEES":   "ETF - PSU Bank",

    # ── ETFs — Gold & Silver ─────────────────────────────────────────────────
    "GOLDBEES":     "Gold",
    "SILVERBEES":   "Silver",

    # ── Mutual Fund / AMC-issued instruments ────────────────────────────────
    # (partial names that appear in holdings — mapped best-effort)
    "Amara":        "Auto Ancillaries",    # Amara Raja Batteries
    "Computer":     "IT",                  # Computer Age Management Services (CAMS)
    "Data":         "IT",                  # Data Patterns
    "Jupiter":      "Financial Services",  # Jupiter Wagons / could be fund
    "Mankind":      "Pharma",              # Mankind Pharma
    "Mirae":        "ETF - Equity",        # Mirae ETF product
    "Samvardhana":  "Auto Ancillaries",    # Samvardhana Motherson
}
# fmt: on


def get_sector(symbol: str) -> str:
    """
    Return the sector for a given NSE symbol.
    Falls back to 'Other' for unrecognised symbols.
    Liquid instruments should be checked via is_cash_instrument() first.
    """
    return SECTOR_MAP.get(symbol, "Other")


def is_cash_instrument(symbol: str) -> bool:
    """Return True if this symbol should be classified as asset_class='Cash'."""
    return symbol in CASH_INSTRUMENTS
