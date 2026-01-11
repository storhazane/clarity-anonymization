"""File reading and parsing utilities."""
import csv
import json
import pandas as pd
from io import StringIO
from datetime import datetime


def safe_json_read(zip_obj, file_path):
    """
    Safely read JSON from a ZIP file, trying multiple encodings.
    
    Args:
        zip_obj: ZipFile object
        file_path: Path to file within ZIP
        
    Returns:
        dict or list: Parsed JSON data
        
    Raises:
        ValueError: If file cannot be decoded
    """
    content = zip_obj.open(file_path).read()
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            return json.loads(content.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"Could not decode {file_path}")


def detect_delimiter(file):
    """
    Detect the delimiter used in a CSV file.
    
    Args:
        file: File-like object
        
    Returns:
        str: Detected delimiter (default: ',')
    """
    try:
        file.seek(0)
        sample = file.read(4096)
        file.seek(0)
        
        if isinstance(sample, bytes):
            sample = sample.decode('utf-8')
        
        sniffer = csv.Sniffer()
        delimiter = sniffer.sniff(sample).delimiter
        return delimiter
    except:
        return ','


def round_timestamp(ts_string, round_to_minutes=1):
    """
    Round a timestamp to the nearest interval.
    
    Args:
        ts_string: Timestamp string in ISO format
        round_to_minutes: Minutes to round to (default: 1)
        
    Returns:
        str: Rounded timestamp string
    """
    if not ts_string:
        return ts_string
    
    try:
        # Handle Unix timestamps (numeric strings)
        if ts_string.replace('.', '', 1).isdigit():
            ts_float = float(ts_string)
            dt = datetime.fromtimestamp(ts_float)
        else:
            # Parse ISO format or other common formats
            dt = datetime.fromisoformat(ts_string.replace('Z', '+00:00'))
        
        # Round to nearest interval
        rounded_minute = (dt.minute // round_to_minutes) * round_to_minutes
        rounded_dt = dt.replace(minute=rounded_minute, second=0, microsecond=0)
        
        return rounded_dt.isoformat()
    except:
        return ts_string


def calculate_tenure_band(df):
    """
    Calculate tenure band from Date_of_Hire.
    
    Tenure bands:
    - 0-3 months
    - 3-6 months
    - 6-12 months
    - 1-2 years
    - 2-5 years
    - 5+ years
    
    Args:
        df: DataFrame with hire date column
        
    Returns:
        DataFrame: DataFrame with Tenure_Band column added
    """
    # Find hire date column
    hire_date_col = None
    for col in df.columns:
        if 'hire' in col.lower() and 'date' in col.lower():
            hire_date_col = col
            break
    
    if not hire_date_col:
        df['Tenure_Band'] = None
        return df
    
    # Convert to datetime
    df[hire_date_col] = pd.to_datetime(df[hire_date_col], errors='coerce')
    
    # Calculate tenure in days
    current_date = pd.Timestamp.now()
    df['tenure_days'] = (current_date - df[hire_date_col]).dt.days
    
    # Assign tenure bands
    def assign_band(days):
        if pd.isna(days):
            return None
        elif days < 0:
            return None  # Future hire date
        elif days <= 90:  # 0-3 months
            return "0-3 months"
        elif days <= 180:  # 3-6 months
            return "3-6 months"
        elif days <= 365:  # 6-12 months
            return "6-12 months"
        elif days <= 730:  # 1-2 years
            return "1-2 years"
        elif days <= 1825:  # 2-5 years
            return "2-5 years"
        else:  # 5+ years
            return "5+ years"
    
    df['Tenure_Band'] = df['tenure_days'].apply(assign_band)
    df.drop('tenure_days', axis=1, inplace=True)
    
    return df