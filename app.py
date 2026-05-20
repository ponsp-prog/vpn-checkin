import streamlit as st
import pandas as pd
import sqlite3
import io
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 1. CONFIG & STYLING
# ---------------------------------------------------------------------------
st.set_page_config(page_title="VPN Analytics Portal", layout="wide")

# ประกาศตัวแปรชื่อเดือนไว้ตรงนี้เพื่อให้ใช้ได้ทุกที่ในโปรแกรมครับคุณพล
MONTHS_TH = [
    '', 'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
    'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'
]

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;600;700&display=swap');
    html, body, [class*="css"], .stApp {
        font-family: 'IBM Plex Sans Thai', sans-serif !important;
        background-color: #FFFFFF !important;
        color: #1E293B !important;
    }
    .hero-title {
        font-size: 52px !important;
        font-weight: 800 !important;
        text-align: center;
        background: linear-gradient(90deg, #FF00E6, #00C8FF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 5px;
    }
    .user-color  { color: #00C8FF !important; font-weight: 700; }
    .admin-color { color: #F61100 !important; font-weight: 700; }
    .hero-subtitle {
        font-size: 18px !important;
        text-align: center;
        color: #64748B;
        margin-bottom: 30px;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF !important;
        border-radius: 20px !important;
        border: 2px solid #4200EA !important;
        box-shadow: 0 10px 25px -5px rgba(66, 0, 234, 0.15) !important;
        padding: 25px !important;
        margin-bottom: 25px;
    }
    .stButton>button {
        background: #4200EA !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 12px !important;
        height: 48px !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 14px 0 rgba(66, 0, 234, 0.39) !important;
        transition: 0.2s all ease;
    }
    .stButton>button:hover {
        background: #FF00E6 !important;
        transform: translateY(-2px);
    }
    [data-testid="stMetricValue"] {
        background: linear-gradient(90deg, #FF00E6, #00C8FF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800 !important;
        font-size: 48px !important;
    }
    header, footer { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 2. DATABASE & PARSE FUNCTIONS
# ---------------------------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect('vpn_data.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vpn_logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            Computer_name TEXT,
            Account       TEXT,
            Date          TEXT,
            Local_time    TEXT,
            UNIQUE(Computer_name, Date)
        )
    ''')
    conn.commit()
    return conn

def parse_vpn_file(file_bytes: bytes) -> pd.DataFrame | None:
    df_raw = None
    try:
        tables = pd.read_html(io.BytesIO(file_bytes), flavor="lxml")
        if tables: df_raw = pd.concat(tables, ignore_index=True)
    except: pass

    if df_raw is None:
        try: df_raw = pd.read_excel(io.BytesIO(file_bytes), engine="xlrd")
        except:
            try: df_raw = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
            except: return None

    df_raw.columns = [re.sub(r'\s+', ' ', str(c)).strip() for c in df_raw.columns]
    
    time_col = next((c for c in df_raw.columns if re.search(r'local\s*time', c, re.I)), None)
    name_col = next((c for c in df_raw.columns if re.search(r'computer\s*name', c, re.I)), None)
    acc_col  = next((c for c in df_raw.columns if re.search(r'account', c, re.I)), None)
    event_col = next((c for c in df_raw.columns if re.search(r'event\s*type', c, re.I)), None)

    if not all([time_col, name_col, event_col]): return None

    df_ua = df_raw[df_raw[event_col].astype(str).str.strip().str.lower() == "user activity"].copy()
    if df_ua.empty: return None

    df_ua[time_col] = pd.to_datetime(df_ua[time_col], dayfirst=False, errors='coerce')
    df_ua = df_ua.dropna(subset=[time_col, name_col])
    df_ua['Date'] = df_ua[time_col].dt.date.astype(str)

    df_first = df_ua.sort_values(time_col).groupby([name_col, 'Date'], as_index=False).first()

    return pd.DataFrame({
        'Computer_name': df_first[name_col].str.strip(),
        'Account':       df_first[acc_col].str.strip() if acc_col else "-",
        'Date':          df_first['Date'],
        'Local_time':    df_first[time_col].dt.strftime('%H:%M:%S'),
    })

# ---------------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------------
is_admin = st.query_params.get("role") == "admin"
# ---------------------------------------------------------------------------
# 4. ADMIN UI 
# ---------------------------------------------------------------------------
if is_admin:
    st.markdown('<p class="hero-title admin-color">🛠️ Admin Control</p>', unsafe_allow_html=True)

    if st.button("← กลับสู่หน้าหลัก", use_container_width=True):
        st.query_params.clear()
        st.rerun()

    # --- ส่วนที่ 1: การอัปโหลดข้อมูล ---
    with st.container(border=True):
        st.subheader("📤 อัปโหลดข้อมูลใหม่")
        uploaded_file = st.file_uploader(
            "เลือกไฟล์ OpenVPN Export (.xls, .xlsx)",
            type=['xlsx', 'xls'],
            key="upload_file"
        )

        if uploaded_file:
            file_bytes = uploaded_file.read()
            with st.spinner("กำลังอ่านและประมวลผลไฟล์..."):
                df_to_db = parse_vpn_file(file_bytes)

            if df_to_db is not None and not df_to_db.empty:
                st.write("**📋 ตัวอย่างข้อมูลที่จะบันทึก:**")
                st.dataframe(df_to_db, use_container_width=True, hide_index=True)

                if st.button("✅ ยืนยันบันทึกลงฐานข้อมูล", use_container_width=True, key="confirm_save"):
                    try:
                        conn = get_db_connection()
                        inserted = skipped = 0
                        for _, row in df_to_db.iterrows():
                            cur = conn.execute(
                                "INSERT OR IGNORE INTO vpn_logs (Computer_name, Account, Date, Local_time) VALUES (?, ?, ?, ?)",
                                (row['Computer_name'], row['Account'], row['Date'], row['Local_time'])
                            )
                            inserted += cur.rowcount
                            skipped  += 1 - cur.rowcount
                        conn.commit()
                        conn.close()
                        st.success(f"✅ บันทึกสำเร็จ {inserted} รายการ | ข้ามซ้ำ {skipped} รายการ")
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ พบข้อผิดพลาดขณะบันทึก: {e}")

    # --- ส่วนที่ 2: การลบข้อมูลแบบแยก วัน/เดือน/ปี ---
    with st.container(border=True):
        st.subheader("🗑️ จัดการและลบข้อมูลรายวัน")
        
        conn = get_db_connection()
        df_exists = pd.read_sql("SELECT DISTINCT Date FROM vpn_logs", conn)
        conn.close()

        if not df_exists.empty:
            df_exists['Date_dt'] = pd.to_datetime(df_exists['Date'])
            
            c1, c2, c3 = st.columns(3)
            
            # 1. เลือกปี
            years = sorted(df_exists['Date_dt'].dt.year.unique(), reverse=True)
            with c1:
                sel_y = st.selectbox("เลือกปี", options=years, format_func=lambda y: f"พ.ศ. {y + 543}")
            
            # 2. เลือกเดือน
            months = sorted(df_exists[df_exists['Date_dt'].dt.year == sel_y]['Date_dt'].dt.month.unique(), reverse=True)
            with c2:
                sel_m = st.selectbox("เลือกเดือน", options=months, format_func=lambda m: MONTHS_TH[m])
            
            # 3. เลือกวัน
            days = sorted(df_exists[(df_exists['Date_dt'].dt.year == sel_y) & 
                                    (df_exists['Date_dt'].dt.month == sel_m)]['Date_dt'].dt.day.unique(), reverse=True)
            with c3:
                sel_d = st.selectbox("เลือกวันที่", options=days)

            target_del_date = f"{sel_y}-{sel_m:02d}-{sel_d:02d}"
            display_date = f"{sel_d} {MONTHS_TH[sel_m]} {sel_y + 543}"

            if st.button(f"❌ ยืนยันลบข้อมูลวันที่ {display_date}", use_container_width=True):
                conn = get_db_connection()
                conn.execute("DELETE FROM vpn_logs WHERE Date = ?", (target_del_date,))
                conn.commit()
                conn.close()
                st.success(f"ลบข้อมูลวันที่ {display_date} เรียบร้อยแล้ว")
                st.rerun()
        else:
            st.info("ยังไม่มีข้อมูลในระบบให้จัดการครับ")

        st.divider()
        
        if st.button("⚠️ ล้างฐานข้อมูลทั้งหมด (ลบทุกอย่าง)", use_container_width=True):
            conn = get_db_connection()
            conn.execute("DELETE FROM vpn_logs")
            conn.commit()
            conn.close()
            st.success("ล้างข้อมูลทั้งหมดเรียบร้อยแล้ว!")
            st.rerun()

else:
    # ---------------------------------------------------------------------------
    # 5. USER UI
    # ---------------------------------------------------------------------------
    st.markdown('<p class="hero-title user-color">🌐 VPN Check-in</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">ระบบตรวจสอบเวลาเข้าใช้งาน VPN รายสัปดาห์</p>', unsafe_allow_html=True)

    try:
        conn = get_db_connection()
        df_dates = pd.read_sql("SELECT DISTINCT Date FROM vpn_logs ORDER BY Date DESC", conn)

        if not df_dates.empty:
            df_dates['Date_dt'] = pd.to_datetime(df_dates['Date'])

            # 5.1 สรุปสัปดาห์
            with st.container(border=True):
                st.write("**📊 สถานะการเข้าใช้งานรายสัปดาห์ ( อังคาร – จันทร์ )**")
                today = datetime.now().date()
                days_since_tuesday = (today.weekday() - 1) % 7
                current_week_start = today - timedelta(days=days_since_tuesday)

                weeks = []
                for i in range(4):
                    s = current_week_start - timedelta(weeks=i)
                    e = s + timedelta(days=6)
                    weeks.append((f"{s.strftime('%d/%m/%Y')} - {e.strftime('%d/%m/%Y')}" + (" ( ปัจจุบัน )" if i==0 else ""), s, e))

                sel_idx = st.selectbox("เลือกรอบสัปดาห์ :", options=range(len(weeks)), format_func=lambda i: weeks[i][0])
                _, sw, ew = weeks[sel_idx]

                df_w = pd.read_sql("SELECT Computer_name, Account, Date FROM vpn_logs WHERE Date BETWEEN ? AND ?", conn, params=[str(sw), str(ew)])
                if not df_w.empty:
                    dr = [sw + timedelta(days=d) for d in range(7)]
                    df_w['Date_dt'] = pd.to_datetime(df_w['Date']).dt.date
                    user_stats = []
                    for u in df_w['Computer_name'].unique():
                        ud = df_w[df_w['Computer_name'] == u]['Date_dt'].tolist()
                        acc = df_w[df_w['Computer_name'] == u]['Account'].iloc[0] if 'Account' in df_w.columns else "-"
                        user_stats.append({'name': u, 'account': acc, 'active': len(set(ud) & set(dr)), 'dates': ud})
                    
                    user_stats = sorted(user_stats, key=lambda x: x['active'], reverse=True)
                    html = ""
                    for u in user_stats:
                        dots = "".join([f'<span style="color: {"#FF00E6" if d in u["dates"] else "#E2E8F0"}; font-size: 24px; margin-right: 8px;">●</span>' for d in dr])
                        html += f"<tr><td style='padding:12px; border-bottom:1px solid #F1F5F9;'>{u['name']}</td><td style='padding:12px; border-bottom:1px solid #F1F5F9;'>{u['account']}</td><td style='padding:12px; border-bottom:1px solid #F1F5F9; text-align:center;'>{dots}</td><td style='padding:12px; border-bottom:1px solid #F1F5F9; font-weight:700; color:#4200EA;'>{u['active']} วัน</td></tr>"
                    st.markdown(f'<table style="width:100%; border-collapse:collapse;"><thead><tr style="background-color:#F8FAFC;"><th style="text-align:left; padding:12px;">พนักงาน (Computer)</th><th style="text-align:left; padding:12px;">Account</th><th style="text-align:center; padding:12px;">ตารางเข้าใช้งาน</th><th style="text-align:left; padding:12px;">รวม</th></tr></thead><tbody>{html}</tbody></table>', unsafe_allow_html=True)

            # 5.2 รายวัน
            with st.container(border=True):
                st.write("**📅 ตรวจสอบรายวัน**")
                c_y, c_m, c_d = st.columns(3)
                years = sorted(df_dates['Date_dt'].dt.year.unique(), reverse=True)
                with c_y: sy = st.selectbox("ปี ", options=years, format_func=lambda y: str(y+543))
                months = sorted(df_dates[df_dates['Date_dt'].dt.year == sy]['Date_dt'].dt.month.unique(), reverse=True)
                with c_m: sm = st.selectbox("เดือน ", options=months, format_func=lambda m: MONTHS_TH[m])
                days = sorted(df_dates[(df_dates['Date_dt'].dt.year == sy) & (df_dates['Date_dt'].dt.month == sm)]['Date_dt'].dt.day.unique(), reverse=True)
                with c_d: sd = st.selectbox("วัน ", options=days)

                res = pd.read_sql("SELECT Computer_name, Account, Local_time FROM vpn_logs WHERE Date = ? ORDER BY Local_time ASC", conn, params=[f"{sy}-{sm:02d}-{sd:02d}"])
                if not res.empty:
                    m1, m2 = st.columns(2)
                    m1.metric("👥 จำนวนพนักงาน", f"{len(res)} คน")
                    m2.metric("🌅 เวลาเข้าแรกสุด", res['Local_time'].min())
                    st.dataframe(res, use_container_width=True, hide_index=True)

        else:
            st.info("📢 ยินดีต้อนรับคุณพล! ขณะนี้ยังไม่มีข้อมูลในระบบครับ")
        conn.close()
    except Exception as e:
        st.error(f"⚠️ พบข้อผิดพลาด: {e}")