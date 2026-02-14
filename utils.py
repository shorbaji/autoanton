from typing import Dict, List, Callable, Tuple, Union
import datetime
import os
from pathlib import Path
import re
import numpy as np
import pandas as pd
from google.cloud import storage
import rasterio
from rasterstats import zonal_stats
import json


def parse_aeti_filename(filename: str) -> tuple[datetime.date, datetime.date]:
    """
    Parse WAPOR-3 AETI filename to extract the date range.
    Format: WAPOR-3.L1-AETI-D.YYYY-MM-DX.tif
    where X is 1 (days 1-10), 2 (days 11-20), or 3 (days 21-end of month)

    Returns tuple of (start_date, end_date) for the dekad period.
    """
    pattern = r'WAPOR-3\.L1-AETI-D\.(\d{4})-(\d{2})-D(\d)\.tif'
    match = re.match(pattern, filename)

    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filename}")

    year = int(match.group(1))
    month = int(match.group(2))
    dekad = int(match.group(3))

    # Convert dekad to date range
    if dekad == 1:
        start_day = 1
        end_day = 10
    elif dekad == 2:
        start_day = 11
        end_day = 20
    elif dekad == 3:
        start_day = 21
        # Last day of month
        import calendar
        end_day = calendar.monthrange(year, month)[1]
    else:
        raise ValueError(f"Invalid dekad value: {dekad}")

    start_date = datetime.date(year, month, start_day)
    end_date = datetime.date(year, month, end_day)

    return start_date, end_date


def parse_rainfall_filename(filename: str) -> tuple[datetime.date, datetime.date]:
    """
    Parse WAPOR-3 rainfall filename to extract the date.
    Format: WAPOR-3.L1-PCP-E.YYYY-MM-DD.tif

    Returns tuple of (date, date) for consistency with other parsers.
    """
    pattern = r'WAPOR-3\.L1-PCP-E\.(\d{4})-(\d{2})-(\d{2})\.tif'
    match = re.match(pattern, filename)

    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filename}")

    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    date = datetime.date(year, month, day)
    return date, date


def parse_ret_filename(filename: str) -> tuple[datetime.date, datetime.date]:
    """
    Parse WAPOR-3 RET (Reference Evapotranspiration) filename to extract the date.
    Format: WAPOR-3.L1-RET-E.YYYY-MM-DD.tif

    Returns tuple of (date, date) for consistency with other parsers.
    """
    pattern = r'WAPOR-3\.L1-RET-E\.(\d{4})-(\d{2})-(\d{2})\.tif'
    match = re.match(pattern, filename)

    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filename}")

    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    date = datetime.date(year, month, day)
    return date, date


def _load_fields_geojson(geojson_path: str = "fields.geojson") -> list[dict]:
    """
    Load field boundaries from GeoJSON file.

    Returns:
        List of field dictionaries with 'title' and 'geometry' keys
    """
    with open(geojson_path, 'r') as f:
        data = json.load(f)

    fields = []
    for feature in data['features']:
        fields.append({
            'title': feature['properties']['title'],
            'geometry': feature['geometry']
        })

    return fields


def _extract_field_averages(
    raster_path: Path,
    fields: list[dict]
) -> dict[str, float]:
    """
    Extract average values for each field from a raster file.
    Applies the raster's scale and offset if present.

    Args:
        raster_path: Path to the raster file
        fields: List of field dictionaries with 'title' and 'geometry' keys

    Returns:
        Dictionary mapping field titles to their average values (scaled)
    """
    # Get scale and offset from raster metadata
    with rasterio.open(raster_path) as src:
        scale = src.scales[0] if src.scales else 1.0
        offset = src.offsets[0] if src.offsets else 0.0

    geometries = [f['geometry'] for f in fields]
    stats = zonal_stats(geometries, str(raster_path), stats=["mean"], all_touched=True)

    def apply_scale(mean_val):
        if mean_val is None:
            return np.nan
        return mean_val * scale + offset

    return {f['title']: apply_scale(s['mean']) for f, s in zip(fields, stats)}


def process_aeti_data(file_paths: list[Path]) -> pd.DataFrame:
    """
    Process AETI raster data into a DataFrame with field averages.
    Since AETI files are dekadal (10-day periods), the same value is repeated
    for each day in the dekad.

    Args:
        file_paths: List of paths to cached AETI .tif files (sorted by date)

    Returns:
        DataFrame with 'date' column and one column per field containing average AETI values
    """
    # Load field boundaries
    fields = _load_fields_geojson()

    # Process each file
    data_rows = []
    for file_path in file_paths:
        # Extract date range from filename (AETI files are dekadal)
        filename = file_path.name
        date_start, date_end = parse_aeti_filename(filename)

        # Extract field averages for this dekad (pixels already contain the average)
        field_averages = _extract_field_averages(file_path, fields)

        # Create one row per day in the dekad, using the same average value
        current_date = date_start
        while current_date <= date_end:
            row = {'date': current_date, **field_averages}
            data_rows.append(row)
            current_date += datetime.timedelta(days=1)

    # Create DataFrame
    df = pd.DataFrame(data_rows)

    return df


def process_rainfall_data(file_paths: list[Path]) -> pd.DataFrame:
    """
    Process rainfall raster data into a DataFrame with field averages.
    Each file represents a single day.

    Args:
        file_paths: List of paths to cached rainfall .tif files (sorted by date)

    Returns:
        DataFrame with 'date' column and one column per field containing average rainfall values
    """
    # Load field boundaries
    fields = _load_fields_geojson()

    # Process each file
    data_rows = []
    for file_path in file_paths:
        # Extract date from filename (rainfall files are daily)
        filename = file_path.name
        date, _ = parse_rainfall_filename(filename)

        # Extract field averages for this day
        averages = _extract_field_averages(file_path, fields)

        # Create row with date and field values
        row = {'date': date, **averages}
        data_rows.append(row)

    # Create DataFrame
    df = pd.DataFrame(data_rows)

    return df


def process_ret_data(file_paths: list[Path]) -> pd.DataFrame:
    """
    Process RET (Reference Evapotranspiration) raster data into a DataFrame with field averages.
    Each file represents a single day.

    Args:
        file_paths: List of paths to cached RET .tif files (sorted by date)

    Returns:
        DataFrame with 'date' column and one column per field containing average RET values
    """
    # Load field boundaries
    fields = _load_fields_geojson()

    # Process each file
    data_rows = []
    for file_path in file_paths:
        # Extract date from filename (RET files are daily)
        filename = file_path.name
        date, _ = parse_ret_filename(filename)

        # Extract field averages for this day
        averages = _extract_field_averages(file_path, fields)

        # Create row with date and field values
        row = {'date': date, **averages}
        data_rows.append(row)

    # Create DataFrame
    df = pd.DataFrame(data_rows)

    return df


def _fetch_wapor_data(
    start_date: datetime.date,
    end_date: datetime.date,
    bucket_name: str,
    blob_prefix: str,
    cache_subdir: str,
    filename_parser: Callable[[str], tuple[datetime.date, datetime.date]],
    processor: Callable[[list[Path]], Union[np.ndarray, pd.DataFrame]] | None = None
) -> Union[np.ndarray, pd.DataFrame]:
    """
    Generic function to fetch WAPOR data from GCS with local caching.

    Args:
        start_date: Start date for data range
        end_date: End date for data range
        bucket_name: GCS bucket name
        blob_prefix: Path prefix in the bucket
        cache_subdir: Local cache subdirectory name
        filename_parser: Function to parse filename and extract date range
        processor: Optional function to process the data before returning.
                   If None, loads and stacks arrays. If provided, receives list of file paths
                   for memory-efficient sequential processing.

    Returns:
        Processed array or stacked array of downloaded rasters
    """
    # Set up cache directory
    cache_dir = Path("./data") / cache_subdir
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Initialize GCS client
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # List all blobs in the directory
    blobs = bucket.list_blobs(prefix=blob_prefix)

    # Filter and download relevant files
    file_paths = []
    dates = []

    for blob in blobs:
        # Extract filename from full path
        filename = os.path.basename(blob.name)

        # Skip if not a TIF file
        if not filename.endswith('.tif'):
            continue

        try:
            # Parse the date range from filename
            file_start, file_end = filename_parser(filename)

            # Check if file date range overlaps with our date range
            if file_end >= start_date and file_start <= end_date:
                # Check if file is already cached
                cache_path = cache_dir / filename

                if not cache_path.exists():
                    print(f"Downloading {filename}...")
                    blob.download_to_filename(str(cache_path))
                else:
                    print(f"Using cached {filename}")

                file_paths.append(cache_path)
                dates.append(file_start)  # Use start date for sorting

        except ValueError:
            # Skip files that don't match the expected pattern
            continue

    # Sort by date
    if file_paths:
        sorted_indices = np.argsort(dates)
        file_paths = [file_paths[i] for i in sorted_indices]
        dates = [dates[i] for i in sorted_indices]

        print(f"Fetched {len(file_paths)} files from {dates[0]} to {dates[-1]}")

        # Process or stack the data
        if processor is not None:
            return processor(file_paths)
        else:
            # Load and stack into 3D array (time, height, width)
            data_list = []
            for path in file_paths:
                with rasterio.open(path) as src:
                    data = src.read(1)  # Read first band
                    data_list.append(data)
            return np.stack(data_list, axis=0)
    else:
        print(f"No files found for date range {start_date} to {end_date}")
        return np.zeros((0, 0, 0))


def fetch_aeti(
    planting_date: datetime.date,
    end_date: datetime.date | None = None,
    return_processed: bool = True
) -> Union[np.ndarray, pd.DataFrame]:
    """
    Fetch AETI data from Google Cloud Storage for the period from
    two weeks before planting_date to end_date (defaults to today).

    Files are cached locally in ./data/aeti/

    Args:
        planting_date: Planting date (will fetch from 2 weeks before)
        end_date: End date (defaults to today)
        return_processed: If True, returns DataFrame with field averages per date.
                         If False, returns full stacked array (memory intensive).

    Returns:
        DataFrame with field averages (if return_processed=True) or stacked array of AETI data
    """
    # Set up dates
    if end_date is None:
        end_date = datetime.date.today()

    start_date = planting_date - datetime.timedelta(days=14)

    # GCS bucket and path
    bucket_name = "fao-gismgr-wapor-3-data"
    blob_prefix = "DATA/WAPOR-3/MAPSET/L1-AETI-D/"

    return _fetch_wapor_data(
        start_date=start_date,
        end_date=end_date,
        bucket_name=bucket_name,
        blob_prefix=blob_prefix,
        cache_subdir="aeti",
        filename_parser=parse_aeti_filename,
        processor=process_aeti_data if return_processed else None
    )


def fetch_ret(
    planting_date: datetime.date,
    end_date: datetime.date | None = None
) -> pd.DataFrame:
    """
    Fetch RET (Reference Evapotranspiration) data from Google Cloud Storage
    for the period from two weeks before planting_date to end_date (defaults to today).

    Files are cached locally in ./data/ret/
    Returns a processed array instead of the full raster stack to save memory.

    Args:
        planting_date: Planting date (will fetch from 2 weeks before)
        end_date: End date (defaults to today)

    Returns:
        DataFrame with 'date' column and field averages for RET data
    """
    # Set up dates
    if end_date is None:
        end_date = datetime.date.today()

    start_date = planting_date - datetime.timedelta(days=14)

    # GCS bucket and path
    bucket_name = "fao-gismgr-wapor-3-data"
    blob_prefix = "DATA/WAPOR-3/MAPSET/L1-RET-E/"

    return _fetch_wapor_data(
        start_date=start_date,
        end_date=end_date,
        bucket_name=bucket_name,
        blob_prefix=blob_prefix,
        cache_subdir="ret",
        filename_parser=parse_ret_filename,
        processor=process_ret_data
    )


def fetch_rainfall(
    planting_date: datetime.date,
    end_date: datetime.date | None = None
) -> pd.DataFrame:
    """
    Fetch rainfall data from Google Cloud Storage for the period from
    two weeks before planting_date to end_date (defaults to today).

    Files are cached locally in ./data/rainfall/
    Returns a processed array instead of the full raster stack to save memory.

    Args:
        planting_date: Planting date (will fetch from 2 weeks before)
        end_date: End date (defaults to today)

    Returns:
        DataFrame with 'date' column and field averages for rainfall data
    """
    # Set up dates
    if end_date is None:
        end_date = datetime.date.today()

    start_date = planting_date - datetime.timedelta(days=14)

    # GCS bucket and path
    bucket_name = "fao-gismgr-wapor-3-data"
    blob_prefix = "DATA/WAPOR-3/MAPSET/L1-PCP-E/"

    return _fetch_wapor_data(
        start_date=start_date,
        end_date=end_date,
        bucket_name=bucket_name,
        blob_prefix=blob_prefix,
        cache_subdir="rainfall_pcp",
        filename_parser=parse_rainfall_filename,
        processor=process_rainfall_data
    )


def fetch_irrigations(
    field_ids: List[str],
    field_names: List[str],
    supabase_url: str | None = None,
    supabase_key: str | None = None
) -> pd.DataFrame:
    """
    Fetch irrigation data from Supabase database.

    Args:
        field_ids: List of field IDs to filter by
        field_names: List of field names corresponding to field_ids (same order)
        supabase_url: Supabase project URL (defaults to SUPABASE_URL env var)
        supabase_key: Supabase publishable key (defaults to SUPABASE_PUBLISHABLE_KEY env var)

    Returns:
        DataFrame with 'field_name', 'date', and 'amount_mm' columns
    """
    from supabase import create_client

    if len(field_ids) != len(field_names):
        raise ValueError("field_ids and field_names must have the same length")

    if not field_ids:
        return pd.DataFrame(columns=['field_name', 'date', 'amount_mm'])

    url = supabase_url or os.environ.get("SUPABASE_URL")
    key = supabase_key or os.environ.get("SUPABASE_PUBLISHABLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Either pass supabase_url/supabase_key "
            "or set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY environment variables."
        )

    client = create_client(url, key)

    response = (
        client.table("irrigation")
        .select("field_id, date, amount_mm")
        .in_("field_id", field_ids)
        .eq("archived", False)
        .execute()
    )

    if response.data:
        df = pd.DataFrame(response.data)
        df['date'] = pd.to_datetime(df['date']).dt.date
        # Map field_id to field_name
        id_to_name = dict(zip(field_ids, field_names))
        df['field_name'] = df['field_id'].map(id_to_name)
        df = df.drop(columns=['field_id'])
        return df[['field_name', 'date', 'amount_mm']]
    else:
        return pd.DataFrame(columns=['field_name', 'date', 'amount_mm'])


def fetch_kc(kc_path: str = "kc.csv") -> pd.DataFrame:
    """
    Read Kc (crop coefficient) data from a CSV file.

    Args:
        kc_path: Path to the CSV file containing Kc values

    Returns:
        DataFrame with 'date' column and one column per field containing Kc values
    """
    df = pd.read_csv(kc_path, skiprows=[1])
    df = df.rename(columns={df.columns[0]: 'date'})
    df['date'] = pd.to_datetime(df['date'], format='%d-%b-%y').dt.date
    return df


def calculate_mean_ret(ret: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate the mean RET for each field over the last 7 days.

    Args:
        ret: DataFrame with 'date' column and one column per field containing RET values

    Returns:
        Dictionary mapping field names to their 7-day mean RET values
    """
    # Get field columns (all columns except 'date')
    field_columns = [col for col in ret.columns if col != 'date']

    # Sort by date and get last 7 days
    ret_sorted = ret.sort_values('date')
    last_7_days = ret_sorted.tail(7)

    # Calculate mean for each field
    return {field: last_7_days[field].mean() for field in field_columns}


def calculate_water_delta(
    irrigations: pd.DataFrame,
    kc: pd.DataFrame,
    rainfall: pd.DataFrame,
    ret: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate water delta for each field and date.

    Water delta = irrigation + rainfall - effective_et

    Where effective_et is:
    - ret * kc if no irrigation or rainfall on that day
    - ret if there is irrigation or rainfall

    Args:
        irrigations: DataFrame with 'field_id', 'date', 'amount_mm' columns
        kc: DataFrame with 'date' column and field columns with Kc values
        rainfall: DataFrame with 'date' column and field columns with rainfall values
        ret: DataFrame with 'date' column and field columns with RET values

    Returns:
        DataFrame with 'date' column and field columns with water delta values
    """
    import warnings

    field_columns = [col for col in ret.columns if col != 'date']

    # Check date alignment between ret and kc
    ret_dates = set(ret['date'])
    kc_dates = set(kc['date'])
    common_dates = ret_dates & kc_dates

    if ret_dates != kc_dates:
        missing_in_kc = ret_dates - kc_dates
        missing_in_ret = kc_dates - ret_dates
        if missing_in_kc:
            warnings.warn(f"Dates in RET but not in Kc: {sorted(missing_in_kc)}")
        if missing_in_ret:
            warnings.warn(f"Dates in Kc but not in RET: {sorted(missing_in_ret)}")

    # Filter to common dates only
    ret_filtered = ret[ret['date'].isin(common_dates)].copy()
    kc_filtered = kc[kc['date'].isin(common_dates)].copy()

    # Merge ret and kc on date (inner join on common dates)
    merged = ret_filtered.merge(kc_filtered, on='date', suffixes=('_ret', '_kc'))

    # Check rainfall date alignment
    rainfall_dates = set(rainfall['date'])
    rainfall_missing = common_dates - rainfall_dates
    if rainfall_missing:
        warnings.warn(f"Dates missing in rainfall data: {sorted(rainfall_missing)}")

    # Rename rainfall columns to add _rainfall suffix before merging
    rainfall_renamed = rainfall.rename(
        columns={col: f"{col}_rainfall" for col in rainfall.columns if col != 'date'}
    )

    # Merge with rainfall (left join to keep all common dates)
    merged = merged.merge(rainfall_renamed, on='date', how='left')
    # Fill missing rainfall with 0
    rainfall_cols = [col for col in merged.columns if col.endswith('_rainfall')]
    merged[rainfall_cols] = merged[rainfall_cols].fillna(0)

    # Pivot irrigations to wide format (date x field)
    if not irrigations.empty:
        irrigation_pivot = irrigations.pivot_table(
            index='date', columns='field_name', values='amount_mm', aggfunc='sum', fill_value=0
        ).reset_index()
        # Rename irrigation columns to add _irrig suffix
        irrigation_pivot = irrigation_pivot.rename(
            columns={col: f"{col}_irrig" for col in irrigation_pivot.columns if col != 'date'}
        )

        merged = merged.merge(irrigation_pivot, on='date', how='left')
        # Fill missing irrigation amounts with 0
        irrig_cols = [col for col in merged.columns if col.endswith('_irrig')]
        merged[irrig_cols] = merged[irrig_cols].fillna(0)

    # Calculate water delta for each field
    result_data = {'date': merged['date']}

    for field in field_columns:
        ret_col = f"{field}_ret"
        kc_col = f"{field}_kc"
        rainfall_col = f"{field}_rainfall"
        irrig_col = f"{field}_irrig"

        ret_values = merged[ret_col]
        kc_values = merged[kc_col]
        rainfall_values = merged[rainfall_col]

        # Get irrigation values (0 if column doesn't exist)
        if irrig_col in merged.columns:
            irrig_values = merged[irrig_col]
        else:
            irrig_values = pd.Series(0, index=merged.index)

        # Determine if there's any water input (rainfall or irrigation)
        has_water_input = (rainfall_values > 0) | (irrig_values > 0)

        # Calculate water delta based on condition:
        # - If water input: irrigation + rainfall - ret
        # - If no water input: ret * kc (water loss)
        water_delta = np.where(
            has_water_input,
            irrig_values + rainfall_values - ret_values,
            ret_values * kc_values
        )

        result_data[field] = water_delta

    return pd.DataFrame(result_data)


def calculate_daily_water_delta(
    irrigations: pd.DataFrame,
    kc: pd.DataFrame,
    rainfall: pd.DataFrame,
    ret: pd.DataFrame,
) -> pd.DataFrame:
    mean_ret = calculate_mean_ret(ret)
    print(f"mean ret: {mean_ret}")
    

    water_delta = calculate_water_delta(irrigations, kc, rainfall, ret)
    print(f"water_delta: {water_delta}")
 
    return water_delta   
    # need to project mean_ret forward for the dates in kc after the last date of ret
    
#    projected_water_delta = calculate_water_delta(irrigations, kc, rainfall, mean_ret)

    # concatenation
#    daily_water_delta = water_delta + projected_water_delta 

#    return daily_water_delta


def calculate_daily_water(daily_water_delta: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame()


def calculate_pam_root_zone(
    daily_water: pd.DataFrame,
    root_depth: np.ndarray,
) -> pd.DataFrame:
    return pd.DataFrame()


def calculate_pam_depletion_root_zone(pam_root_zone: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame()


def calculate_moisture_level(pam_root_zone: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame()


def irrigation_trigger(pam_depletion_root_zone: pd.DataFrame) -> datetime.date:
    return datetime.date.today()
