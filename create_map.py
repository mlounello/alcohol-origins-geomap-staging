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
    # Match '#### BCE' or '#### CE'
    m = re.match(r"(\d+)\s*(BCE|CE)$", date_str)
    if m:
        year = int(m.group(1))
        era = m.group(2)
        return -year if era == "BCE" else year

    # Match '(\d+)(st|nd|rd|th) century (BCE|CE)'
    m2 = re.match(r"(\d+)(?:st|nd|rd|th)\s+century\s*(BCE|CE)$", date_str)
    if m2:
        century = int(m2.group(1))
        era = m2.group(2)
        # approximate midpoint of that century: (century*100 - 50)
        mid = (century * 100) - 50
        return -mid if era == "BCE" else mid

    # Match just a year without era (assume CE)
    m3 = re.match(r"(\d{3,4})$", date_str)
    if m3:
        return int(m3.group(1))

    # If nothing matches, return 0
    return 0

def compute_radius(year: int) -> int:
    """
    Given a numeric year (BCE negative, CE positive), return a reasonable circle radius.
    Older (more negative) origins → larger radius. Newer → smaller radius.
    We'll clamp between 4 and 12.
    """
    if year == 0:
        return 5  # default radius if unknown

    # Map year range roughly from -5000 → 2000 into radius range 12 → 4
    # linear interpolation: r = m * year + b, but flipped because BCE negative
    # For year = -5000 → want radius ~12; year = 2000 → radius ~4
    m = (4 - 12) / (2000 - (-5000))  # slope
    b = 12 - (m * -5000)
    r = m * year + b
    return int(max(4, min(12, r)))

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
    Also compute numeric 'year' and 'radius' columns for each row.
    """
    # Convert lat/long to numeric
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)

    # Compute 'year' and 'radius'
    df["year"] = df["date"].apply(parse_year)
    df["radius"] = df["year"].apply(compute_radius)

    return df

def add_parent_child_lines(m: folium.Map, df: pd.DataFrame) -> None:
    """
    Draws a polyline between each child node and its parent node, if parent_id exists.
    """
    coords_lookup = {
        row["node_id"]: (row["latitude"], row["longitude"])
        for _, row in df.iterrows()
        if pd.notna(row["node_id"]) and row["node_id"] != ""
    }

    for _, row in df.iterrows():
        parent_id = row["parent_id"]
        child_id = row["node_id"]
        if pd.notna(parent_id) and parent_id != "":
            if parent_id not in coords_lookup:
                print(f"Warning: parent_id '{parent_id}' not found for child '{child_id}'.")
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
    Injects a simple HTML legend in the top-right corner with rounded corners
    and slight transparency.
    """
    legend_html = """
     <div style="
       position: fixed;
       top: 10px; right: 10px;
       width: 160px;
       background-color: rgba(255, 255, 255, 0.8);
       border:2px solid gray;
       border-radius: 8px;
       z-index:9999;
       font-size:14px;
       line-height:18px;
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
      • Color-coded CircleMarkers by group
      • Variable radius based on 'date'
      • Parent→child lines
      • A searchable GeoJSON layer for node_id
      • An enhanced legend
    """
    # 1) Define colors for each group
    group_color_map = {
        "Grain": "gold",
        "Grape": "purple",
        "Sugar": "saddlebrown",
        "Cactus": "green"
    }

    # 2) Compute map center
    center_lat = df["latitude"].mean()
    center_lon = df["longitude"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=2)

    # 3) Draw parent→child lines first
    add_parent_child_lines(m, df)

    # 4) Build a GeoJSON FeatureCollection so we can use the Search plugin
    features = []
    for _, row in df.iterrows():
        # Prepare properties for popup and styling
        props = {
            "node_id": row["node_id"],
            "type": row["type"],
            "group": row["group"],
            "date": row["date"],
            "description": row["description"],
            "citation": row["citation"],
            "color": group_color_map.get(row["group"], "blue"),
            "radius": row["radius"]
        }
        feature = {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Point",
                "coordinates": [float(row["longitude"]), float(row["latitude"])]
            }
        }
        features.append(feature)

    geojson_data = {
        "type": "FeatureCollection",
        "features": features
    }

    # 5) Add the GeoJSON layer with CircleMarker styling via point_to_layer
    def style_function(feature):
        # Not used for CircleMarker, kept if needed for polygons
        return {}

    def point_to_layer(feature, latlng):
        return folium.CircleMarker(
            location=latlng,
            radius=feature["properties"]["radius"],
            color=feature["properties"]["color"],
            fill=True,
            fill_color=feature["properties"]["color"],
            fill_opacity=0.7,
            popup=folium.Popup(
                f"<strong>{feature['properties']['node_id']}</strong><br>"
                f"Type: {feature['properties']['type']}<br>"
                f"Group: {feature['properties']['group']}<br>"
                f"Date: {feature['properties']['date']}<br>"
                f"Description: {feature['properties']['description']}<br>"
                f"Citation: {feature['properties']['citation']}",
                max_width=300
            )
        )

    geojson_layer = folium.GeoJson(
        data=geojson_data,
        name="All Nodes",
        style_function=style_function,
        point_to_layer=point_to_layer,
        tooltip=folium.GeoJsonTooltip(fields=["node_id"], aliases=["Node ID:"])
    )
    geojson_layer.add_to(m)

    # 6) Add the Search box, searching by node_id
    Search(
        layer=geojson_layer,
        search_label="node_id",
        placeholder="Search Node ID...",
        collapsed=False
    ).add_to(m)

    # 7) Inject the enhanced legend
    add_legend(m, group_color_map)

    return m

def main():
    SHEET_ID = "1obKjWhdnJhK3f6qImN0DrQJEBZP-YigvjrU128QkjMM"
    WORKSHEET = "Sheet1"

    # Load and prepare
    df = load_sheet_to_df(SHEET_ID, WORKSHEET)
    print("✅ Loaded sheet. Preparing DataFrame…")
    df = prepare_dataframe(df)
    print(f"✅ DataFrame ready: {len(df)} valid points.")

    # Create map with all features
    fmap = create_folium_map(df)
    print("✅ Map with variable radii, search box, lines, and legend created.")

    # Save to docs/index.html
    output_file = "docs/index.html"
    fmap.save(output_file)
    print(f"✅ Map saved to {output_file}.")

if __name__ == "__main__":
    main()