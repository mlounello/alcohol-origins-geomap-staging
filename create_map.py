# create_map.py

import pandas as pd
import folium
import gspread
from google.oauth2.service_account import Credentials
import sys
import re

def parse_year(date_str: str) -> int:
    """
    Convert a date like '3500 BCE', '16th century CE', or '1840 CE' into
    an approximate numeric year: BCE → negative, CE → positive, century → midpoint.
    If parsing fails, return 0.
    """
    date_str = date_str.strip()
    m = re.match(r"(\d+)\s*(BCE|CE)$", date_str)
    if m:
        year, era = int(m.group(1)), m.group(2)
        return -year if era == "BCE" else year
    m2 = re.match(r"(\d+)(?:st|nd|rd|th)\s+century\s*(BCE|CE)$", date_str)
    if m2:
        century, era = int(m2.group(1)), m2.group(2)
        mid = century * 100 - 50
        return -mid if era == "BCE" else mid
    m3 = re.match(r"(\d{3,4})$", date_str)
    if m3:
        return int(m3.group(1))
    return 0

def compute_radius(year: int) -> int:
    """
    Map year range -5000→2000 into radius 12→4, clamp 4–12.
    """
    if year == 0:
        return 5
    m = (4 - 12) / (2000 - (-5000))
    b = 12 - m * -5000
    r = m * year + b
    return int(max(4, min(12, r)))

def load_sheet_to_df(sheet_id: str, worksheet_name: str = "Data") -> pd.DataFrame:
    """
    Authenticate and load Google Sheet into a DataFrame.
    """
    SERVICE_ACCOUNT_FILE = "alcohol-origins-geomap-cd20d437877f.json"
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    except FileNotFoundError:
        print(f"ERROR: Could not find {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)
    client = gspread.authorize(creds)
    try:
        sheet = client.open_by_key(sheet_id)
    except Exception as e:
        print(f"ERROR: Could not open sheet: {e}")
        sys.exit(1)
    try:
        worksheet = sheet.worksheet(worksheet_name)
    except Exception:
        print(f"ERROR: Worksheet named '{worksheet_name}' not found.")
        sys.exit(1)
    data = worksheet.get_all_values()
    if not data or len(data) < 2:
        print("ERROR: No data rows found in worksheet.")
        sys.exit(1)
    headers, rows = data[0], data[1:]
    return pd.DataFrame(rows, columns=headers)

def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean lat/lon and compute 'year' and 'radius'.
    """
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    df["year"] = df["date"].apply(parse_year)
    df["radius"] = df["year"].apply(compute_radius)
    return df

def add_parent_child_lines(m: folium.Map, df: pd.DataFrame, color_map: dict) -> None:
    """
    Draw lines colored by child group.
    """
    coords = {row["node_id"]:(row["latitude"],row["longitude"])
              for _, row in df.iterrows() if row["node_id"]}
    for _, row in df.iterrows():
        pid = row["parent_id"]
        if pid in coords:
            folium.PolyLine(
                locations=[coords[pid], (row["latitude"], row["longitude"])],
                color=color_map.get(row["group"], "gray"),
                weight=5, opacity=0.6
            ).add_to(m)

def add_legend(m: folium.Map, color_map: dict) -> None:
    """
    Static legend container bottom-right.
    """
    html = """
    <div id="legend" style="
      position: fixed;
      bottom: 10px; right: 10px;
      background: rgba(255,255,255,0.8);
      border:2px solid gray;
      border-radius:8px;
      padding:8px;
      font-size:14px;
      z-index:9999;
      box-shadow:3px 3px 6px rgba(0,0,0,0.2);
    ">
      <b>Groups</b><br>
    """
    for grp, col in color_map.items():
        html += f"""
        <div id="legend-{grp}">
          <i style="background:{col};width:12px;height:12px;display:inline-block;margin-right:6px;"></i>
          {grp}
        </div>
        """
    html += "</div>"
    m.get_root().html.add_child(folium.Element(html))

def create_folium_map(df: pd.DataFrame) -> folium.Map:
    """
    Folium map with:
      • English Street / Satellite / Hybrid base layers (radios)
      • One overlay per beverage group with color swatches in the LayerControl
      • Parent→child lines & circles colored by group
      • LayerControl in bottom-left
    """
    # 1) Define colors
    group_color_map = {
        "Grain":  "#f9d81b",
        "Grape":  "#75147c",
        "Sugar":  "#FFFFFF",
        "Cactus": "#367c21",
        #"Spice":  "#8B4513",
        #"Floral": "#FFC0CB",
        #"Roots":  "#B22222",
    }

    # 2) Center map
    center = [df["latitude"].mean(), df["longitude"].mean()]
    m = folium.Map(location=center, zoom_start=2, tiles=None)

    # 3) Base layer: Street
    folium.TileLayer(
        'CartoDB positron',
        attr='CartoDB',
        name='Street (English)',
        overlay=False,
        control=True
    ).add_to(m)

    # 4) Base layer: Satellite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite',
        overlay=False,
        control=True
    ).add_to(m)

    # 5) Base layer: Hybrid (imagery + labels) via a FeatureGroup
    hybrid_fg = folium.FeatureGroup(name='Hybrid (Satellite + Labels)', overlay=False, control=True)
    hybrid_fg.add_to(m)
    # Imagery
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        overlay=False,
        control=False
    ).add_to(hybrid_fg)
    # Labels overlay
    folium.TileLayer(
        tiles='https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        overlay=False,
        control=False
    ).add_to(hybrid_fg)

    # 6) Overlays: one FeatureGroup per beverage group
    group_fgs = {}
    for grp, color in group_color_map.items():
        # Embed color swatch HTML in the name
        name_html = (
            f'<span style="background:{color};'
            'width:12px;height:12px;display:inline-block;'
            'margin-right:6px;border:1px solid #000;"></span>'
            f'{grp}'
        )
        fg = folium.FeatureGroup(name=name_html, show=True)
        fg.add_to(m)
        group_fgs[grp] = fg

    # 7) Draw lines & circles into each group
    coords = {r["node_id"]:(r["latitude"],r["longitude"]) for _,r in df.iterrows() if r["node_id"]}
    for _, row in df.iterrows():
        grp = row["group"]
        fg = group_fgs.get(grp)
        if not fg:
            continue
        pid = row["parent_id"]
        if pid in coords:
            folium.PolyLine(
                locations=[coords[pid], (row["latitude"], row["longitude"])],
                color=group_color_map[grp],
                weight=6, opacity=25
            ).add_to(fg)
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=row["radius"],
            color=group_color_map[grp],
            fill=True, fill_color=group_color_map[grp], fill_opacity=0.7,
            popup=folium.Popup(
                f"<strong>{row['node_id']}</strong><br>"
                f"{row['type']} / {row['group']} / {row['date']}<br>"
                f"{row['description']}<br>{row['citation']}",
                max_width=300
            )
        ).add_to(fg)

    # 8) Add LayerControl for all layers (base radios + group checkboxes)
    folium.LayerControl(position='bottomleft', collapsed=False).add_to(m)

    return m

def main():
    SHEET_ID = "1obKjWhdnJhK3f6qImN0DrQJEBZP-YigvjrU128QkjMM"
    WORKSHEET = "Data"

    df = load_sheet_to_df(SHEET_ID, WORKSHEET)
    print(f"✅ Loaded {len(df)} rows.")
    df = prepare_dataframe(df)
    print(f"✅ Prepared {len(df)} valid points.")
    fmap = create_folium_map(df)
    fmap.save("docs/index.html")
    print("✅ Map saved to docs/index.html.")

if __name__ == "__main__":
    main()