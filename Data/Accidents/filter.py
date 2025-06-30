import pandas as pd

# 1) Load the CSV, parsing ;-delimiter and comma-decimal
df = pd.read_csv(
    'Unfallorte2023_LinRef.csv',
    sep=';',
    dtype=str,             # read everything as string first
    usecols=[
        'IstRad','XGCSWGS84','YGCSWGS84','UJAHR','UMONAT','USTUNDE'
    ]
)

# 2) Convert coordinate columns from "123456,789" to float 123456.789
df['lon'] = df['XGCSWGS84'].str.replace(',', '.').astype(float)
df['lat'] = df['YGCSWGS84'].str.replace(',', '.').astype(float)

# 3) Filter only bicycle‐involved accidents
df = df[df['IstRad'] == '1']

# 4) Define Dresden bounding box (approximate)
LAT_MIN, LAT_MAX = 51.0, 51.2
LON_MIN, LON_MAX = 13.6, 13.9

df_dresden = df[
    (df['lat'] >= LAT_MIN) &
    (df['lat'] <= LAT_MAX) &
    (df['lon'] >= LON_MIN) &
    (df['lon'] <= LON_MAX)
].copy()

# 5) (Optional) Parse timestamp info into a datetime
df_dresden['year']   = df_dresden['UJAHR'].astype(int)
df_dresden['month']  = df_dresden['UMONAT'].astype(int)
df_dresden['hour']   = df_dresden['USTUNDE'].astype(int)

# 6) Save the filtered result
df_dresden.to_csv('accidents_dresden_bikes.csv', index=False)

print(f"Found {len(df_dresden)} bicycle accidents in Dresden.")
