# autoanton

Irrigation water balance calculator for wheat fields. Uses WAPOR-3 satellite data (AETI, rainfall, reference ET), Supabase irrigation records, and crop coefficients to compute daily water deltas per field.

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Authenticate with Google Cloud

WAPOR-3 raster data is fetched from Google Cloud Storage. Authenticate with:

```bash
gcloud auth application-default login
```

### 3. Configure Supabase

Create a `.env` file in the project root:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your_publishable_key
```

### 4. Required data files

- `fields.geojson` — field boundaries (16 fields, A-1 through D-4)
- `kc.csv` — crop coefficient (Kc) values by date and field

Both are included in the repo.

## Usage

Open `ai.ipynb` and run the cells. The notebook fetches data, caches it locally under `data/`, and calculates the water balance:

```python
from utils import fetch_aeti, fetch_ret, fetch_rainfall, fetch_irrigations, fetch_kc, calculate_water_delta

planting_date = datetime.date(2025, 12, 10)

aeti = fetch_aeti(planting_date)
rainfall = fetch_rainfall(planting_date)
ret = fetch_ret(planting_date)
kc = fetch_kc()
irrigations = fetch_irrigations(field_ids=list(range(37, 53)), field_names=field_names)

water_delta = calculate_water_delta(irrigations, kc, rainfall, ret)
```

Satellite rasters are cached in `data/aeti/`, `data/rainfall_pcp/`, and `data/ret/` so subsequent runs skip the download.
