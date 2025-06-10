# create_map.py

import pandas as pd
import folium
from folium.plugins import Search
import gspread
from google.oauth2.service_account import Credentials
import sys
import re

def parse_year(date_str: str) -> int:
    """
    Convert a date like '3500 BCE', '16th century CE', or '1840 CE' into
    an approximate numeric year: BCE → negative, CE → positive, century → midpoint.
    If parsing fails, return 0 (so radius fallback works).
    """
    date_str = date_str.strip()
    m = re.match(r"(\d+)\s*(BCE|CE)$", date_str)
    if m:
        year = int(m.group(1))
        era = m.group(2)
        return -year if era == "BCE" else year

    m2 = re.match(r"(\d+)(?:st|nd|rd|th)\s+century\s*(BCE|CE)$", date_str)
    if m2:
        century = int(m2.group(1))
        era = m2.group(2)
        mid = (century * 100) - 50
        return -mid if era == "BCE" else mid

    m3 = re.match(r"(\d{3,4})$", date_str)
    if m3:
        return int(m3.group(1))

    return 0

def compute_radius(year: int) -> int:
    """
    Given a numeric year (BCE negative, CE positive), return a reasonable circle radius.
    Older (more negative) origins → larger radius. Newer → smaller radius.
    We'll clamp between 4 and 12.
    """
    if year == 0:
        return 5

    m = (4 - 12) / (2000 - (-5000))  # slope
    b = 12 - (m * -5000)
    r = m * year + b
    return int(max(4, min(12, r)))

def load_sheet_to_df(sheet_id: str, worksheet_name: str = "Data") -> pd.DataFrame:
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
    Also compute numeric 'year' and 'radius' columns for each row.
    """
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)

    df["year"] = df["date"].apply(parse_year)
    df["radius"] = df["year"].apply(compute_radius)

    return df

def add_parent_child_lines(m: folium.Map, df: pd.DataFrame, group_color_map: dict) -> None:
    """
    Draws a polyline between each child node and its parent node,
    coloring the line to match the child's group color.
    """
    # Build lookup of node_id → (lat, lon)
    coords = {
        row["node_id"]: (row["latitude"], row["longitude"])
        for _, row in df.iterrows()
        if row["node_id"]
    }

    for _, row in df.iterrows():
        pid = row["parent_id"]
        if pid and pid in coords:
            parent_loc = coords[pid]
            child_loc  = (row["latitude"], row["longitude"])
            # Use the child's group color, defaulting to gray
            color = group_color_map.get(row["group"], "gray")
            folium.PolyLine(
                locations=[parent_loc, child_loc],
                color=color,
                weight=2,
                opacity=0.6
            ).add_to(m)

def add_legend(m: folium.Map, group_color_map: dict) -> None:
    """
    Injects a simple HTML legend in the bottom-right corner with rounded corners
    and slight transparency.
    """
    legend_html = """
     <div style="
       position: fixed;
       bottom: 10px; right: 10px;
       width: 160px;
       background-color: rgba(255, 255, 255, 0.8);
       border: 2px solid gray;
       border-radius: 8px;
       z-index: 9999;
       font-size: 14px;
       line-height: 18px;
       padding: 8px;
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
    Creates a Folium map with:
      • English-labeled Street base,
      • Satellite & Hybrid options,
      • Color-coded CircleMarkers by group,
      • Variable radius based on 'date',
      • Parent→child lines,
      • An enhanced legend.
    """
    group_color_map = {
        "Grain":   "#f9d81b",
        "Grape":   "#75147c",
        "Sugar":   "#FFFFFF",     
        "Cactus":  "#367c21",
        "Spice":   "#8B4513",     
        "Floral":  "#FFC0CB",     
        "Roots":   "#B22222"      
    }

    center_lat = df["latitude"].mean()
    center_lon = df["longitude"].mean()

    # 1) Initialize empty map (no default tiles)
    m = folium.Map(location=[center_lat, center_lon], zoom_start=2, tiles=None)

    # 2) Add an English-labeled “Street” layer (CartoDB Positron) with attribution
    folium.TileLayer(
        tiles='CartoDB positron',
        attr='CartoDB',
        name='Street (English)',
        control=True
    ).add_to(m)

    # 3) Add pure Satellite imagery (ESRI) with proper attribution
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite',
        control=True
    ).add_to(m)

    # 4) Add a “labels only” overlay to create Hybrid (with proper attr)
    folium.TileLayer(
        tiles='https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Hybrid (Satellite + Labels)',
        overlay=True,
        control=True
    ).add_to(m)

    # 5) Draw parent→child lines first (so markers sit on top)
    add_parent_child_lines(m, df, group_color_map)

    # 6) Add individual CircleMarkers (with radius); remove any “pins”
    for _, row in df.iterrows():
        color = group_color_map.get(row["group"], "blue")
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=row["radius"],
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(
                f"<strong>{row['node_id']}</strong><br>"
                f"Type: {row['type']}<br>"
                f"Group: {row['group']}<br>"
                f"Date: {row['date']}<br>"
                f"Description: {row['description']}<br>"
                f"Citation: {row['citation']}",
                max_width=300
            )
        ).add_to(m)

    # 7) Inject the enhanced legend (bottom-right)
    add_legend(m, group_color_map)

    # 8) Finally, add the LayerControl so users can switch among tiles
    folium.LayerControl(position='bottomleft', collapsed=False).add_to(m)

    return m

def main():
    SHEET_ID = "1obKjWhdnJhK3f6qImN0DrQJEBZP-YigvjrU128QkjMM"
    WORKSHEET = "Data"

    df = load_sheet_to_df(SHEET_ID, WORKSHEET)
    print("✅ Loaded sheet. Preparing DataFrame…")
    df = prepare_dataframe(df)
    print(f"✅ DataFrame ready: {len(df)} valid points.")

    fmap = create_folium_map(df)
    print("✅ Map with tile layers, variable radii, lines, and legend created.")

    output_file = "docs/index.html"
    fmap.save(output_file)
    print(f"✅ Map saved to {output_file}.")

if __name__ == "__main__":
    main()