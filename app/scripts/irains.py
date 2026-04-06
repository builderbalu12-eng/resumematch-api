import requests
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ─── 1. Read IMD Block CSV ───
def read_imd_csv(filepath):
    df = pd.read_csv(filepath)
    df['state_clean'] = df['state_name'].str.strip().str.lower()
    df['district_clean'] = df['district_name'].str.strip().str.lower()
    df['block_clean'] = df['block_name'].astype(str).str.strip().str.lower()
    return df

# ─── 2. Fetch AWS data from all 3 APIs ───
def fetch_aws_data():
    apis = [
        "https://city.imd.gov.in/api/v1/getUPAWS",
        "https://city.imd.gov.in/api/v1/getTelanganaAWS",
        "https://city.imd.gov.in/api/v1/getTamilnaduAWS",
    ]
    all_stations = []
    for url in apis:
        try:
            print(f"Fetching: {url}")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") and data.get("data"):
                for s in data["data"]:
                    block_val = s.get("block") or s.get("tehsil") or ""
                    all_stations.append({
                        "state": str(s.get("state", "")).strip(),
                        "district": str(s.get("district", "")).strip(),
                        "block": str(block_val).strip(),
                        "station_name": str(s.get("station", "")).strip(),
                        "station_id": str(s.get("id", "")).strip(),
                    })
                print(f"  -> Got {len(data['data'])} stations")
        except Exception as e:
            print(f"  -> Error: {e}")
    df = pd.DataFrame(all_stations)
    if not df.empty:
        df['state_clean'] = df['state'].str.lower().str.replace('_', ' ')
        df['district_clean'] = df['district'].str.lower()
        df['block_clean'] = df['block'].str.lower()
    return df

# ─── 3. State name normalization ───
STATE_MAP = {
    'uttar_pradesh': 'uttar pradesh',
    'uttar pradesh': 'uttar pradesh',
    'telanagana': 'telangana',
    'telangana': 'telangana',
    'tamilnadu': 'tamil nadu',
    'tamil nadu': 'tamil nadu',
}

def normalize_state(s):
    s = s.strip().lower().replace('_', ' ')
    return STATE_MAP.get(s, s)

# ─── 4. Build block-level comparison (ALL IMD blocks, LEFT JOIN) ───
def build_comparison(imd_df, aws_df):
    imd_df['state_norm'] = imd_df['state_clean'].apply(normalize_state)

    # Aggregate IMD by state + district + block
    imd_agg = imd_df.groupby(['state_norm', 'district_clean', 'block_clean']).agg(
        state_name=('state_name', 'first'),
        district_name=('district_name', 'first'),
        block_name=('block_name', 'first'),
        block_code=('block_code', 'first'),
        imd_station_count=('station_name', 'count'),
    ).reset_index()

    print(f"  IMD total blocks: {len(imd_agg)}")

    # Aggregate AWS by state + district + block
    if not aws_df.empty:
        aws_df['state_norm'] = aws_df['state_clean'].apply(normalize_state)
        aws_agg = aws_df.groupby(['state_norm', 'district_clean', 'block_clean']).agg(
            aws_station_count=('station_id', 'nunique'),
        ).reset_index()
        print(f"  AWS total blocks: {len(aws_agg)}")
    else:
        aws_agg = pd.DataFrame(columns=['state_norm', 'district_clean', 'block_clean', 'aws_station_count'])
        print("  AWS: No data fetched")

    # LEFT JOIN: IMD is master
    merged = pd.merge(
        imd_agg, aws_agg,
        on=['state_norm', 'district_clean', 'block_clean'],
        how='left'
    )

    # Fill values
    merged['imd_station_count'] = merged['imd_station_count'].fillna(0).astype(int)
    merged['aws_station_count'] = merged['aws_station_count'].fillna(0).astype(int)
    merged['imd_availability'] = merged['imd_station_count'].apply(lambda x: 'Yes' if x > 0 else 'No')
    merged['aws_availability'] = merged['aws_station_count'].apply(lambda x: 'Yes' if x > 0 else 'No')

    # Sort
    merged = merged.sort_values(['state_name', 'district_name', 'block_name']).reset_index(drop=True)
    merged.insert(0, 'sno', range(1, len(merged) + 1))

    # Show unmatched AWS blocks
    if not aws_df.empty:
        aws_blocks = set(zip(aws_agg['state_norm'], aws_agg['district_clean'], aws_agg['block_clean']))
        imd_blocks = set(zip(imd_agg['state_norm'], imd_agg['district_clean'], imd_agg['block_clean']))
        unmatched = aws_blocks - imd_blocks
        if unmatched:
            print(f"\n  WARNING: {len(unmatched)} AWS blocks NOT matched in IMD CSV:")
            for s, d, b in sorted(unmatched)[:30]:
                print(f"    - {s} / {d} / {b}")
            if len(unmatched) > 30:
                print(f"    ... and {len(unmatched) - 30} more")

    return merged

# ─── 5. Write Excel (matching screenshot format exactly) ───
def write_excel(merged, output_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "blocks_with_station_presence"

    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    # ── Row 1: Group headers ──
    for c in range(1, 6):
        ws.cell(row=1, column=c).border = thin_border

    # F1:G1 = "IMD Stations"
    ws.merge_cells('F1:G1')
    cell = ws.cell(row=1, column=6, value='IMD Stations')
    cell.font = Font(bold=True, size=11)
    cell.fill = PatternFill('solid', fgColor='D9E2F3')
    cell.alignment = Alignment(horizontal='center', vertical='center')
    cell.border = thin_border
    ws.cell(row=1, column=7).border = thin_border
    ws.cell(row=1, column=7).fill = PatternFill('solid', fgColor='D9E2F3')

    # H1:I1 = "State Govt Stations"
    ws.merge_cells('H1:I1')
    cell = ws.cell(row=1, column=8, value='State Govt Stations')
    cell.font = Font(bold=True, size=11)
    cell.fill = PatternFill('solid', fgColor='FCE4D6')
    cell.alignment = Alignment(horizontal='center', vertical='center')
    cell.border = thin_border
    ws.cell(row=1, column=9).border = thin_border
    ws.cell(row=1, column=9).fill = PatternFill('solid', fgColor='FCE4D6')

    # ── Row 2: Sub-headers ──
    sub_headers = {
        1: 'S.no',
        2: 'State',
        3: 'District',
        4: 'Block_Name',
        5: 'Block_Code',
        6: 'Availabity of\nstation- IMD',
        7: 'station_count -\nIMD',
        8: 'Availabity of\nstation- State\ngovt',
        9: 'station_count\n- State Govt'
    }
    header_font = Font(bold=True, size=10)
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for col_idx, text in sub_headers.items():
        cell = ws.cell(row=2, column=col_idx, value=text)
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border

    # ── Data rows ──
    yes_fill = PatternFill('solid', fgColor='C6EFCE')
    no_fill = PatternFill('solid', fgColor='FFC7CE')
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')

    for idx, row in merged.iterrows():
        r = idx + 3
        values = [
            row['sno'],
            row['state_name'],
            row['district_name'],
            row['block_name'],
            row['block_code'],
            row['imd_availability'],
            row['imd_station_count'],
            row['aws_availability'],
            row['aws_station_count'],
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=r, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = left_align if col_idx in (2, 3, 4) else center_align

            if col_idx == 6:
                cell.fill = yes_fill if val == 'Yes' else no_fill
            elif col_idx == 8:
                cell.fill = yes_fill if val == 'Yes' else no_fill

    # Column widths
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 38
    ws.column_dimensions['C'].width = 25
    ws.column_dimensions['D'].width = 28
    ws.column_dimensions['E'].width = 16
    ws.column_dimensions['F'].width = 18
    ws.column_dimensions['G'].width = 18
    ws.column_dimensions['H'].width = 20
    ws.column_dimensions['I'].width = 18

    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 50

    ws.freeze_panes = 'A3'
    ws.auto_filter.ref = f"A2:I{len(merged) + 2}"

    wb.save(output_path)
    print(f"\nSaved: {output_path}")

# ─── MAIN ───
if __name__ == "__main__":
    print("=" * 60)
    print("  IMD vs State Govt Station Comparison (BLOCK Level)")
    print("=" * 60)

    csv_path = "/Users/balakrishnaakula/Downloads/block wise stations.csv"
    print(f"\n1. Reading IMD Block CSV: {csv_path}")
    imd_df = read_imd_csv(csv_path)
    print(f"   Rows: {len(imd_df)}")
    print(f"   States: {imd_df['state_clean'].nunique()}")
    print(f"   Districts: {imd_df['district_clean'].nunique()}")
    print(f"   Blocks: {imd_df['block_clean'].nunique()}")

    print(f"\n2. Fetching State Govt AWS data from APIs...")
    aws_df = fetch_aws_data()
    print(f"   AWS stations fetched: {len(aws_df)}")

    print(f"\n3. Building block-level comparison (ALL IMD blocks, LEFT JOIN)...")
    merged = build_comparison(imd_df, aws_df)

    output_path = "IMD_vs_StateGovt_Block_Comparison.xlsx"
    print(f"\n4. Writing Excel...")
    write_excel(merged, output_path)

    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    total = len(merged)
    imd_yes = len(merged[merged['imd_availability'] == 'Yes'])
    aws_yes = len(merged[merged['aws_availability'] == 'Yes'])
    both = len(merged[(merged['imd_availability'] == 'Yes') & (merged['aws_availability'] == 'Yes')])
    print(f"  Total blocks (from IMD): {total}")
    print(f"  Blocks with IMD stations: {imd_yes}")
    print(f"  Blocks with State Govt stations: {aws_yes}")
    print(f"  Blocks with BOTH: {both}")
    print(f"  Blocks with NEITHER: {total - imd_yes - aws_yes + both}")
    print(f"{'=' * 60}")