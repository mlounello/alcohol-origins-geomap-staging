# create_map.py

import pandas as pd
import folium
import gspread
from google.oauth2.service_account import Credentials
import sys

def load_sheet_to_df(sheet_id: str, worksheet_name: str = "Sheet1") -> pd.DataFrame:
    """
    Authenticate using service_account.json, open the Google Sheet by ID,
    read the specified worksheet into a pandas DataFrame, and return it.
    """
    SERVICE_ACCOUNT_FILE = "alcohol-origins-geomap-cd20d437877f.json"
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    except FileNotFoundError:
        print(f"ERROR: Could not find {SERVICE_ACCOUNT_FILE}. Make sure it’s in your project root.")
        sys.exit(1)

    client = gspread.authorize(creds)

    try:
        sheet = client.open_by_key(sheet_id)
    except Exception as e:
        print(f"ERROR: Could not open sheet with ID {sheet_id}. Exception: {e}")
        sys.exit(1)

    try:
        worksheet = sheet.worksheet(worksheet_name)
    except Exception:
        print(f"ERROR: Worksheet named '{worksheet_name}' not found. Check your tab name.")
        sys.exit(1)

    data = worksheet.get_all_values()
    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)
    return df

def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert latitude/longitude columns to floats and drop rows missing valid coords.
    """
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    return df

def add_parent_child_lines(m: folium.Map, df: pd.DataFrame) -> None:
    """
    Draws a polyline between each child node and its parent node, if parent_id exists.
    """
    # Build a lookup: node_id -> (lat, lon)
    coords_lookup = {
        row["node_id"]: (row["latitude"], row["longitude"])
        for _, row in df.iterrows()
        if pd.notna(row["node_id"]) and row["node_id"] != ""
    }

    # For every row with a parent_id, draw a line from parent coords → child coords
    for _, row in df.iterrows():
        parent_id = row["parent_id"]
        child_id = row["node_id"]
        if pd.notna(parent_id) and parent_id != "":
            if parent_id not in coords_lookup:
                print(f"Warning: parent_id '{parent_id}' not found in node_id list. Skipping line for child '{child_id}'.")
                continue
            parent_coords = coords_lookup[parent_id]
            child_coords = (row["latitude"], row["longitude"])
            folium.PolyLine(
                locations=[parent_coords, child_coords],
                color="gray",
                weight=2,
                opacity=0.6
            ).add_to(m)

def add_legend(m: folium.Map, group_color_map: dict) -> None:
    """
    Injects a simple HTML legend in the top-right corner of the map.
    group_color_map: dict mapping group name -> color string
    """
    legend_html = """
     <div style="
       position: fixed; 
       top: 10px; right: 10px; 
       width: 150px; 
       background-color: white;
       border:2px solid gray; 
       z-index:9999; 
       font-size:14px;
       line-height:18px;
       padding: 10px;
       box-shadow: 3px 3px 6px rgba(0,0,0,0.2);
     ">
     <b>Legend</b><br>
    """
    for group, color in group_color_map.items():
        legend_html += f"""
         <i style="background:{color}; width:12px; height:12px; display:inline-block; margin-right:6px;"></i>
         {group}<br>
        """
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

def create_folium_map(df: pd.DataFrame) -> folium.Map:
    """
    Creates a Folium map, plots each point with color-coding by group,
    draws parent→child lines, and injects a legend.
    """
    # --- 1) Define colors for each group ---
    group_color_map = {
        "Grain": "gold",
        "Grape": "purple",
        "Sugar": "saddlebrown",
        "Cactus": "green"
    }

    # --- 2) Compute map center as mean of all points ---
    center_lat = df["latitude"].mean()
    center_lon = df["longitude"].mean()

    # --- 3) Initialize Folium map ---
    m = folium.Map(location=[center_lat, center_lon], zoom_start=2)

    # --- 4) Draw parent→child lines first (so that markers sit on top) ---
    add_parent_child_lines(m, df)

    # --- 5) Add each row as a CircleMarker, color by group ---
    for _, row in df.iterrows():
        color = group_color_map.get(row["group"], "blue")  # Default to blue if unknown group
        popup_html = f"""
        <strong>{row['node_id']}</strong><br>
        Type: {row['type']}<br>
        Group: {row['group']}<br>
        Date: {row['date']}<br>
        Description: {row['description']}<br>
        Citation: {row['citation']}
        """
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(m)

    # --- 6) Add Legend/Sidebar ---
    add_legend(m, group_color_map)

    return m

def main():
    SHEET_ID = "1obKjWhdnJhK3f6qImN0DrQJEBZP-YigvjrU128QkjMM"
    WORKSHEET = "Sheet1"

    # 1) Load the sheet into a DataFrame
    df = load_sheet_to_df(SHEET_ID, WORKSHEET)
    print("✅ Loaded sheet. Now preparing DataFrame...")

    # 2) Clean lat/long and drop invalid rows
    df = prepare_dataframe(df)
    print(f"✅ DataFrame prepared: {len(df)} valid points found.")

    # 3) Create the map
    fmap = create_folium_map(df)
    print("✅ Folium map with lines and color‐coded markers created.")

    # 4) Save map to HTML
    output_file = "docs/index.html"
    fmap.save(output_file)
    print(f"✅ Map saved to {output_file}.")

if __name__ == "__main__":
    main()