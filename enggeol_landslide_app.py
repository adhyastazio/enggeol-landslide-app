import streamlit as st
import pandas as pd
import geopandas as gpd
import leafmap.foliumap as leafmap
import html
import hashlib
from shapely.geometry import Point
from google.oauth2 import service_account
from google.cloud import bigquery
from google.cloud import firestore
from google.cloud import storage
from PIL import Image
import base64
from io import BytesIO
import os
import re

# ---------------------
# Page Configuration
# ---------------------
st.set_page_config(
    page_title="Landslide Viewer - Jawa Barat",
    page_icon="🗻",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------
# Helper Functions
# ---------------------
def get_base64_of_bin_file(bin_file):
    """Convert binary file to base64 string"""
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def create_login_image_placeholder():
    """Display a custom image on the login screen."""
    image_path = "TimePhoto_20241107_120744.jpg"
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
        img_html = f'''<img src="data:image/jpeg;base64,{encoded}" 
                       style="width: 100%; 
                              height: 600px; 
                              object-fit: cover; 
                              border-radius: 12px; 
                              box-shadow: 0 8px 32px rgba(0,0,0,0.15);
                              margin-bottom: 20px;"/>'''
    else:
        img_html = """
        <div style="
            width: 100%;
            height: 200px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.15);
            margin-bottom: 20px;
        ">
            <span style="font-size: 64px; color: white;">🗻</span>
        </div>
        """
    return f"""
    <div style="text-align: center; margin-bottom: 30px;">
        {img_html}
        <h2 style="color: #333; margin-top: 20px; font-weight: 300;">Landslide Viewer</h2>
        <p style="color: #666; margin-bottom: 30px;">Sistem Informasi Longsor Jawa Barat</p>
    </div>
    """

# ---------------------
# Google Cloud Firestore for user database
# ---------------------
@st.cache_resource
def get_firestore_client():
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"]  
    )
    return firestore.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register():
    st.markdown(create_login_image_placeholder(), unsafe_allow_html=True)
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("### 📝 Daftar Akun Baru")
            new_user = st.text_input("Username baru", placeholder="Masukkan username")
            new_pass = st.text_input("Password", type="password", placeholder="Masukkan password")
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Daftar", use_container_width=True):
                    if new_user and new_pass:
                        db = get_firestore_client()
                        users_ref = db.collection("users")
                        if users_ref.document(new_user).get().exists:
                            st.warning("Username sudah digunakan.")
                        else:
                            users_ref.document(new_user).set({
                                "password": hash_password(new_pass),
                                "role": "viewer"
                            })
                            st.success("Registrasi berhasil! Silakan login.")
                            st.session_state.page = "login"
                            st.rerun()
                    else:
                        st.error("Username dan password harus diisi!")
            with col_btn2:
                if st.button("Kembali ke Login", use_container_width=True):
                    st.session_state.page = "login"
                    st.rerun()

def login():
    st.markdown(create_login_image_placeholder(), unsafe_allow_html=True)
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("### 🔐 Login")
            username = st.text_input("Username", placeholder="Masukkan username")
            password = st.text_input("Password", type="password", placeholder="Masukkan password")
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Login", use_container_width=True):
                    if username and password:
                        db = get_firestore_client()
                        users_ref = db.collection("users")
                        user_doc = users_ref.document(username).get()
                        if user_doc.exists and user_doc.to_dict().get("password") == hash_password(password):
                            st.session_state.logged_in = True
                            st.session_state.username = username
                            st.session_state.role = user_doc.to_dict().get("role", "viewer")
                            st.rerun()
                        else:
                            st.error("Login gagal. Periksa kembali username atau password.")
                    else:
                        st.error("Username dan password harus diisi!")
            with col_btn2:
                if st.button("Daftar Akun Baru", use_container_width=True):
                    st.session_state.page = "register"
                    st.rerun()

# ---------------------
# Load data from BigQuery
# ---------------------
def dms_to_dd(dms_str):
    """
    Convert DMS string like '7°35\'9.81"S' or '108° 6\'16.38"E' to decimal degrees.
    """
    if pd.isna(dms_str) or not dms_str:
        return None
    dms_str = str(dms_str).strip()
    match = re.match(r'(\d+)[°\s]+(\d+)[\'′\s]+([\d.]+)["″]?\s*([NSEW])', dms_str)
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    dd = float(degrees) + float(minutes)/60 + float(seconds)/3600
    if direction in ['S', 'W']:
        dd *= -1
    return dd

@st.cache_data
def load_data_from_bigquery():
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]  
        )
        project_id = "enggeol-riset-kolaborasi"
        client = bigquery.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])
        query = """
        SELECT * FROM `enggeol-riset-kolaborasi.Longsoran.longsoran_jabar`
        """
        df = client.query(query).to_dataframe()
        df["Lattitute Decimals"] = df["Lattitute"].apply(dms_to_dd)
        df["Longitude Decimals"] = df["Longitude"].apply(dms_to_dd)
        return df
    except Exception as e:
        st.error(f"Error loading data from BigQuery: {e}")
        return pd.DataFrame()

@st.cache_data
def load_boundaries():
    try:
        gdf = gpd.read_file("Jabar_By_Kec.geojson") 
        return gdf
    except Exception as e:
        st.error(f"Error loading boundary data: {e}")
        return gpd.GeoDataFrame()

# ---------------------
# Sidebar Functions
# ---------------------
def create_sidebar():
    with st.sidebar:
        # User Profile Section
        st.markdown("### Profil Pengguna")
        with st.container():
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown("""
                <div style="
                    width: 50px;
                    height: 50px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-bottom: 10px;
                ">
                    <span style="color: white; font-size: 20px;">👤</span>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                st.write(f"**{st.session_state.username}**")
                if st.button("Logout", key="logout_btn"):
                    st.session_state.logged_in = False
                    st.session_state.username = None
                    st.session_state.role = None
                    st.rerun()
        st.divider()
        # Map Controls Section
        st.markdown("### 🗺️ Kontrol Peta")
        display_mode = st.selectbox(
            "Tampilan Data",
            ["Marker", "Point", "Heatmap"],
            help="Pilih cara menampilkan data longsor di peta"
        )
        base_layer = st.selectbox(
            "Tipe Basemap",
            ["OpenStreetMap", "Satellite", "Terrain", "Kontur"],
            help="Pilih jenis peta dasar"
        )
        st.markdown("**Layer Options:**")
        show_boundaries = st.checkbox("Tampilkan Batas Wilayah", value=True)
        show_labels = st.checkbox("Tampilkan Label", value=False)
        st.divider()
        st.markdown("### 📊 Statistik")
        return display_mode, base_layer, show_boundaries, show_labels

# ---------------------
# Initialize session state
# ---------------------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'page' not in st.session_state:
    st.session_state.page = "login"
if 'role' not in st.session_state:
    st.session_state.role = None

# ---------------------
# Authentication Check
# ---------------------
if not st.session_state.logged_in:
    if st.session_state.page == "login":
        login()
    else:
        register()
    st.stop()

# ---------------------
# Main App
# ---------------------
st.title("🗻 Landslide Viewer - Jawa Barat")

# Create sidebar and get controls
display_mode, base_layer, show_boundaries, show_labels = create_sidebar()

# Load data
df = load_data_from_bigquery()
gdf = load_boundaries()

if df.empty or gdf.empty:
    st.error("Could not load required data. Please check your configuration.")
    st.stop()

df.columns = df.columns.str.strip()

# Main content area
col_main, col_filters = st.columns([3, 1])

with col_main:
    # Filter wilayah
    regency_col = "Regency_City"
    district_col_df = "District"
    district_col_gdf = "KECAMATAN"
    boundary_col = "KABKOT"
    df[regency_col] = df[regency_col].astype(str).str.lower()
    df[district_col_df] = df[district_col_df].astype(str).str.lower()
    gdf[boundary_col] = gdf[boundary_col].astype(str).str.lower()
    gdf[district_col_gdf] = gdf[district_col_gdf].astype(str).str.lower()

    col1, col2 = st.columns(2)
    with col1:
        selected_region = st.selectbox("Pilih Kabupaten/Kota", ["Semua"] + sorted(gdf[boundary_col].unique()))
    
    # Konversi df ke GeoDataFrame
    df = df.dropna(subset=["Lattitute Decimals", "Longitude Decimals"])
    df["Latitude Decimals"] = pd.to_numeric(df["Lattitute Decimals"], errors="coerce")
    df["Longitude Decimals"] = pd.to_numeric(df["Longitude Decimals"], errors="coerce")
    gdf_points = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["Longitude Decimals"], df["Latitude Decimals"]), crs="EPSG:4326")

    if selected_region != "Semua":
        selected_boundary = gdf[gdf[boundary_col] == selected_region.lower()]
        filtered_gdf = gpd.sjoin(gdf_points, selected_boundary, how="inner", predicate="within")
        boundary = selected_boundary
    else:
        filtered_gdf = gdf_points.copy()
        boundary = gdf.copy()

    # District selectbox setelah kota/kabupaten
    available_districts = filtered_gdf[district_col_df].dropna().unique()
    with col2:
        selected_district = st.selectbox("Pilih Kecamatan", ["Semua"] + sorted(available_districts))
    
    if selected_district != "Semua":
        filtered_gdf = filtered_gdf[filtered_gdf[district_col_df] == selected_district.lower()]
        boundary = gdf[
            (gdf[boundary_col] == selected_region.lower()) &
            (gdf[district_col_gdf] == selected_district.lower())
        ]

    # Map setup
    basemap_dict = {
        "OpenStreetMap": "OpenStreetMap",
        "Satellite": "HYBRID",
        "Terrain": "TERRAIN",
        "Kontur": "Esri.WorldTopoMap"
    }

    # Create map
    m = leafmap.Map(center=[-7.1, 107.6], zoom=8)
    m.add_basemap(basemap_dict[base_layer])
    
    if show_boundaries:
        m.add_gdf(boundary, layer_name="Batas Wilayah")

    # Add data based on display mode
    if display_mode == "Marker":
        for _, row in filtered_gdf.iterrows():
            popup_html = "<b><u>Informasi Longsoran</u></b><br>"
            for col in filtered_gdf.columns:
                if col not in ['Latitude Decimals', 'Longitude Decimals', 'geometry']:
                    val = row[col]
                    val_str = '-' if pd.isna(val) else html.escape(str(val))
                    popup_html += f"<b>{html.escape(col)}:</b> {val_str}<br>"
            m.add_marker(
                location=[row['Latitude Decimals'], row['Longitude Decimals']],
                popup=popup_html,
                icon=leafmap.folium.Icon(icon='map-marker', color='red')
            )

    elif display_mode == "Point":
        m.add_points_from_xy(
            filtered_gdf,
            x="Longitude Decimals",
            y="Latitude Decimals",
            layer_name="Landslide Points"
        )

    elif display_mode == "Heatmap":
        if not filtered_gdf.empty:
            heatmap_data = filtered_gdf[['Latitude Decimals', 'Longitude Decimals']].copy()
            heatmap_data['value'] = 1
            m.add_heatmap(
                data=heatmap_data,
                latitude='Latitude Decimals',
                longitude='Longitude Decimals',
                value='value',
                radius=15
            )

    # Display map
    m.to_streamlit(height=600)

# Advanced Filters Section (below map)
st.markdown("---")
with st.expander("🔧 Advanced Filters", expanded=False):
    st.markdown("**Filter Data Berdasarkan Parameter Numerik:**")
    numeric_filters = [
        "Landslide Length (m)",
        "Landslide Width (m)",
        "Landslide Height (m)",
        "Elevation (m)",
        "Slope Angle (°)"
    ]
    cols = st.columns(2)
    for i, col in enumerate(numeric_filters):
        if col in filtered_gdf.columns:
            filtered_gdf[col] = pd.to_numeric(filtered_gdf[col], errors="coerce")
            if not filtered_gdf[col].dropna().empty:
                min_val = int(filtered_gdf[col].min(skipna=True))
                max_val = int(filtered_gdf[col].max(skipna=True))
                with cols[i % 2]:
                    val_range = st.slider(
                        f"**{col}**", 
                        min_val, 
                        max_val, 
                        (min_val, max_val),
                        key=f"filter_{col}"
                    )
                    filtered_gdf = filtered_gdf[filtered_gdf[col].between(val_range[0], val_range[1])]

# Update sidebar statistics
with st.sidebar:
    if 'filtered_gdf' in locals():
        st.metric("Total Data Points", len(filtered_gdf))
        if not filtered_gdf.empty:
            st.metric("Wilayah Terpilih", selected_region if selected_region != "Semua" else "Seluruh Jawa Barat")
            if "Elevation (m)" in filtered_gdf.columns:
                avg_elevation = filtered_gdf["Elevation (m)"].mean()
                if not pd.isna(avg_elevation):
                    st.metric("Rata-rata Elevasi (m)", f"{avg_elevation:.1f}")

# ---------------------
# Editor Panel (for editor role)
# ---------------------
@st.cache_data(show_spinner=False)
def get_last_50_landslides():
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]
        )
        client = bigquery.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])
        query = "SELECT `L-ID`, Regency_City, District, Village, Lattitute, Longitude, Date FROM `enggeol-riset-kolaborasi.Longsoran.longsoran_jabar` ORDER BY Date DESC LIMIT 50"
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Error loading landslide data: {e}")
        return pd.DataFrame()

def upload_landslide_pic_to_gcs(filename, uploaded_file):
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]
        )
        bucket_name = "enggeol-landslide-pics"
        storage_client = storage.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(f"landslide_pics/{filename}.jpg")
        uploaded_file.seek(0)  # Reset file pointer
        blob.upload_from_file(uploaded_file, content_type=uploaded_file.type)
        blob.make_public()
        return blob.public_url
    except Exception as e:
        st.error(f"Error uploading image: {e}")
        return None

# Role-based mode selection
if st.session_state.role == "editor":
    page = st.sidebar.radio("Mode", ["Viewer", "Editor"], label_visibility="visible")
else:
    page = "Viewer"

if page == "Editor":
    st.markdown("## ✏️ Editor Panel")
    st.markdown("Tambah atau hapus data longsor di sini.")

    # Add new landslide data
    with st.form(key="add_landslide_form"):
        st.write("### Tambah Data Longsor Baru")
        regency = st.text_input("Kabupaten/Kota", key="editor_regency")
        district = st.text_input("Kecamatan", key="editor_district")
        village = st.text_input("Desa", key="editor_village")
        latitude = st.text_input("Latitude (DMS format)", help="Contoh: 7°35'9.81\"S", key="editor_latitude")
        longitude = st.text_input("Longitude (DMS format)", help="Contoh: 108° 6'16.38\"E", key="editor_longitude")
        elevation = st.number_input("Elevation _m_", value=0, key="editor_elevation")
        observed_lithology = st.text_input("Observed Lithology", key="editor_lithology")
        landslide_type = st.text_input("Landslide Type", key="editor_type")
        landslide_material = st.text_input("Landslide Material", key="editor_material")
        landslide_length = st.text_input("Landslide Length _m_", key="editor_length")
        landslide_width = st.text_input("Landslide Width _m_", key="editor_width")
        landslide_height = st.text_input("Landslide Height _m_", key="editor_height")
        landslide_date = st.text_input("Historical Landslide Date", key="editor_date")
        landslide_pic = st.file_uploader("Upload Foto Longsor", type=["jpg", "jpeg", "png"], key="editor_pic")
        additional_comments = st.text_area("Additional Comments", key="editor_comments")
        submit_btn = st.form_submit_button(label="Tambah Data")

        # Form submission logic INSIDE the form
        if submit_btn:
            # Validate required fields
            if not regency or not district or not village or not latitude or not longitude:
                st.error("Mohon isi semua field yang wajib (Kabupaten/Kota, Kecamatan, Desa, Latitude, Longitude)")
            else:
                try:
                    img_url = None
                    if landslide_pic:
                        img_url = upload_landslide_pic_to_gcs(
                            f"{regency}_{district}_{village}_{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}",
                            landslide_pic
                        )
                    
                    credentials = service_account.Credentials.from_service_account_info(
                        st.secrets["gcp_service_account"]
                    )
                    client = bigquery.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])
                    table_id = "enggeol-riset-kolaborasi.Longsoran.longsoran_jabar"
                    new_lid = f"L{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}"
                    
                    rows_to_insert = [{
                        "L-ID": new_lid,
                        "Regency_City": regency,
                        "District": district,
                        "Village": village,
                        "Lattitute": latitude,
                        "Longitude": longitude,
                        "Elevation _m_": elevation,
                        "Observed Lithology": observed_lithology,
                        "Landslide Type": landslide_type,
                        "Landslide Material": landslide_material,
                        "Landslide Length _m_": landslide_length,
                        "Landslide Width _m_": landslide_width,
                        "Landslide Height _m_": landslide_height,
                        "Historical Landslide Date": landslide_date,
                        "image_url": img_url,
                        "Additional Comments": additional_comments,
                        "Data Entry": st.session_state.username,
                        "Date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                    }]
                    
                    errors = client.insert_rows_json(table_id, rows_to_insert)
                    if errors == []:
                        st.success("Data longsor berhasil ditambahkan!")
                        st.cache_data.clear()  # Clear cache to show new data
                    else:
                        st.error(f"Gagal menambah data: {errors}")
                        
                except Exception as e:
                    st.error(f"Error submitting data: {e}")

    # Remove landslide data (show last 50 entries)
    st.write("### Hapus Data Longsor")
    df_editor = get_last_50_landslides()
    
    if not df_editor.empty:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]
        )
        client = bigquery.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])
        
        for idx, row in df_editor.iterrows():
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"{row['Regency_City']} - {row['District']} - {row['Village']} ({row['Lattitute']}, {row['Longitude']}) [{row['Date']}]")
            with col2:
                if st.button(f"Hapus", key=f"del_{row['L-ID']}"):
                    try:
                        delete_query = f"""
                        DELETE FROM `enggeol-riset-kolaborasi.Longsoran.longsoran_jabar`
                        WHERE `L-ID` = '{row['L-ID']}'
                        """
                        client.query(delete_query).result()
                        st.success("Data berhasil dihapus.")
                        st.cache_data.clear()  # Clear cache to reflect deletion
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting data: {e}")
    else:
        st.info("Tidak ada data untuk ditampilkan.")

    st.stop()

# CSS for better styling
st.markdown("""
<style>
    .stSelectbox > div > div > select {
        background-color: #f8f9fa;
    }
    .stExpander {
        border: 1px solid #e9ecef;
        border-radius: 0.5rem;
        margin-top: 1rem;
    }
    .metric-container {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)
