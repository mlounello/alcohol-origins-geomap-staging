# load_data.py

import pandas as pd
import sys

def main():
    # Path to the CSV (relative to this script)
    csv_path = "data/alcohol_origins.csv"

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"ERROR: Could not find the CSV at {csv_path}")
        sys.exit(1)

    # Print out the first few rows and column names
    print("✅ Successfully loaded CSV. Here are the columns:")
    print(list(df.columns))
    print("\nHere are the first 5 rows:\n")
    print(df.head())

if __name__ == "__main__":
    main()