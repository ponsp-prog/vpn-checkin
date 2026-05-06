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

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;600;700&display=swap');
    html, body, [class*="css"], .stText, .stMarkdown p, .stMetric label {
        font-family: 'IBM Plex Sans Thai', sans-serif !important;
    }
    .stApp { background-color: #F8FAFC; }
    .hero-title {
        font-size: clamp(32px, 8vw, 64px) !important;
        font-weight: 700 !important;
        text-align: center;
        margin-bottom: 5px;
    }
    .user-color  { color: #1E40AF; }
    .admin-color { color: #B91C1C; }
    .hero-subtitle {
        font-size: clamp(16px, 4vw, 22px) !important;
        text-align: center;
        color: #64748B;
        margin-bottom: 25px;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: white;
        border-radius: 12px !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        padding: 15px !important;
        margin-bottom: 15px;
    }
    header { visibility: hidden; }
    footer  { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 2. DATABASE
# ---------------------------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect('vpn_data.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vpn_logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            Computer_name TEXT,
            Date          TEXT,
            Local_time    TEXT,
            UNIQUE(Computer_name, Date)
        )
    ''')
    conn.commit()
    return conn

# ---------------------------------------------------------------------------
# 3. PARSE FUNCTION
#    รองรับ: HTML-based .xls (OpenVPN export) / binary .xls / .xlsx
#    - concat ทุก <table> ในไฟล์เดียว
#    - กรองเฉพาะ Event type = "User activity"
#    - เก็บเฉพาะ Local time เช้าที่สุดของแต่ละคนต่อวัน
# ---------------------------------------------------------------------------
def parse_vpn_file(file_bytes: bytes) -> pd.DataFrame | None:
    df_raw = None
    errors = []

    # Strategy A — pd.read_html (HTML-based .xls)
    try:
        tables = pd.read_html(io.BytesIO(file_bytes), flavor="lxml")
        if tables:
            df_raw = pd.concat(tables, ignore_index=True)
    except Exception as e:
        errors.append(f"read_html (lxml): {e}")

    # Strategy B — xlrd (binary .xls)
    if df_raw is None:
        try:
            df_raw = pd.read_excel(io.BytesIO(file_bytes), engine="xlrd")
        except Exception as e:
            errors.append(f"xlrd: {e}")

    # Strategy C — openpyxl (.xlsx)
    if df_raw is None:
        try:
            df_raw = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
        except Exception as e:
            errors.append(f"openpyxl: {e}")

    if df_raw is None:
        st.error("❌ ไม่สามารถอ่านไฟล์ได้:\n" + "\n".join(errors))
        return None

    # Normalize column names
    df_raw.columns = [re.sub(r'\s+', ' ', str(c)).strip() for c in df_raw.columns]

    def find_col(pattern: str) -> str | None:
        for col in df_raw.columns:
            if re.search(pattern, col, flags=re.IGNORECASE):
                return col
        return None

    time_col  = find_col(r'local\s*time')
    name_col  = find_col(r'computer\s*name')
    event_col = find_col(r'event\s*type')

    missing = [lbl for lbl, col in [("Local time", time_col),
                                     ("Computer name", name_col),
                                     ("Event type", event_col)] if col is None]
    if missing:
        st.error(f"❌ หาคอลัมน์ไม่เจอ: **{', '.join(missing)}**\n\n"
                 f"คอลัมน์ที่มีในไฟล์: `{', '.join(df_raw.columns.tolist())}`")
        return None

    # Filter: User activity only
    df_ua = df_raw[
        df_raw[event_col].astype(str).str.strip().str.lower() == "user activity"
    ].copy()

    if df_ua.empty:
        st.warning("⚠️ ไม่พบแถวที่มี Event type = 'User activity' ในไฟล์นี้")
        return None

    # Parse datetime → keep earliest per person per day
    df_ua[time_col] = pd.to_datetime(df_ua[time_col], dayfirst=False, errors='coerce')
    df_ua = df_ua.dropna(subset=[time_col, name_col])
    df_ua['Date'] = df_ua[time_col].dt.date.astype(str)

    df_first = (
        df_ua
        .sort_values(time_col)
        .groupby([name_col, 'Date'], as_index=False)
        .first()
    )

    return pd.DataFrame({
        'Computer_name': df_first[name_col].str.strip(),
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

    if st.button("🗑️ ล้างฐานข้อมูลทั้งหมด", use_container_width=True):
        conn = get_db_connection()
        conn.execute("DELETE FROM vpn_logs")
        conn.commit()
        conn.close()
        st.success("ล้างข้อมูลเรียบร้อยแล้ว!")
        st.rerun()

    with st.container(border=True):
        st.subheader("📤 อัปโหลดข้อมูลใหม่")
        uploaded_file = st.file_uploader(
            "เลือกไฟล์ OpenVPN Export (.xls, .xlsx)",
            type=['xlsx', 'xls']
        )

        if uploaded_file:
            file_bytes = uploaded_file.read()
            with st.spinner("กำลังอ่านและประมวลผลไฟล์..."):
                df_to_db = parse_vpn_file(file_bytes)

            if df_to_db is not None and not df_to_db.empty:
                st.write(f"**ตัวอย่างข้อมูล ({len(df_to_db)} รายการ):**")
                st.dataframe(df_to_db, use_container_width=True, hide_index=True)

                if st.button("✅ ยืนยันบันทึกลงฐานข้อมูล", use_container_width=True):
                    try:
                        conn = get_db_connection()
                        inserted = skipped = 0
                        for _, row in df_to_db.iterrows():
                            cur = conn.execute(
                                "INSERT OR IGNORE INTO vpn_logs (Computer_name, Date, Local_time) VALUES (?, ?, ?)",
                                (row['Computer_name'], row['Date'], row['Local_time'])
                            )
                            if cur.rowcount:
                                inserted += 1
                            else:
                                skipped += 1
                        conn.commit()
                        conn.close()
                        st.success(f"✅ บันทึกสำเร็จ {inserted} รายการ | ข้ามซ้ำ {skipped} รายการ")
                    except Exception as e:
                        st.error(f"❌ พบข้อผิดพลาดขณะบันทึก: {e}")

    if st.button("← กลับสู่หน้าหลัก", use_container_width=True):
        st.query_params.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# 5. USER UI
# ---------------------------------------------------------------------------
else:
    st.markdown('<p class="hero-title user-color">🌐 VPN Check-in</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">ระบบตรวจสอบเวลาเข้าใช้งาน VPN และสรุปผลการเข้าใช้งานรอบสัปดาห์</p>',
                unsafe_allow_html=True)

    MONTHS_TH = [
        '', 'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
        'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'
    ]

    try:
        conn = get_db_connection()
        df_dates = pd.read_sql("SELECT DISTINCT Date FROM vpn_logs ORDER BY Date DESC", conn)

        if not df_dates.empty:
            df_dates['Date_dt'] = pd.to_datetime(df_dates['Date'])

            # -----------------------------------------------------------------
            # 5.1 สรุปรอบการประชุม (อังคาร – จันทร์)
            #     FIX: แสดงรอบปัจจุบัน (ที่กำลังเดิน) เป็น default เสมอ
            # -----------------------------------------------------------------
            with st.container(border=True):
                st.write("**📊 สรุปภาพรวมรอบสัปดาห์ (อังคาร – จันทร์)**")

                today = datetime.now().date()
                # หา Tuesday ที่เริ่มรอบปัจจุบัน
                # weekday(): Mon=0, Tue=1, Wed=2, ..., Sun=6
                days_since_tuesday = (today.weekday() - 1) % 7
                current_week_start = today - timedelta(days=days_since_tuesday)

                weeks = []
                for i in range(4):
                    start_d = current_week_start - timedelta(weeks=i)
                    end_d   = start_d + timedelta(days=6)
                    label   = f"{start_d.strftime('%d/%m/%Y')} - {end_d.strftime('%d/%m/%Y')}"
                    if i == 0:
                        label += "  (รอบปัจจุบัน)"
                    weeks.append((label, start_d, end_d))

                selected_idx = st.selectbox(
                    "เลือกรอบสัปดาห์ที่ต้องการดู:",
                    options=range(len(weeks)),
                    format_func=lambda i: weeks[i][0],
                    index=0   # default = รอบปัจจุบันเสมอ
                )
                _, sel_start, sel_end = weeks[selected_idx]

                df_meeting = pd.read_sql(
                    "SELECT Computer_name, Date FROM vpn_logs WHERE Date BETWEEN ? AND ?",
                    conn, params=[str(sel_start), str(sel_end)]
                )

                if not df_meeting.empty:
                    summary_df = (
                        df_meeting.groupby('Computer_name')
                        .size()
                        .reset_index(name='วันที่เข้าใช้งาน (วัน)')
                        .sort_values('วันที่เข้าใช้งาน (วัน)', ascending=False)
                    )
                    st.data_editor(
                        summary_df,
                        column_config={"วันที่เข้าใช้งาน (วัน)": st.column_config.ProgressColumn(
                            f"สถานะ {weeks[selected_idx][0].split('  ')[0]}",
                            format="%d วัน", min_value=0, max_value=7
                        )},
                        use_container_width=True, hide_index=True, disabled=True
                    )
                else:
                    st.info(f"ไม่พบข้อมูลในช่วง {weeks[selected_idx][0]}")

            # -----------------------------------------------------------------
            # 5.2 ตรวจสอบรายวัน
            #     FIX: เลือก ปี → เดือน (ชื่อไทย) → วัน แยกกัน, ซ้ายไปขวา
            # -----------------------------------------------------------------
            with st.container(border=True):
                st.write("**📅 ตรวจสอบรายวัน**")

                c_year, c_month, c_day = st.columns([1, 1.4, 1])

                years_avail = sorted(df_dates['Date_dt'].dt.year.unique(), reverse=True)
                with c_year:
                    sel_year = st.selectbox(
                        "ปี",
                        options=years_avail,
                        format_func=lambda y: str(y + 543)
                    )

                months_avail = sorted(
                    df_dates[df_dates['Date_dt'].dt.year == sel_year]['Date_dt'].dt.month.unique(),
                    reverse=True
                )
                with c_month:
                    sel_month = st.selectbox(
                        "เดือน",
                        options=months_avail,
                        format_func=lambda m: MONTHS_TH[m]
                    )

                days_avail = sorted(
                    df_dates[
                        (df_dates['Date_dt'].dt.year  == sel_year) &
                        (df_dates['Date_dt'].dt.month == sel_month)
                    ]['Date_dt'].dt.day.unique(),
                    reverse=True
                )
                with c_day:
                    sel_day = st.selectbox("วัน", options=days_avail)

                target_date = f"{sel_year}-{sel_month:02d}-{sel_day:02d}"
                df_result = pd.read_sql(
                    "SELECT Computer_name, Local_time FROM vpn_logs WHERE Date = ? ORDER BY Local_time ASC",
                    conn, params=[target_date]
                )

                if not df_result.empty:
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        st.metric("👥 จำนวนพนักงานทั้งหมดที่เข้าใช้งาน VPN", f"{len(df_result)} คน")
                    with col_m2:
                        st.metric("🌅 เวลาที่เข้าใช้งาน VPN แรกสุด", df_result['Local_time'].min())
                    st.dataframe(df_result, use_container_width=True, hide_index=True)
                else:
                    st.info(f"ไม่พบข้อมูลในวันที่ {sel_day} {MONTHS_TH[sel_month]} {sel_year + 543}")

            # -----------------------------------------------------------------
            # 5.3 ส่งออกรายงาน CSV
            # -----------------------------------------------------------------
            with st.container(border=True):
                st.write("**📥 ส่งออกรายงาน (.CSV)**")
                all_dates_raw = sorted(df_dates['Date_dt'].dt.date.unique(), reverse=True)
                date_options  = {d.strftime('%d/%m/%Y'): d.strftime('%Y-%m-%d') for d in all_dates_raw}
                selected_labels = st.multiselect(
                    "เลือกวันที่ต้องการรวมไฟล์:",
                    options=list(date_options.keys())
                )
                if selected_labels:
                    days_query = [date_options[lbl] for lbl in selected_labels]
                    report_df  = pd.read_sql(
                        f"SELECT * FROM vpn_logs WHERE Date IN ({','.join(['?']*len(days_query))})",
                        conn, params=days_query
                    )
                    report_df['Date'] = pd.to_datetime(report_df['Date']).dt.strftime('%d/%m/%Y')
                    st.download_button(
                        "📥 ดาวน์โหลดไฟล์",
                        report_df.to_csv(index=False).encode('utf-8-sig'),
                        "VPN_Report.csv", "text/csv",
                        use_container_width=True
                    )

        else:
            st.info("📢 ยินดีต้อนรับ! ขณะนี้ยังไม่มีข้อมูลในระบบ")

        conn.close()

    except Exception as e:
        st.error(f"⚠️ พบข้อผิดพลาด: {e}")