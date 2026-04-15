import requests
import pandas as pd
import numpy as np
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule
import warnings
warnings.filterwarnings("ignore")

today = datetime.now().strftime("%Y-%m-%d")

# ── FETCH ─────────────────────────────────────────────────────────────────────
r = requests.post(
    "https://irainshydro.imd.gov.in:3000/api/v1/up-aws/daily",
    json={"startDate": today, "endDate": today},
    timeout=20,
    verify=False
)

rows = r.json().get("data", [])
df   = pd.DataFrame(rows)

if df.empty:
    print("No data found")
    raise SystemExit

# Convert dat UTC → IST date string
if "dat" in df.columns:
    df["dat"] = pd.to_datetime(df["dat"], utc=True, errors="coerce") \
                  .dt.tz_convert("Asia/Kolkata") \
                  .dt.strftime("%Y-%m-%d")

# ── STYLES ────────────────────────────────────────────────────────────────────
HDR_FILL   = PatternFill("solid", fgColor="1F3864")
HDR_FONT   = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
SUB_FONT   = Font(size=9, color="666666", italic=True)
BODY_FONT  = Font(size=10)
CENTER     = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT       = Alignment(horizontal="left", vertical="center", indent=1)
RIGHT      = Alignment(horizontal="right", vertical="center")
thin       = Side(style="thin", color="D0D0D0")
BORDER     = Border(left=thin, right=thin, top=thin, bottom=thin)
EVEN_FILL  = PatternFill("solid", fgColor="F5F8FF")
ODD_FILL   = PatternFill("solid", fgColor="FFFFFF")

# ── WORKBOOK ──────────────────────────────────────────────────────────────────
wb       = Workbook()
ws       = wb.active
ws.title = "API Data"

all_cols = df.columns.tolist()
pretty   = [c.replace("_", " ").title() for c in all_cols]
end_col  = get_column_letter(len(all_cols) + 1)

# Title
ws.merge_cells(f"B2:{end_col}2")
ws["B2"]            = f"UP AWS — All Station Data  ({today})"
ws["B2"].font       = TITLE_FONT
ws["B2"].alignment  = CENTER
ws.row_dimensions[2].height = 30

ws.merge_cells(f"B3:{end_col}3")
ws["B3"]           = f"Rows: {len(df)}  |  Columns: {len(all_cols)}  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} IST"
ws["B3"].font      = SUB_FONT
ws["B3"].alignment = CENTER
ws.row_dimensions[3].height = 16

# Headers
for j, h in enumerate(pretty, start=2):
    c           = ws.cell(row=5, column=j, value=h)
    c.font      = HDR_FONT
    c.fill      = HDR_FILL
    c.alignment = CENTER
    c.border    = BORDER
ws.row_dimensions[5].height = 30

# Data rows
for i, row in enumerate(df.itertuples(index=False), start=6):
    fill = EVEN_FILL if i % 2 == 0 else ODD_FILL
    for j, col in enumerate(all_cols, start=2):
        v = getattr(row, col)
        if isinstance(v, float) and np.isnan(v):
            v = None
        c           = ws.cell(row=i, column=j, value=v)
        c.font      = BODY_FONT
        c.border    = BORDER
        c.fill      = fill
        c.alignment = RIGHT if isinstance(v, (int, float)) else LEFT
    ws.row_dimensions[i].height = 16

last_row = len(df) + 5

# Auto filter + freeze
ws.auto_filter.ref = f"B5:{end_col}{last_row}"
ws.freeze_panes    = "D6"

# Color scale on total_rainfall
if "total_rainfall" in all_cols:
    rf_col = get_column_letter(all_cols.index("total_rainfall") + 2)
    ws.conditional_formatting.add(
        f"{rf_col}6:{rf_col}{last_row}",
        ColorScaleRule(
            start_type="min",        start_color="FFFFFF",
            mid_type="num",          mid_value=5,    mid_color="BDD7EE",
            end_type="max",          end_color="1F3864"
        )
    )

# Auto column widths
ws.column_dimensions["A"].width = 3
for j, col in enumerate(all_cols, start=2):
    max_len = max(len(pretty[j - 2]), 10)
    sample  = df[col].fillna("").astype(str).head(200)   # ✅ fix here
    if not sample.empty:
        max_len = min(max(max_len, sample.map(len).max()), 35)
    ws.column_dimensions[get_column_letter(j)].width = max_len + 2

# Footer
ws[f"B{last_row + 2}"]      = f"Source: IRAINS UP AWS API  |  Date: {today}"
ws[f"B{last_row + 2}"].font = SUB_FONT

# ── SAVE ──────────────────────────────────────────────────────────────────────
out = f"up_aws_{today}.xlsx"
wb.save(out)
print(f"✅ Saved: {out}  ({len(df)} records, {len(all_cols)} columns)")