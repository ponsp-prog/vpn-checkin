import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime

# --- 1. CONFIG & STYLING (ปรับแต่งให้รองรับ Mobile แบบ 100%) ---
st.set_page_config(page_title="VPN Analytics Portal", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;600;700&display=swap');
    
    html, body, [class*="css"], .stText, .stMarkdown p, .stMetric label {
        font-family: 'IBM Plex Sans Thai', sans-serif !important;
    }

    .stApp { background-color: #F8FAFC; }
    
    /* หัวข้อแบบ Responsive: ในคอมจะใหญ่ ในมือถือจะเล็กลงอัตโนมัติ */
    .hero-title {
        font-size: clamp(32px, 8vw, 64px) !important;
        font-weight: 700 !important;
        text-align: center;
        margin-top: -10px;
        margin-bottom: 5px;
        line-height: 1.2;
    }
    .user-color { color: #1E40AF; }
    .admin-color { color: #B91C1C; }
    
    .hero-subtitle {
        font-size: clamp(16px, 4vw, 22px) !important;
        text-align: center;
        color: #64748B;
        margin-bottom: 25px;
    }

    /* ปรับแต่งกรอบ Container ให้ขอบมนและดูสะอาดตา */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: white;
        border-radius: 12px !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
        padding: 10px !important;
    }

    /* ปรับแต่ง Dataframe ให้ดูง่ายบนมือถือ */
    .stDataFrame { width: 100% !important; }
    
    header {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATABASE LOGIC ---
def get_db_connection():
    return sqlite3.connect('vpn_data.db')

# --- 3. ROUTING ---
is_admin = st.query_params.get("role") == "admin"

# --- 4. ADMIN UI ---
if is_admin:
    st.markdown('<p class="hero-title admin-color">🛠️ Admin Control</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">จัดการและอัปเดตข้อมูลผ่านมือถือได้ทันที</p>', unsafe_allow_html=True)
    
    with st.container(border=True):
        st.subheader("📤 อัปโหลดข้อมูลใหม่")
        uploaded_file = st.file_uploader("เลือกไฟล์ Excel (.xlsx)", type=['xlsx'])
        
        if uploaded_file:
            try:
                df = pd.read_excel(uploaded_file)
                df.columns = df.columns.str.strip()
                df['Local time'] = pd.to_datetime(df['Local time'], errors='coerce')
                df = df.dropna(subset=['Local time'])
                df['Date'] = df['Local time'].dt.date.astype(str)
                df_first = df.sort_values('Local time').groupby(['Computer name', 'Date']).first().reset_index()
                
                df_to_db = df_first[['Computer name', 'Date', 'Local time']].copy()
                df_to_db['Local time'] = df_to_db['Local time'].dt.strftime('%H:%M:%S')
                df_to_db.columns = ['Computer_name', 'Date', 'Local_time']

                conn = get_db_connection()
                df_to_db.to_sql('vpn_logs', conn, if_exists='append', index=False)
                conn.close()
                st.success("✅ บันทึกข้อมูลสำเร็จ!")
            except Exception as e:
                st.error(f"❌ พบข้อผิดพลาด: {e}")
    
    st.write("")
    if st.button("← กลับสู่หน้าหลัก", use_container_width=True):
        st.query_params.clear()
        st.rerun()

# --- 5. USER UI ---
else:
    st.markdown('<p class="hero-title user-color">🌐 VPN Check-in</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">ระบบตรวจสอบเวลาเข้างานรายวัน</p>', unsafe_allow_html=True)
    
    try:
        conn = get_db_connection()
        df_dates = pd.read_sql("SELECT DISTINCT Date FROM vpn_logs ORDER BY Date DESC", conn)
        
        if not df_dates.empty:
            df_dates['Date_dt'] = pd.to_datetime(df_dates['Date'])
            
            with st.container(border=True):
                st.write("**📅 เลือกวันที่ต้องการดูข้อมูล**")
                # ใช้ Columns แบบ Dynamic
                c1, c2, c3 = st.columns([1, 1.2, 1])
                years = sorted(df_dates['Date_dt'].dt.year.unique(), reverse=True)
                with c3: sel_year = st.selectbox("ปี", years)
                months = sorted(df_dates[df_dates['Date_dt'].dt.year == sel_year]['Date_dt'].dt.month.unique(), reverse=True)
                with c2: sel_month = st.selectbox("เดือน", months)
                days = sorted(df_dates[(df_dates['Date_dt'].dt.year == sel_year) & (df_dates['Date_dt'].dt.month == sel_month)]['Date_dt'].dt.day.unique(), reverse=True)
                with c1: sel_day = st.selectbox("วัน", days)

            target_date = f"{sel_year}-{sel_month:02d}-{sel_day:02d}"
            df_result = pd.read_sql(f"SELECT Computer_name, Local_time FROM vpn_logs WHERE Date = '{target_date}'", conn)
            
            if not df_result.empty:
                # ส่วน Metric: ในมือถือจะเรียงต่อกันเป็นแนวตั้งให้อัตโนมัติ
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    with st.container(border=True):
                        st.metric("👥 พนักงานทั้งหมด", f"{len(df_result)} คน")
                with col_m2:
                    with st.container(border=True):
                        st.metric("🌅 เข้างานคนแรก", df_result['Local_time'].min())
                
                with st.container(border=True):
                    st.write(f"**📋 รายชื่อพนักงาน ({sel_day:02d}/{sel_month:02d}/{sel_year})**")
                    # ตารางจะขยายกว้างตามหน้าจอมือถือ
                    st.dataframe(df_result, use_container_width=True, hide_index=True)
            
            with st.container(border=True):
                st.write("**📊 ดาวน์โหลดรายงาน**")
                all_dates_raw = sorted(df_dates['Date_dt'].dt.date.unique(), reverse=True)
                date_options = {d.strftime('%d/%m/%Y'): d.strftime('%Y-%m-%d') for d in all_dates_raw}
                selected_labels = st.multiselect("เลือกวันที่:", options=list(date_options.keys()))
                
                if selected_labels:
                    days_query = [date_options[label] for label in selected_labels]
                    report_df = pd.read_sql(f"SELECT * FROM vpn_logs WHERE Date IN ({','.join(['?']*len(days_query))})", conn, params=days_query)
                    report_df['Date'] = pd.to_datetime(report_df['Date']).dt.strftime('%d/%m/%Y')
                    st.download_button("📥 ดาวน์โหลดไฟล์ .CSV", report_df.to_csv(index=False).encode('utf-8-sig'), "VPN_Report.csv", "text/csv", use_container_width=True)
        else:
            st.info("📢 ยินดีต้อนรับครับเจ้านาย! รอแอดมินอัปโหลดข้อมูลครับ")
        conn.close()
    except Exception as e:
        st.error(f"⚠️ พบข้อผิดพลาด: {e}")