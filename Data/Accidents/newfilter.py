import pandas as pd
import glob, os

# ── 1)  Parameters ────────────────────────────────────────────────────────────
KEEP_COLS = ['IstRad', 'XGCSWGS84', 'YGCSWGS84',
             'UJAHR', 'UMONAT', 'USTUNDE']

LAT_MIN, LAT_MAX = 51.0, 51.2        # Dresden
LON_MIN, LON_MAX = 13.6, 13.9

frames = []

for path in glob.glob('Unfallorte*_LinRef.*'):          # *.csv and *.txt
    try:
        df = pd.read_csv(path, sep=';', dtype=str, engine='python', encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(path, sep=';', dtype=str, engine='python', encoding='latin-1')

    df = df[[c for c in KEEP_COLS if c in df.columns]]

    if not {'IstRad','XGCSWGS84','YGCSWGS84'}.issubset(df.columns):
        print(f"⚠️  {os.path.basename(path)} skipped (essential columns missing)")
        continue

    # coord strings  → float
    df['lon'] = df['XGCSWGS84'].str.replace(',', '.').astype(float)
    df['lat'] = df['YGCSWGS84'].str.replace(',', '.').astype(float)

    df = df[df['IstRad'] == '1']                            # bicycle only
    df = df[(df['lat'].between(LAT_MIN, LAT_MAX)) &
            (df['lon'].between(LON_MIN, LON_MAX))].copy()   # Dresden

    if df.empty:
        continue

    if 'UJAHR' in df.columns:
        df['year'] = df['UJAHR'].astype(int)                # handy for logging

    frames.append(df)

# ── 2)  Concatenate & write ───────────────────────────────────────────────────
if frames:
    all_years = pd.concat(frames, ignore_index=True)

    # *** NEW LINE: drop the unwanted columns before saving ***
    all_years = all_years.drop(columns=['year','IstRad','XGCSWGS84','YGCSWGS84'],
                               errors='ignore')

    all_years.to_csv('accidents_dresden_bikes_2016_2023.csv', index=False)
    print(f"✅ Saved {len(all_years)} rows from {min(frames, key=len)['UJAHR'].iloc[0]}–"
          f"{max(frames, key=len)['UJAHR'].iloc[0]}")
else:
    print("No Dresden bicycle accidents found in the supplied files.")
