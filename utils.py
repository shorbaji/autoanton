from typing import Dict, List
import datetime
import os
from pathlib import Path
import re
import numpy as np
import pandas as pd
from google.cloud import storage
import rasterio


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


def fetch_aeti(
    planting_date: datetime.date,
    end_date: datetime.date | None = None
) -> np.ndarray:
    """
    Fetch AETI data from Google Cloud Storage for the period from
    two weeks before planting_date to end_date (defaults to today).

    Files are cached locally in ./data/aeti/
    """
    # Set up dates
    if end_date is None:
        end_date = datetime.date.today()

    start_date = planting_date - datetime.timedelta(days=14)

    # Set up cache directory
    cache_dir = Path("./data/aeti")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # GCS bucket and path
    bucket_name = "fao-gismgr-wapor-3-data"
    blob_prefix = "DATA/WAPOR-3/MAPSET/L1-AETI-D/"

    # Initialize GCS client
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # List all blobs in the directory
    blobs = bucket.list_blobs(prefix=blob_prefix)

    # Filter and download relevant files
    aeti_data = []
    dates = []

    for blob in blobs:
        # Extract filename from full path
        filename = os.path.basename(blob.name)

        # Skip if not a TIF file
        if not filename.endswith('.tif'):
            continue

        try:
            # Parse the date range from filename
            dekad_start, dekad_end = parse_aeti_filename(filename)

            # Check if dekad overlaps with our date range
            # Include if any day in the dekad falls within [start_date, end_date]
            if dekad_end >= start_date and dekad_start <= end_date:
                # Check if file is already cached
                cache_path = cache_dir / filename

                if not cache_path.exists():
                    print(f"Downloading {filename}...")
                    blob.download_to_filename(str(cache_path))
                else:
                    print(f"Using cached {filename}")

                # Read the raster data
                with rasterio.open(cache_path) as src:
                    data = src.read(1)  # Read first band
                    aeti_data.append(data)
                    dates.append(dekad_start)  # Use start date for sorting

        except ValueError:
            # Skip files that don't match the expected pattern
            continue

    # Sort by date
    if aeti_data:
        sorted_indices = np.argsort(dates)
        aeti_data = [aeti_data[i] for i in sorted_indices]
        dates = [dates[i] for i in sorted_indices]

        # Stack into 3D array (time, height, width)
        aeti_array = np.stack(aeti_data, axis=0)

        print(f"Fetched {len(aeti_data)} AETI files from {dates[0]} to {dates[-1]}")
        return aeti_array
    else:
        print(f"No AETI files found for date range {start_date} to {end_date}")
        return np.zeros((0, 0, 0))


def fetch_ret() -> np.ndarray:
    ret = np.zeros(30)

    return ret


def fetch_rainfall() -> np.ndarray:
    rainfall = np.zeros(30)
    return rainfall


def fetch_irrigations() -> List[Dict]:
    irrigations = []

    return irrigations


def fetch_kc() -> np.ndarray:
    ndvi = np.zeros(30)
    kc = np.where(ndvi < 0.3, 0.3, ndvi)
    return kc


def calculate_mean_ret(ret: np.ndarray) -> np.ndarray:
    return np.zeros(30)


def calculate_water_loss(
    irrigations: List[Dict],
    kc: np.ndarray,
    rainfall: np.ndarray,
    ret: np.ndarray) -> np.ndarray:
    return np.zeros(30)


def calculate_daily_water_delta(
    irrigations: List[Dict],
    kc: np.ndarray,
    rainfall: np.ndarray,
    ret: np.ndarray,
):
    mean_ret = calculate_mean_ret(ret)

    water_loss = calculate_water_loss(irrigations, kc, rainfall, ret)
    projected_water_loss = calculate_water_loss(irrigations, kc, rainfall, mean_ret)

    daily_water_delta = water_loss + projected_water_loss + irrigations + rainfall

    return daily_water_delta


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
