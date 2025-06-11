# load_from_sheets.py

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import sys

def main():
    # 1) Path to your service account JSON
    SERVICE_ACCOUNT_FILE = "alcohol-origins-geomap-cd20d437877f.json"

    # 2) Define the scopes we need (read-only access to Sheets)
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    ]

    try:
        # 3) Authenticate using the service account file
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
    except FileNotFoundError:
        print(f"ERROR: Could not find {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)

    # 4) Authorize gspread with those credentials
    client = gspread.authorize(creds)

    # 5) Specify the Sheet ID and open the sheet
    SHEET_ID = "1obKjWhdnJhK3f6qImN0DrQJEBZP-YigvjrU128QkjMM"  # ← Replace this with your actual sheet ID
    try:
        sheet = client.open_by_key(SHEET_ID)
    except Exception as e:
        print(f"ERROR: Could not open sheet with ID {SHEET_ID}. Exception: {e}")
        sys.exit(1)

    # 6) Select the worksheet/tab name (default is often "Sheet1")
    #    If your students are using a different tab name (e.g., "Data"), adjust accordingly.
    worksheet = sheet.worksheet("Sheet1")

    # 7) Get all values as a list of lists, then convert to DataFrame
    data = worksheet.get_all_values()
    # The first row is assumed to be the header
    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)

    # 8) Print confirmation plus a quick peek
    print("✅ Successfully loaded data from Google Sheets. Columns:")
    print(list(df.columns))
    print("\nFirst 5 rows:\n", df.head())

if __name__ == "__main__":
    main()