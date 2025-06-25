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
from PIL import Image
import base64
from io import BytesIO
import os

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
        # Fallback if image not found
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
                            users_ref.document(new_user).set({"password": hash_password(new_pass)})
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
@st.cache_data
def load_data_from_bigquery():
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"]  
    )
    project_id = "enggeol-riset-kolaborasi"
    client = bigquery.Client(credentials=credentials, project=st.secrets["gcp_service_account"]["project_id"])

    query = """
    SELECT * FROM `enggeol-riset-kolaborasi.Longsoran.longsoran_jabar`
    """
    df = client.query(query).to_dataframe()
    return df

def load_boundaries():
    gdf = gpd.read_file("Jabar_By_Kec.geojson") 
    return gdf

# ---------------------
# Sidebar Functions
# ---------------------
def create_sidebar():
    with st.sidebar:
        # User Profile Section
        st.markdown("### 👤 Profil Pengguna")
        with st.container():
            col1, col2 = st.columns([1, 2])
            with col1:
                # Profile picture placeholder
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
                    st.rerun()
        
        st.divider()
        
        # Map Controls Section
        st.markdown("### 🗺️ Kontrol Peta")
        
        # Display mode
        display_mode = st.selectbox(
            "Tampilan Data",
            ["Marker", "Point", "Heatmap"],
            help="Pilih cara menampilkan data longsor di peta"
        )
        # Base layer
        base_layer = st.selectbox(
            "Tipe Basemap",
            ["OpenStreetMap", "Satellite", "Terrain", "Kontur"],
            help="Pilih jenis peta dasar"
        )
        
        # Layer toggles
        st.markdown("**Layer Options:**")
        show_boundaries = st.checkbox("Tampilkan Batas Wilayah", value=True)
        show_labels = st.checkbox("Tampilkan Label", value=False)
        
        st.divider()
        
        # Statistics
        st.markdown("### 📊 Statistik")
        
        return display_mode, base_layer, show_boundaries, show_labels

# ---------------------
# Initialize session state
# ---------------------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'page' not in st.session_state:
    st.session_state.page = "login"

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
df.columns = df.columns.str.strip()

# Main content area
col_main, col_filters = st.columns([3, 1])

with col_main:
    # Filter wilayah
    regency_col = "Regency/City"
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
    df = df.dropna(subset=["Latitude Decimals", "Longitude Decimals"])
    df["Latitude Decimals"] = pd.to_numeric(df["Latitude Decimals"], errors="coerce")
    df["Longitude Decimals"] = pd.to_numeric(df["Longitude Decimals"], errors="coerce")
    df = df.dropna(subset=["Latitude Decimals", "Longitude Decimals"])
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
    
    # Kolom numerik yang dapat difilter
    numeric_filters = [
        "Landslide Length (m)",
        "Landslide Width (m)",
        "Landslide Height (m)",
        "Elevation (m)",
        "Slope Angle (°)"
    ]
    
    # Create columns for filters
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
            
            # Additional statistics
            if "Elevation (m)" in filtered_gdf.columns:
                avg_elevation = filtered_gdf["Elevation (m)"].mean()
                if not pd.isna(avg_elevation):
                    st.metric("Rata-rata Elevasi (m)", f"{avg_elevation:.1f}")

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