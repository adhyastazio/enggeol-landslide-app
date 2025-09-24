# streamlit_app.py
import streamlit as st
import pandas as pd
import geopandas as gpd
import leafmap.foliumap as leafmap
import html
import hashlib
import json
import uuid
import re
from datetime import datetime, date
from io import BytesIO
from PIL import Image
from google.oauth2 import service_account
from google.cloud import bigquery, firestore, storage
from shapely.geometry import Point
import base64
import os

# ---------------------
# Config / Constants
# ---------------------
# <-- UBAHAN: Mengadopsi format nama yang lebih eksplisit dan bersih dari kode baru.
PROJECT_ID = st.secrets["gcp_service_account"]["project_id"]
BQ_DATASET = "Longsoran" 
BQ_TABLE_NAME = "longsoran_jabar" 
BQ_TABLE = f"{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE_NAME}"
GCS_BUCKET = "enggeol-landslide-pics"
FIRESTORE_COLLECTION = "landslide_data"
PAGE_SIZE = 50

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
# Basic helpers & UI placeholders
# ---------------------
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        return base64.b64encode(f.read()).decode()

def create_login_image_placeholder():
    image_path = "TimePhoto_20241107_120744.jpg"
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
        img_html = f'''<img src="data:image/jpeg;base64,{encoded}" style="width:100%; height:600px; object-fit:cover; border-radius:12px; box-shadow:0 8px 32px rgba(0,0,0,0.15); margin-bottom:20px;" />'''
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
    <div style="text-align:center; margin-bottom:30px;">
        {img_html}
        <h2 style="color:#333; margin-top:20px; font-weight:300;">Landslide Viewer</h2>
        <p style="color:#666; margin-bottom:30px;">Sistem Informasi Longsor Jawa Barat</p>
    </div>
    """

# ---------------------
# GCP clients (cached) - (MEMPERTAHANKAN metode ini, karena lebih baik)
# ---------------------
@st.cache_resource
def get_credentials():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return creds

@st.cache_resource
def get_firestore_client_cached():
    creds = get_credentials()
    return firestore.Client(credentials=creds, project=PROJECT_ID)

@st.cache_resource
def get_bq_client_cached():
    creds = get_credentials()
    return bigquery.Client(credentials=creds, project=PROJECT_ID)

@st.cache_resource
def get_gcs_client_cached():
    creds = get_credentials()
    return storage.Client(credentials=creds, project=PROJECT_ID)

# ---------------------
# Utility functions
# ---------------------
def titlecase_column(s):
    if pd.isna(s) or s is None:
        return s
    return str(s).strip().title()

def dms_to_dd(dms_str):
    if pd.isna(dms_str) or not dms_str:
        return None
    s = str(dms_str).strip()
    # First, try to parse as a simple float
    try:
        return float(s)
    except ValueError:
        pass  # If it fails, continue to DMS parsing
    
    match = re.match(r'(\d+)[°\s]+(\d+)[\'′\s]+([\d.]+)["″]?\s*([NSEW])', s, re.IGNORECASE)
    if not match:
        return None
    
    degrees, minutes, seconds, direction = match.groups()
    dd = float(degrees) + float(minutes)/60 + float(seconds)/3600
    if direction.upper() in ['S', 'W']:
        dd *= -1
    return dd

# ---------------------
# GCS upload (resize + upload) - (MEMPERTAHANKAN metode ini, karena lebih baik)
# ---------------------
def upload_image_to_gcs_and_get_url(filename_noext, uploaded_file, bucket_name=GCS_BUCKET, resize_max=(1280,720)):
    try:
        storage_client = get_gcs_client_cached()
        bucket = storage_client.bucket(bucket_name)
        filename_safe = re.sub(r'[^A-Za-z0-9_\-\.]', '_', filename_noext)
        blob_path = f"landslide_pics/{filename_safe}.jpg"
        blob = bucket.blob(blob_path)

        uploaded_file.seek(0)
        img = Image.open(uploaded_file).convert("RGB")
        img.thumbnail(resize_max)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        buf.seek(0)

        blob.upload_from_file(buf, content_type="image/jpeg")

        try:
            blob.make_public()
            return blob.public_url
        except Exception:
            return f"gs://{bucket_name}/{blob_path}"
    except Exception as e:
        st.error(f"Error uploading image to GCS: {e}")
        return None

# ---------------------
# Firestore helpers (save, query, pagination)
# ---------------------
def save_entry_to_firestore(entry_dict, doc_id=None):
    db = get_firestore_client_cached()
    col = db.collection(FIRESTORE_COLLECTION)
    if doc_id:
        col.document(doc_id).set(entry_dict, merge=True)
        return doc_id
    else:
        # <-- UBAHAN: Menggunakan L-ID sebagai ID dokumen untuk konsistensi
        doc_ref = col.document(entry_dict["L-ID"])
        entry_dict["_created_at"] = firestore.SERVER_TIMESTAMP
        entry_dict["bigquery_synced"] = False
        doc_ref.set(entry_dict)
        return doc_ref.id

def get_recent_entries_from_firestore(limit=50):
    db = get_firestore_client_cached()
    docs = db.collection(FIRESTORE_COLLECTION).order_by("_created_at", direction=firestore.Query.DESCENDING).limit(limit).stream()
    rows = []
    for d in docs:
        dd = d.to_dict()
        dd["_doc_id"] = d.id
        for fld in ["Province", "Regency_City", "District", "Village"]:
            if fld in dd:
                dd[fld] = titlecase_column(dd[fld])
        rows.append(dd)
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def get_entries_paginated(page_number=0, page_size=PAGE_SIZE):
    db = get_firestore_client_cached()
    q = db.collection(FIRESTORE_COLLECTION).order_by("_created_at", direction=firestore.Query.DESCENDING).offset(page_number*page_size).limit(page_size)
    docs = list(q.stream())
    rows = []
    for d in docs:
        dd = d.to_dict()
        dd["_doc_id"] = d.id
        for fld in ["Province", "Regency_City", "District", "Village"]:
            if fld in dd:
                dd[fld] = titlecase_column(dd[fld])
        rows.append(dd)
    return pd.DataFrame(rows) if rows else pd.DataFrame()

# ---------------------
# Batch Sync Firestore -> BigQuery - (MEMPERTAHANKAN metode ini, karena jauh lebih efisien)
# ---------------------
def batch_sync_firestore_to_bigquery(dataset_table=BQ_TABLE):
    st.info("Starting batch sync to BigQuery...")
    db = get_firestore_client_cached()
    client = get_bq_client_cached()

    docs = list(db.collection(FIRESTORE_COLLECTION).where("bigquery_synced", "==", False).stream())
    if not docs:
        st.success("Tidak ada data baru untuk disinkronkan.")
        return

    table_ref = client.get_table(dataset_table)
    bq_fields = [f.name for f in table_ref.schema]

    ndjson_lines = []
    doc_id_map = []
    for d in docs:
        data = d.to_dict()
        data.pop("_created_at", None)
        data.pop("bigquery_synced", None)
        
        for k, v in list(data.items()):
            if isinstance(v, datetime) or isinstance(v, date):
                data[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        
        for fld in ["Regency_City", "District", "Village", "Province"]:
            if fld in data:
                data[fld] = titlecase_column(data[fld])
        
        filtered = {k: v for k, v in data.items() if k in bq_fields}
        ndjson_lines.append(json.dumps(filtered, ensure_ascii=False))
        doc_id_map.append(d.id)

    if not ndjson_lines:
        st.warning("Tidak ada data yang cocok dengan skema BigQuery untuk disinkronkan.")
        return

    ndjson_bytes = "\n".join(ndjson_lines).encode("utf-8")
    file_obj = BytesIO(ndjson_bytes)
    file_obj.seek(0)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition="WRITE_APPEND",
        autodetect=False,
    )
    try:
        load_job = client.load_table_from_file(file_obj, dataset_table, job_config=job_config)
        load_job.result()
        for doc_id in doc_id_map:
            db.collection(FIRESTORE_COLLECTION).document(doc_id).update({"bigquery_synced": True, "bigquery_synced_at": firestore.SERVER_TIMESTAMP})
        st.success(f"Berhasil sinkron {len(doc_id_map)} dokumen ke BigQuery.")
    except Exception as e:
        st.error(f"Batch sync gagal: {e}")
        try:
            st.write(load_job.errors)
        except:
            pass

# ---------------------
# CSV handler - (MEMPERTAHANKAN metode ini, karena lebih fungsional)
# ---------------------
def handle_csv_and_images_upload(csv_file, image_files_list):
    try:
        df_csv = pd.read_csv(csv_file)
    except Exception as e:
        st.error(f"Gagal membaca CSV: {e}")
        return

    df_csv.columns = df_csv.columns.str.strip()
    image_map = {f.name: f for f in (image_files_list or [])}

    count = 0
    for i, row in df_csv.iterrows():
        # <-- UBAHAN: Mengadopsi generator ID yang lebih kuat
        if "L-ID" in df_csv.columns and pd.notna(row.get("L-ID")):
            lid = str(row.get("L-ID"))
        else:
            lid = f"L{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"

        entry = row.to_dict()
        for col in ["Province", "Regency_City", "District", "Village"]:
            if col in entry and pd.notna(entry[col]):
                entry[col] = titlecase_column(entry[col])

        entry.update({
            "L-ID": lid,
            "Data Entry": st.session_state.username,
            "Date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        image_url = None
        image_filename = None
        if "image_filename" in df_csv.columns and pd.notna(row.get("image_filename")):
            image_filename = str(row.get("image_filename"))
        elif "image" in df_csv.columns and pd.notna(row.get("image")):
            image_filename = str(row.get("image"))

        if image_filename and image_filename in image_map:
            uploaded_img = image_map[image_filename]
            image_url = upload_image_to_gcs_and_get_url(f"{lid}_{image_filename.split('.')[0]}", uploaded_img)
            entry["image_url"] = image_url

        save_entry_to_firestore(entry)
        count += 1

    st.success(f"Berhasil memproses {count} baris dari CSV dan menyimpan ke Firestore.")

# ---------------------
# Load data for viewer: BigQuery + Firestore recent overlay
# ---------------------
@st.cache_data(ttl=300)
def load_data_for_viewer():
    try:
        bq = get_bq_client_cached()
        df_bq = bq.query(f"SELECT * FROM `{BQ_TABLE}`").to_dataframe()
    except Exception as e:
        st.warning(f"Tidak dapat memuat data dari BigQuery: {e}. Menampilkan data terbaru saja.")
        df_bq = pd.DataFrame()

    try:
        fs_df = get_recent_entries_from_firestore(limit=500)
    except Exception as e:
        st.error(f"Error loading Firestore data: {e}")
        fs_df = pd.DataFrame()

    if not fs_df.empty:
        if "Lattitute" not in fs_df.columns and "lat" in fs_df.columns:
            fs_df["Lattitute"] = fs_df["lat"]
        if "Longitude" not in fs_df.columns and "lon" in fs_df.columns:
            fs_df["Longitude"] = fs_df["lon"]
        if "Date" not in fs_df.columns and "date" in fs_df.columns:
            fs_df["Date"] = fs_df["date"]
    
    combined = pd.concat([df_bq, fs_df], ignore_index=True).drop_duplicates(subset=["L-ID"], keep='last')

    if "Lattitute" in combined.columns:
        combined["Latitude Decimals"] = combined["Lattitute"].apply(dms_to_dd)
    if "Longitude" in combined.columns:
        combined["Longitude Decimals"] = combined["Longitude"].apply(dms_to_dd)
        
    return combined

# ---------------------
# Authentication (Firestore used for users)
# ---------------------
@st.cache_resource
def get_firestore_user_collection():
    return get_firestore_client_cached().collection("users")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register():
    st.markdown(create_login_image_placeholder(), unsafe_allow_html=True)
    with st.container():
        st.markdown("### 📝 Daftar Akun Baru")
        new_user = st.text_input("Username baru", key="reg_user")
        new_pass = st.text_input("Password", type="password", key="reg_pass")
        if st.button("Daftar"):
            if new_user and new_pass:
                users = get_firestore_user_collection()
                if users.document(new_user).get().exists:
                    st.warning("Username sudah digunakan.")
                else:
                    users.document(new_user).set({"password": hash_password(new_pass), "role": "viewer"})
                    st.success("Registrasi berhasil! Silakan login.")
                    st.session_state.page = "login"
                    st.rerun()
            else:
                st.error("Username dan password harus diisi!")

def login():
    st.markdown(create_login_image_placeholder(), unsafe_allow_html=True)
    with st.container():
        st.markdown("### 🔐 Login")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Login"):
                if username and password:
                    users = get_firestore_user_collection()
                    doc = users.document(username).get()
                    if doc.exists and doc.to_dict().get("password") == hash_password(password):
                        st.session_state.logged_in = True
                        st.session_state.username = username
                        st.session_state.role = doc.to_dict().get("role", "viewer")
                        st.rerun()
                    else:
                        st.error("Login gagal. Periksa username/password.")
                else:
                    st.error("Isi username dan password.")
        with col2:
            if st.button("Daftar Akun Baru"):
                st.session_state.page = "register"
                st.rerun()

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'page' not in st.session_state:
    st.session_state.page = "login"
if 'role' not in st.session_state:
    st.session_state.role = None

# Authentication flow
if not st.session_state.logged_in:
    if st.session_state.page == "login":
        login()
    else:
        register()
    st.stop()

# ---------------------
# Main App UI
# ---------------------
st.title("🗻 Landslide Viewer - Jawa Barat")

def create_sidebar():
    with st.sidebar:
        st.markdown("### Profil Pengguna")
        col1, col2 = st.columns([1, 3])
        with col1:
            st.markdown("""
            <div style="
                width: 50px; height:50px; border-radius:50%;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                display:flex; align-items:center; justify-content:center;">
                <span style="font-size:20px;color:white">👤</span>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.write(f"**{st.session_state.username}**")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.rerun()
        st.divider()
        st.markdown("### 🗺️ Kontrol Peta")
        display_mode = st.selectbox("Tampilan Data", ["Marker", "Point", "Heatmap"])
        base_layer = st.selectbox("Tipe Basemap", ["OpenStreetMap", "Satellite", "Terrain", "Kontur"])
        show_boundaries = st.checkbox("Tampilkan Batas Wilayah", value=True)
        show_labels = st.checkbox("Tampilkan Label", value=False)
        st.divider()
        st.markdown("### 📊 Statistik")
    return display_mode, base_layer, show_boundaries, show_labels

display_mode, base_layer, show_boundaries, show_labels = create_sidebar()

df = load_data_for_viewer()
gdf = None
try:
    gdf = gpd.read_file("Jabar_By_Kec.geojson")
except Exception as e:
    st.error(f"Error loading boundary file: {e}")

if df.empty or gdf is None:
    st.error("Could not load required data. Please check configuration.")
    st.stop()

df.columns = df.columns.str.strip()

col_main, col_filters = st.columns([3,1])
with col_main:
    regency_col = "Regency_City"
    district_col_df = "District"
    boundary_col = "KABKOT"
    if regency_col in df.columns:
        df[regency_col] = df[regency_col].astype(str).str.lower().str.title()
    if district_col_df in df.columns:
        df[district_col_df] = df[district_col_df].astype(str).str.lower().str.title()
    if boundary_col in gdf.columns:
        gdf[boundary_col] = gdf[boundary_col].astype(str).str.lower().str.title()
    
    col1, col2 = st.columns(2)
    with col1:
        possible_regions = ["Semua"]
        if regency_col in df.columns:
            possible_regions += sorted(df[regency_col].dropna().unique())
        selected_region = st.selectbox("Pilih Kabupaten/Kota", possible_regions)
    
    df = df.dropna(subset=["Latitude Decimals", "Longitude Decimals"])
    gdf_points = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["Longitude Decimals"], df["Latitude Decimals"]), crs="EPSG:4326")

    if selected_region != "Semua":
        filtered_gdf = gdf_points[gdf_points[regency_col] == selected_region].copy()
        boundary = gdf[gdf[boundary_col] == selected_region].copy()
    else:
        filtered_gdf = gdf_points.copy()
        boundary = gdf.copy()

    available_districts = sorted(filtered_gdf[district_col_df].dropna().unique()) if district_col_df in filtered_gdf.columns else []
    with col2:
        selected_district = st.selectbox("Pilih Kecamatan", ["Semua"] + available_districts)
    if selected_district != "Semua":
        filtered_gdf = filtered_gdf[filtered_gdf[district_col_df] == selected_district]

    basemap_dict = {"OpenStreetMap":"OpenStreetMap", "Satellite":"HYBRID", "Terrain":"TERRAIN", "Kontur":"Esri.WorldTopoMap"}
    m = leafmap.Map(center=[-7.1, 107.6], zoom=8)
    m.add_basemap(basemap_dict.get(base_layer, "OpenStreetMap"))
    
    if show_boundaries and not boundary.empty:
        m.add_gdf(boundary, layer_name="Batas Wilayah")
    
    popup_cols = [c for c in filtered_gdf.columns if c not in ['geometry', 'Latitude Decimals', 'Longitude Decimals', '_doc_id']]
    
    if display_mode == "Marker" and not filtered_gdf.empty:
        m.add_points_from_xy(
            filtered_gdf,
            x="Longitude Decimals",
            y="Latitude Decimals",
            popup=popup_cols,
            layer_name="Landslide Markers"
        )
    elif display_mode == "Point" and not filtered_gdf.empty:
        m.add_points_from_xy(filtered_gdf, x="Longitude Decimals", y="Latitude Decimals", layer_name="Landslide Points")
    elif display_mode == "Heatmap" and not filtered_gdf.empty:
        heatmap_data = filtered_gdf[['Latitude Decimals','Longitude Decimals']].copy()
        heatmap_data['value'] = 1
        m.add_heatmap(data=heatmap_data, latitude='Latitude Decimals', longitude='Longitude Decimals', value='value', radius=15)
        
    m.to_streamlit(height=600)

st.markdown("---")
with st.expander("🔧 Advanced Filters", expanded=False):
    st.markdown("**Filter Data Berdasarkan Parameter Numerik:**")
    # <-- UBAHAN: Menyesuaikan nama kolom dengan skema data baru yang lebih bersih
    numeric_filters = ["Landslide Length (m)","Landslide Width (m)","Landslide Height (m)","Elevation (m)","Slope Angle (°)"]
    cols = st.columns(2)
    for i, coln in enumerate(numeric_filters):
        if coln in filtered_gdf.columns:
            filtered_gdf[coln] = pd.to_numeric(filtered_gdf[coln], errors="coerce")
            if not filtered_gdf[coln].dropna().empty:
                min_val = int(filtered_gdf[coln].min(skipna=True))
                max_val = int(filtered_gdf[coln].max(skipna=True))
                if min_val < max_val:
                    with cols[i%2]:
                        val_range = st.slider(f"**{coln}**", min_val, max_val, (min_val, max_val), key=f"filter_{coln}")
                        filtered_gdf = filtered_gdf[filtered_gdf[coln].between(val_range[0], val_range[1])]

with st.sidebar:
    if 'filtered_gdf' in locals():
        st.metric("Total Data Points", len(filtered_gdf))
        if not filtered_gdf.empty:
            st.metric("Wilayah Terpilih", selected_region if selected_region != "Semua" else "Seluruh Jawa Barat")
            # <-- UBAHAN: Menyesuaikan nama kolom
            if "Elevation (m)" in filtered_gdf.columns:
                avg_elevation = filtered_gdf["Elevation (m)"].mean()
                if not pd.isna(avg_elevation):
                    st.metric("Rata-rata Elevasi (m)", f"{avg_elevation:.1f}")

# ---------------------
# Editor Panel (Firestore-backed)
# ---------------------
if st.session_state.role in ["editor", "admin"]:
    page_mode = st.sidebar.radio("Mode", ["Viewer","Editor"], index=0)
else:
    page_mode = "Viewer"

if page_mode == "Editor":
    st.markdown("## ✏️ Editor Panel")
    st.info("Tambah, edit, atau hapus data. Data disimpan di Firestore dan dapat disinkronkan ke BigQuery.")

    # <-- UBAHAN TOTAL: Mengadopsi form dari kode baru yang lebih rapi dan fungsional.
    with st.expander("Tambah Data Manual", expanded=True):
        with st.form("manual_add_form", clear_on_submit=True):
            st.markdown("##### Informasi Lokasi")
            col1, col2 = st.columns(2)
            with col1:
                regency = st.text_input("Kabupaten/Kota*", key="m_regency")
                district = st.text_input("Kecamatan*", key="m_district")
                village = st.text_input("Desa*", key="m_village")
            with col2:
                latitude = st.number_input("Latitude (Desimal)*", format="%.6f", key="m_lat", step=0.000001)
                longitude = st.number_input("Longitude (Desimal)*", format="%.6f", key="m_lon", step=0.000001)
                elevation = st.number_input("Elevasi (m)", key="m_elev", step=1.0)
            
            st.markdown("##### Informasi Longsoran")
            col3, col4 = st.columns(2)
            with col3:
                landslide_date = st.date_input("Tanggal Kejadian", value=date.today(), key="m_date")
                observed_lithology = st.text_input("Litologi Teramati", key="m_lithology")
                landslide_type = st.text_input("Tipe Longsor", key="m_type")
                landslide_material = st.text_input("Material Longsor", key="m_material")
            with col4:
                landslide_length = st.number_input("Panjang Longsoran (m)", key="m_length", step=0.1)
                landslide_width = st.number_input("Lebar Longsoran (m)", key="m_width", step=0.1)
                landslide_height = st.number_input("Tinggi Longsoran (m)", key="m_height", step=0.1)
                landslide_pic = st.file_uploader("Upload Foto Longsor", type=["jpg","jpeg","png"], key="m_pic")
            
            additional_comments = st.text_area("Komentar Tambahan", key="m_comments")
            
            submitted = st.form_submit_button("Simpan ke Firestore")

            if submitted:
                if not all([regency, district, village, latitude, longitude]):
                    st.error("Mohon isi semua field yang ditandai bintang (*).")
                else:
                    # <-- BARU: Mengadopsi L-ID yang lebih kuat dari kode baru.
                    new_lid = f"L{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"
                    
                    # <-- UBAHAN: Mengadopsi skema data yang lebih bersih dari kode baru.
                    entry = {
                        "L-ID": new_lid,
                        "Province": "Jawa Barat",
                        "Regency_City": titlecase_column(regency),
                        "District": titlecase_column(district),
                        "Village": titlecase_column(village),
                        "Lattitute": latitude,
                        "Longitude": longitude,
                        "Elevation (m)": elevation,
                        "Observed Lithology": observed_lithology,
                        "Landslide Type": landslide_type,
                        "Landslide Material": landslide_material,
                        "Landslide Length (m)": landslide_length,
                        "Landslide Width (m)": landslide_width,
                        "Landslide Height (m)": landslide_height,
                        "Date": landslide_date.strftime("%Y-%m-%d"),
                        "Additional Comments": additional_comments,
                        "Data Entry": st.session_state.username,
                    }
                    if landslide_pic:
                        url = upload_image_to_gcs_and_get_url(f"{new_lid}", landslide_pic)
                        if url:
                            entry["image_url"] = url
                    
                    save_entry_to_firestore(entry)
                    st.success(f"Data {new_lid} berhasil disimpan. Muat ulang halaman untuk melihat pembaruan di peta.")
                    st.cache_data.clear() # Membersihkan cache agar data baru bisa dimuat

    st.markdown("---")

    with st.expander("Upload Massal via CSV", expanded=False):
        st.markdown("Pastikan nama kolom di CSV Anda cocok dengan field di form manual (contoh: `Regency_City`, `Lattitute`, `Landslide Type`, dll). `L-ID` opsional, akan dibuat otomatis jika kosong. `image_filename` bisa digunakan untuk mencocokkan dengan gambar.")
        uploaded_csv = st.file_uploader("Upload CSV", type=["csv"], key="csv_upload")
        uploaded_imgs = st.file_uploader("Upload Gambar (opsional, jika ada kolom `image_filename` di CSV)", type=["jpg","jpeg","png"], accept_multiple_files=True, key="img_upload")
        if st.button("Proses CSV"):
            if not uploaded_csv:
                st.error("Silakan pilih file CSV terlebih dahulu.")
            else:
                handle_csv_and_images_upload(uploaded_csv, uploaded_imgs)
                st.cache_data.clear()

    st.markdown("---")
    
    # Editor & Pagination
    st.markdown("#### Daftar Entri Terbaru (Edit / Hapus)")
    if "editor_page" not in st.session_state:
        st.session_state.editor_page = 0
    
    df_editor = get_entries_paginated(page_number=st.session_state.editor_page, page_size=PAGE_SIZE)
    
    colp1, colp2, colp3 = st.columns([1,2,1])
    with colp1:
        if st.button("⬅️ Halaman Sebelumnya", disabled=(st.session_state.editor_page == 0)):
            st.session_state.editor_page -= 1
            st.rerun()
    with colp2:
        st.markdown(f"<p style='text-align:center;'>Halaman {st.session_state.editor_page + 1}</p>", unsafe_allow_html=True)
    with colp3:
        if st.button("Halaman Berikutnya ➡️", disabled=(len(df_editor) < PAGE_SIZE)):
            st.session_state.editor_page += 1
            st.rerun()
            
    if df_editor.empty:
        st.info("Tidak ada data pada halaman ini.")
    else:
        display_cols = ['L-ID', 'Regency_City', 'District', 'Village', 'Date', 'Data Entry', 'bigquery_synced']
        st.dataframe(df_editor[[c for c in display_cols if c in df_editor.columns]].reset_index(drop=True), use_container_width=True)

        chosen_id = st.selectbox("Pilih L-ID untuk Edit / Hapus", options=df_editor["L-ID"].tolist())
        selected_row = df_editor[df_editor["L-ID"] == chosen_id].iloc[0].to_dict()

        with st.expander(f"Edit Entri: {chosen_id}"):
            with st.form("edit_form"):
                e_regency = st.text_input("Kabupaten/Kota", value=selected_row.get("Regency_City",""))
                e_district = st.text_input("Kecamatan", value=selected_row.get("District",""))
                e_village = st.text_input("Desa", value=selected_row.get("Village",""))
                e_lat = st.number_input("Latitude", value=float(selected_row.get("Lattitute", 0.0)), format="%.6f")
                e_lon = st.number_input("Longitude", value=float(selected_row.get("Longitude", 0.0)), format="%.6f")
                e_comments = st.text_area("Komentar Tambahan", value=selected_row.get("Additional Comments",""))
                e_pic = st.file_uploader("Ganti / Tambah foto", type=["jpg","jpeg","png"], key="edit_pic")
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    submit_edit = st.form_submit_button("Simpan Perubahan")
                with col_b2:
                    delete_button = st.form_submit_button("Hapus Entri Ini", help="Tindakan ini tidak bisa dibatalkan!")

                if submit_edit:
                    doc_id = selected_row["_doc_id"]
                    update_entry = {k:v for k,v in selected_row.items() if not k.startswith('_')} # start with existing data
                    update_entry.update({
                        "Regency_City": titlecase_column(e_regency),
                        "District": titlecase_column(e_district),
                        "Village": titlecase_column(e_village),
                        "Lattitute": e_lat,
                        "Longitude": e_lon,
                        "Additional Comments": e_comments,
                        "Data Entry": st.session_state.username,
                        "bigquery_synced": False, # Mark as needs-sync after edit
                    })
                    if e_pic:
                        url = upload_image_to_gcs_and_get_url(f"{chosen_id}_edit", e_pic)
                        if url:
                            update_entry["image_url"] = url
                    save_entry_to_firestore(update_entry, doc_id=doc_id)
                    st.success("Perubahan disimpan. Muat ulang halaman untuk pembaruan.")
                    st.cache_data.clear()

                if delete_button:
                    st.warning(f"Anda yakin ingin menghapus {chosen_id}?")
                    if st.button("Ya, Hapus Permanen"):
                        doc_id = selected_row["_doc_id"]
                        try:
                            get_firestore_client_cached().collection(FIRESTORE_COLLECTION).document(doc_id).delete()
                            st.success("Dokumen dihapus dari Firestore.")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal menghapus: {e}")


    st.markdown("---")
    st.markdown("#### Sinkronisasi Data")
    if st.button("Sinkronkan Data Baru ke BigQuery"):
        batch_sync_firestore_to_bigquery(dataset_table=BQ_TABLE)
        st.cache_data.clear()
        
# ---------------------
# CSS
# ---------------------
st.markdown("""
<style>
    .stApp {
        background-color: #FFFFFF;
    }
    .stSelectbox, .stTextInput, .stNumberInput, .stDateInput, .stTextArea {
        border-radius: 0.5rem;
    }
    .stButton > button {
        border-radius: 0.5rem;
        border: 1px solid #667eea;
        color: #667eea;
    }
    .stButton > button:hover {
        border-color: #764ba2;
        color: #764ba2;
    }
    .stExpander {
        border: 1px solid #e9ecef;
        border-radius: 0.5rem;
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)
