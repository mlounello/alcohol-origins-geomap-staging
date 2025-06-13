# create_map.py

import os
import pandas as pd
import folium
from folium.plugins import Search
import gspread
from google.oauth2.service_account import Credentials
import sys
import re

def parse_year(date_str: str) -> int:
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
    if year == 0:
        return 5
    m = (4 - 12) / (2000 - (-5000))
    b = 12 - m * -5000
    r = m * year + b
    return int(max(4, min(12, r)))

def load_sheet_to_df(sheet_id: str, worksheet_name: str = "Data") -> pd.DataFrame:
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
    df["latitude"]  = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    df["year"]   = df["date"].apply(parse_year)
    df["radius"] = df["year"].apply(compute_radius)
    return df

def create_folium_map(df: pd.DataFrame) -> folium.Map:
    # 1) Colors
    group_color_map = {
        "Grain":  "#f9d81b",
        "Grape":  "#75147c",
        "Sugar":  "#FFFFFF",
        "Cactus": "#367c21",
    }

    # 2) Base map
    center = [df["latitude"].mean(), df["longitude"].mean()]
    m = folium.Map(location=center, zoom_start=2, tiles=None)

    # 3) Base layers
    folium.TileLayer("CartoDB positron", attr="CartoDB",
                     name="Street (English)", overlay=False, control=True).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite", overlay=False, control=True
    ).add_to(m)
    hybrid_fg = folium.FeatureGroup(
        name="Hybrid (Satellite + Labels)", overlay=False, control=True
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", overlay=False, control=False
    ).add_to(hybrid_fg)
    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", overlay=False, control=False
    ).add_to(hybrid_fg)

    # 4) One FeatureGroup per beverage group
    group_fgs = {}
    for grp, color in group_color_map.items():
        name_html = (
            f'<span style="background:{color};width:12px;height:12px;'
            'display:inline-block;margin-right:6px;border:1px solid #000;"></span>'
            f'{grp}'
        )
        fg = folium.FeatureGroup(name=name_html, show=True).add_to(m)
        group_fgs[grp] = fg

    # 5) Draw lines & circles in each FG
    coords = {
        r["node_id"]:(r["latitude"],r["longitude"])
        for _,r in df.iterrows() if r["node_id"]
    }
    for _, row in df.iterrows():
        grp = row["group"]
        fg  = group_fgs.get(grp)
        if not fg:
            continue
        pid = row["parent_id"]
        if pid in coords:
            folium.PolyLine(
                locations=[coords[pid], (row["latitude"], row["longitude"])],
                color=group_color_map[grp], weight=2, opacity=0.6
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

    # 6) LayerControl
    folium.LayerControl(position='bottomleft', collapsed=False).add_to(m)

    # 7) Filter sidebar HTML (top-left)
    checkbox_html = "\n".join(
        f'<input type="checkbox" class="filter-group" value="{grp}" checked> {grp}<br>'
        for grp in group_color_map
    )
    sidebar_html = f"""
    <div id="filter-sidebar" style="
      position: fixed; top: 50px; left: 10px;
      background: white; padding: 10px;
      box-shadow: 2px 2px 6px rgba(0,0,0,0.3);
      z-index: 9999; width: 180px;
    ">
      <h4>Filters</h4>
      <b>Group</b><br>
      {checkbox_html}
      <hr>
      <b>Year Range</b><br>
      <input id="year-min" type="number" value="-5000" style="width:70px;"> to
      <input id="year-max" type="number" value="2000" style="width:70px;"><br>
      <button id="apply-filters">Apply Filters</button>
    </div>
    """
    m.get_root().html.add_child(folium.Element(sidebar_html))

    # 8) New filter script: scan all overlayPane layers by name
    filter_script = """
    <script>
      function applyFilters() {
        // which groups are checked?
        var checked = Array.from(
          document.querySelectorAll('.filter-group:checked')
        ).map(c=>c.value);

        map.eachLayer(function(layer){
          // only consider overlayPane feature groups
          if (layer.options && layer.options.pane === 'overlayPane' && layer.options.name) {
            // strip any HTML tags from the name
            var raw = layer.options.name.replace(/<[^>]*>/g,'');
            if (checked.includes(raw)) {
              if (!map.hasLayer(layer)) map.addLayer(layer);
            } else {
              if (map.hasLayer(layer)) map.removeLayer(layer);
            }
          }
        });
      }
      document.getElementById('apply-filters').onclick = applyFilters;
    </script>
    """
    m.get_root().html.add_child(folium.Element(filter_script))

    return m

def main():
    SHEET_ID   = "1obKjWhdnJhK3f6qImN0DrQJEBZP-YigvjrU128QkjMM"
    WORKSHEET  = "Data"

    df = load_sheet_to_df(SHEET_ID, WORKSHEET)
    print(f"✅ Loaded {len(df)} rows.")
    df = prepare_dataframe(df)
    print(f"✅ Prepared {len(df)} valid points.")

    fmap = create_folium_map(df)

    output_file = "docs/index.html"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    fmap.save(output_file)
    print(f"✅ Map saved to {output_file}.")

if __name__ == "__main__":
    main()