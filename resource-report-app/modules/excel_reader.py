"""
excel_reader.py
Loads multiple uploaded .xlsx, .xls, and .csv files into pandas DataFrames.
Generates file preview metadata: row count, detected employee hint, and date range.
"""

from __future__ import annotations
import io
import os
import re
from typing import BinaryIO, Dict, List, Tuple, Union
import pandas as pd


def read_file_to_dataframe(
    file_source: Union[str, BinaryIO, bytes],
    filename: str
) -> pd.DataFrame:
    """
    Reads a single .xlsx, .xls, or .csv file into a pandas DataFrame.
    Handles encoding variations and skips completely blank rows.
    """
    ext = os.path.splitext(filename)[1].lower()

    # If raw bytes, wrap with io.BytesIO for file-like readers
    if isinstance(file_source, bytes):
        file_source = io.BytesIO(file_source)

    if ext in ['.xlsx', '.xlsm', '.xltx', '.xltm']:
        df = pd.read_excel(file_source, engine='openpyxl')
    elif ext == '.xls':
        # Fallback to default engine for older Excel if installed, else openpyxl/xlrd
        try:
            df = pd.read_excel(file_source)
        except Exception:
            df = pd.read_excel(file_source, engine='openpyxl')
    elif ext == '.csv':
        # If byte stream or bytes, handle encodings gracefully
        encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin1', 'iso-8859-1']
        raw_bytes = None
        if isinstance(file_source, bytes):
            raw_bytes = file_source
        elif hasattr(file_source, 'read'):
            raw_bytes = file_source.read()
            if hasattr(file_source, 'seek'):
                file_source.seek(0)

        df = None
        if raw_bytes is not None:
            for enc in encodings:
                try:
                    df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            if df is None:
                df = pd.read_csv(io.BytesIO(raw_bytes), encoding='utf-8', errors='replace')
        else:
            for enc in encodings:
                try:
                    df = pd.read_csv(file_source, encoding=enc)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            if df is None:
                df = pd.read_csv(file_source, encoding='utf-8', errors='replace')
    else:
        raise ValueError(f"Unsupported file format '{ext}' for file '{filename}'. Expected .xlsx, .xls, or .csv.")

    # Drop fully empty rows and columns
    df = df.dropna(how='all')
    df = df.dropna(axis=1, how='all')

    # Strip whitespace from column names if strings
    df.columns = [str(c).strip() if c is not None else f"Unnamed_{i}" for i, c in enumerate(df.columns)]
    return df


def extract_file_preview(df: pd.DataFrame, filename: str) -> Dict:
    """
    Generates preview metadata for an uploaded file:
    - filename
    - row_count
    - columns list
    - detected_employee (from filename or employee column hint)
    - date_range (min and max date string if detected)
    - preview_rows (top 5 rows serialized as dicts)
    """
    row_count = len(df)
    columns = list(df.columns)

    # Detect employee hint
    detected_employee = ""
    # Check filename first (e.g. "TaskStatus - Amit Sondhiya.xlsx" or "Amit_Tasks.csv")
    name_clean = os.path.splitext(os.path.basename(filename))[0]
    name_parts = re.split(r'[-_~]', name_clean)
    candidate_names = [p.strip() for p in name_parts if len(p.strip()) > 3 and not re.search(r'(task|status|report|input|aug|202\d)', p, re.IGNORECASE)]
    if candidate_names:
        detected_employee = candidate_names[0]

    # Look inside dataframe columns if employee is not found in filename
    emp_col = None
    for col in columns:
        if re.search(r'(assign|employee|resource|developer|owner|name)', col, re.I):
            emp_col = col
            break

    if emp_col and not detected_employee:
        non_null_emp = df[emp_col].dropna().astype(str).str.strip()
        unique_emps = [e for e in non_null_emp.unique() if e and e.lower() not in ['nan', 'none', 'null', '']]
        if len(unique_emps) == 1:
            detected_employee = unique_emps[0]
        elif len(unique_emps) > 1:
            detected_employee = f"{unique_emps[0]} (+{len(unique_emps)-1} others)"

    # Detect Date Range
    date_range = "N/A"
    date_col = None
    for col in columns:
        if re.search(r'^(date|task\s*date|entry\s*date)$', col, re.I):
            date_col = col
            break

    if date_col:
        try:
            # Try parsing dates flexible with dayfirst=True
            dates = pd.to_datetime(df[date_col], errors='coerce', dayfirst=True)
            valid_dates = dates.dropna()
            if not valid_dates.empty:
                min_d = valid_dates.min().strftime('%d-%b-%Y')
                max_d = valid_dates.max().strftime('%d-%b-%Y')
                date_range = f"{min_d} to {max_d}"
        except Exception:
            date_range = "Present"

    # Preview rows (top 5) with sanitized values
    preview_slice = df.head(5).fillna("").to_dict(orient='records')
    # Convert any timestamps or non-serializable objects to string
    sanitized_preview = []
    for r in preview_slice:
        sanitized_preview.append({str(k): str(v) for k, v in r.items()})

    return {
        "filename": filename,
        "row_count": row_count,
        "columns": columns,
        "detected_employee": detected_employee or "Multiple / Not specified",
        "date_range": date_range,
        "preview_rows": sanitized_preview
    }


def load_uploaded_files(
    files: List[Tuple[str, Union[str, BinaryIO, bytes]]]
) -> List[Tuple[str, pd.DataFrame, Dict]]:
    """
    Batch loads files.
    Returns list of (filename, dataframe, preview_metadata).
    """
    results = []
    for filename, source in files:
        df = read_file_to_dataframe(source, filename)
        preview = extract_file_preview(df, filename)
        results.append((filename, df, preview))
    return results
