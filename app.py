import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch
import io
import os

# ---------------------------
# Database setup
# ---------------------------
DB_PATH = "flex_tax.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS income (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        amount REAL,
        description TEXT,
        tax_year TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS mileage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        miles REAL,
        start_location TEXT,
        end_location TEXT,
        purpose TEXT,
        tax_year TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        amount REAL,
        category TEXT,
        description TEXT,
        tax_year TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH)

def get_setting(key, default=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# ---------------------------
# Tax helpers
# ---------------------------
def get_tax_year(d=None):
    if d is None:
        d = date.today()
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    year = d.year
    if d.month < 4 or (d.month == 4 and d.day < 6):
        return f"{year-1}/{str(year)[2:]}"
    return f"{year}/{str(year+1)[2:]}"

def calculate_mileage_claim(miles_list, tax_year):
    """Calculate HMRC simplified mileage claim with correct banding"""
    total_claim = 0.0
    cumulative = 0.0
    first_rate = 0.55 if tax_year >= "2026/27" else 0.45
    for m in miles_list:
        if cumulative >= 10000:
            total_claim += m * 0.25
        else:
            at_first = min(m, 10000 - cumulative)
            at_second = m - at_first
            total_claim += at_first * first_rate + at_second * 0.25
        cumulative += m
    return total_claim, cumulative

def calculate_tax(profit):
    """Simple estimate for England/Wales/NI 2026/27"""
    pa = 12570
    basic_limit = 50270
    higher_limit = 125140
    taxable = max(0, profit - pa)
    income_tax = 0.0
    if taxable > 0:
        basic = min(taxable, basic_limit - pa)
        income_tax += basic * 0.20
        remaining = taxable - basic
        if remaining > 0:
            higher = min(remaining, higher_limit - basic_limit)
            income_tax += higher * 0.40
            remaining -= higher
            if remaining > 0:
                income_tax += remaining * 0.45
    # Class 4 NI
    class4 = 0.0
    if profit > 12570:
        band1 = min(profit, 50270) - 12570
        class4 += band1 * 0.06
        if profit > 50270:
            class4 += (profit - 50270) * 0.02
    return income_tax, class4, income_tax + class4

# ---------------------------
# App
# ---------------------------
st.set_page_config(page_title="Amazon Flex Tax Tracker", page_icon="🚚", layout="wide")

init_db()

st.title("🚚 Amazon Flex Tax & Mileage Tracker")
st.caption("Personal tool for UK sole traders • Tracks income, mileage (HMRC rates) & expenses • Generates reports for Self Assessment / accountant")

# Sidebar
st.sidebar.header("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Log Income", "Log Mileage", "Log Expenses", "Reports & Export", "Settings"])

tax_year = st.sidebar.selectbox("Tax Year", ["2026/27", "2025/26", "2024/25"], index=0)
st.sidebar.info(f"Current tax year selected: **{tax_year}**\n\nMileage rate: **{'55p' if tax_year >= '2026/27' else '45p'}** first 10,000 miles, then 25p.")

# ---------------------------
# Dashboard
# ---------------------------
if page == "Dashboard":
    st.header("Dashboard")
    
    conn = get_conn()
    income_df = pd.read_sql_query("SELECT * FROM income WHERE tax_year=?", conn, params=(tax_year,))
    mileage_df = pd.read_sql_query("SELECT * FROM mileage WHERE tax_year=? ORDER BY date", conn, params=(tax_year,))
    expenses_df = pd.read_sql_query("SELECT * FROM expenses WHERE tax_year=?", conn, params=(tax_year,))
    conn.close()
    
    total_income = income_df["amount"].sum() if not income_df.empty else 0.0
    miles_list = mileage_df["miles"].tolist() if not mileage_df.empty else []
    mileage_claim, total_miles = calculate_mileage_claim(miles_list, tax_year)
    total_expenses = expenses_df["amount"].sum() if not expenses_df.empty else 0.0
    profit = total_income - mileage_claim - total_expenses
    it, c4, total_tax = calculate_tax(profit)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Income", f"£{total_income:,.2f}")
    col2.metric("Mileage Claim", f"£{mileage_claim:,.2f}", f"{total_miles:,.1f} miles")
    col3.metric("Other Expenses", f"£{total_expenses:,.2f}")
    col4.metric("Estimated Profit", f"£{profit:,.2f}")
    
    st.subheader("Tax Estimate (simplified)")
    tcol1, tcol2, tcol3 = st.columns(3)
    tcol1.metric("Income Tax", f"£{it:,.2f}")
    tcol2.metric("Class 4 NI", f"£{c4:,.2f}")
    tcol3.metric("Total Tax to Set Aside", f"£{total_tax:,.2f}")
    
    st.info("⚠️ This is an **estimate only**. Personal Allowance £12,570 • Class 4 NI 6%/2% • Does not include Payments on Account, student loans, or other income. Always verify with HMRC or an accountant.")
    
    if not income_df.empty or not mileage_df.empty:
        st.subheader("Recent Activity")
        if not income_df.empty:
            st.write("**Latest Income**")
            st.dataframe(income_df.sort_values("date", ascending=False).head(5), use_container_width=True)
        if not mileage_df.empty:
            st.write("**Latest Mileage**")
            st.dataframe(mileage_df.sort_values("date", ascending=False).head(5), use_container_width=True)

# ---------------------------
# Log Income
# ---------------------------
elif page == "Log Income":
    st.header("Log Amazon Flex Income")
    with st.form("income_form"):
        d = st.date_input("Date", value=date.today())
        amount = st.number_input("Amount received (£)", min_value=0.0, step=0.01, format="%.2f")
        desc = st.text_input("Description / Block notes", placeholder="e.g. Flex block 4h – Station XYZ")
        submitted = st.form_submit_button("Add Income")
        if submitted and amount > 0:
            conn = get_conn()
            c = conn.cursor()
            c.execute("INSERT INTO income (date, amount, description, tax_year) VALUES (?, ?, ?, ?)",
                      (d.isoformat(), amount, desc, tax_year))
            conn.commit()
            conn.close()
            st.success(f"Added £{amount:.2f} for {d}")
    
    st.subheader("Income Log")
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM income WHERE tax_year=? ORDER BY date DESC", conn, params=(tax_year,))
    conn.close()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        del_id = st.number_input("ID to delete", min_value=0, step=1)
        if st.button("Delete Income Entry") and del_id > 0:
            conn = get_conn()
            conn.execute("DELETE FROM income WHERE id=?", (del_id,))
            conn.commit()
            conn.close()
            st.success("Deleted")
            st.rerun()
    else:
        st.info("No income logged yet for this tax year.")

# ---------------------------
# Log Mileage
# ---------------------------
elif page == "Log Mileage":
    st.header("Log Mileage")
    st.write("Record business miles for Amazon Flex blocks. HMRC requires date, purpose, and distance.")
    
    with st.form("mileage_form"):
        d = st.date_input("Date", value=date.today())
        miles = st.number_input("Miles driven", min_value=0.0, step=0.1, format="%.1f")
        start = st.text_input("Start location", placeholder="e.g. Home / Depot / Warehouse")
        end = st.text_input("End location", placeholder="e.g. Last drop / Depot")
        purpose = st.text_input("Purpose", value="Amazon Flex delivery block")
        submitted = st.form_submit_button("Add Mileage")
        if submitted and miles > 0:
            conn = get_conn()
            c = conn.cursor()
            c.execute("INSERT INTO mileage (date, miles, start_location, end_location, purpose, tax_year) VALUES (?, ?, ?, ?, ?, ?)",
                      (d.isoformat(), miles, start, end, purpose, tax_year))
            conn.commit()
            conn.close()
            st.success(f"Added {miles} miles on {d}")
    
    st.subheader("Mileage Log")
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM mileage WHERE tax_year=? ORDER BY date DESC", conn, params=(tax_year,))
    conn.close()
    if not df.empty:
        claim, total_m = calculate_mileage_claim(df.sort_values("date")["miles"].tolist(), tax_year)
        st.metric("Total Miles this year", f"{total_m:,.1f}", f"Claim value: £{claim:,.2f}")
        st.dataframe(df, use_container_width=True)
        del_id = st.number_input("Mileage ID to delete", min_value=0, step=1, key="mil_del")
        if st.button("Delete Mileage Entry") and del_id > 0:
            conn = get_conn()
            conn.execute("DELETE FROM mileage WHERE id=?", (del_id,))
            conn.commit()
            conn.close()
            st.success("Deleted")
            st.rerun()
    else:
        st.info("No mileage logged yet.")

# ---------------------------
# Log Expenses
# ---------------------------
elif page == "Log Expenses":
    st.header("Log Other Expenses")
    st.write("Phone, parking, equipment, bags, insurance portion, etc. (Do **not** claim these if using simplified mileage for the vehicle.)")
    
    categories = ["Phone / Data", "Parking / Tolls", "Equipment / Bags", "Insurance (business portion)", "Other"]
    with st.form("expense_form"):
        d = st.date_input("Date", value=date.today())
        amount = st.number_input("Amount (£)", min_value=0.0, step=0.01, format="%.2f")
        cat = st.selectbox("Category", categories)
        desc = st.text_input("Description / Notes")
        submitted = st.form_submit_button("Add Expense")
        if submitted and amount > 0:
            conn = get_conn()
            c = conn.cursor()
            c.execute("INSERT INTO expenses (date, amount, category, description, tax_year) VALUES (?, ?, ?, ?, ?)",
                      (d.isoformat(), amount, cat, desc, tax_year))
            conn.commit()
            conn.close()
            st.success(f"Added £{amount:.2f} ({cat})")
    
    st.subheader("Expenses Log")
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM expenses WHERE tax_year=? ORDER BY date DESC", conn, params=(tax_year,))
    conn.close()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        del_id = st.number_input("Expense ID to delete", min_value=0, step=1, key="exp_del")
        if st.button("Delete Expense Entry") and del_id > 0:
            conn = get_conn()
            conn.execute("DELETE FROM expenses WHERE id=?", (del_id,))
            conn.commit()
            conn.close()
            st.success("Deleted")
            st.rerun()
    else:
        st.info("No expenses logged yet.")

# ---------------------------
# Reports
# ---------------------------
elif page == "Reports & Export":
    st.header("Reports & Export")
    
    conn = get_conn()
    income_df = pd.read_sql_query("SELECT * FROM income WHERE tax_year=? ORDER BY date", conn, params=(tax_year,))
    mileage_df = pd.read_sql_query("SELECT * FROM mileage WHERE tax_year=? ORDER BY date", conn, params=(tax_year,))
    expenses_df = pd.read_sql_query("SELECT * FROM expenses WHERE tax_year=? ORDER BY date", conn, params=(tax_year,))
    conn.close()
    
    total_income = income_df["amount"].sum() if not income_df.empty else 0.0
    miles_list = mileage_df["miles"].tolist() if not mileage_df.empty else []
    mileage_claim, total_miles = calculate_mileage_claim(miles_list, tax_year)
    total_expenses = expenses_df["amount"].sum() if not expenses_df.empty else 0.0
    profit = total_income - mileage_claim - total_expenses
    it, c4, total_tax = calculate_tax(profit)
    
    st.subheader("Summary for " + tax_year)
    st.write(f"""
    - **Gross Income**: £{total_income:,.2f}
    - **Mileage Claim** ({total_miles:,.1f} miles): £{mileage_claim:,.2f}
    - **Other Expenses**: £{total_expenses:,.2f}
    - **Taxable Profit (estimate)**: £{profit:,.2f}
    - **Estimated Income Tax**: £{it:,.2f}
    - **Estimated Class 4 NI**: £{c4:,.2f}
    - **Total estimated tax**: £{total_tax:,.2f}
    """)
    
    # PDF Generation
    def create_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        elements = []
        
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12)
        elements.append(Paragraph(f"Amazon Flex Tax Summary – {tax_year}", title_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 12))
        
        elements.append(Paragraph("<b>Summary</b>", styles['Heading2']))
        summary_data = [
            ["Gross Income", f"£{total_income:,.2f}"],
            ["Business Miles", f"{total_miles:,.1f}"],
            ["Mileage Claim (HMRC simplified)", f"£{mileage_claim:,.2f}"],
            ["Other Allowable Expenses", f"£{total_expenses:,.2f}"],
            ["Estimated Taxable Profit", f"£{profit:,.2f}"],
            ["Estimated Income Tax", f"£{it:,.2f}"],
            ["Estimated Class 4 NI", f"£{c4:,.2f}"],
            ["Total Estimated Tax Liability", f"£{total_tax:,.2f}"],
        ]
        t = Table(summary_data, colWidths=[3.5*inch, 2*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 20))
        
        if not mileage_df.empty:
            elements.append(Paragraph("<b>Mileage Log</b>", styles['Heading2']))
            mil_data = [["Date", "Miles", "From", "To", "Purpose"]] + \
                       [[row['date'], f"{row['miles']:.1f}", row['start_location'] or "", row['end_location'] or "", row['purpose'] or ""] 
                        for _, row in mileage_df.iterrows()]
            mt = Table(mil_data, colWidths=[1*inch, 0.7*inch, 1.3*inch, 1.3*inch, 2*inch])
            mt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ]))
            elements.append(mt)
            elements.append(Spacer(1, 12))
        
        if not income_df.empty:
            elements.append(Paragraph("<b>Income Log</b>", styles['Heading2']))
            inc_data = [["Date", "Amount", "Description"]] + \
                       [[row['date'], f"£{row['amount']:.2f}", row['description'] or ""] for _, row in income_df.iterrows()]
            itable = Table(inc_data, colWidths=[1.2*inch, 1*inch, 4*inch])
            itable.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ]))
            elements.append(itable)
            elements.append(Spacer(1, 12))
        
        if not expenses_df.empty:
            elements.append(Paragraph("<b>Other Expenses</b>", styles['Heading2']))
            exp_data = [["Date", "Category", "Amount", "Description"]] + \
                       [[row['date'], row['category'], f"£{row['amount']:.2f}", row['description'] or ""] for _, row in expenses_df.iterrows()]
            et = Table(exp_data, colWidths=[1*inch, 1.5*inch, 1*inch, 2.5*inch])
            et.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightyellow),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ]))
            elements.append(et)
        
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<i>This is a personal record generated for Self Assessment / accountant use. It is not an official HMRC submission. Verify all figures. Mileage uses HMRC simplified expenses rates.</i>", styles['Normal']))
        
        doc.build(elements)
        buffer.seek(0)
        return buffer
    
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Generate PDF Report"):
            pdf_buffer = create_pdf()
            st.download_button(
                label="Download PDF Summary",
                data=pdf_buffer,
                file_name=f"Flex_Tax_Summary_{tax_year.replace('/', '-')}.pdf",
                mime="application/pdf"
            )
    
    with col_b:
        if st.button("Prepare Excel Export"):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                income_df.to_excel(writer, sheet_name='Income', index=False)
                mileage_df.to_excel(writer, sheet_name='Mileage', index=False)
                expenses_df.to_excel(writer, sheet_name='Expenses', index=False)
                summary = pd.DataFrame({
                    "Item": ["Gross Income", "Total Miles", "Mileage Claim", "Other Expenses", "Taxable Profit", "Income Tax Est.", "Class 4 NI Est.", "Total Tax Est."],
                    "Amount": [total_income, total_miles, mileage_claim, total_expenses, profit, it, c4, total_tax]
                })
                summary.to_excel(writer, sheet_name='Summary', index=False)
            output.seek(0)
            st.download_button(
                label="Download Excel Workbook",
                data=output,
                file_name=f"Flex_Tax_Data_{tax_year.replace('/', '-')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    st.success("Use the PDF or Excel with your accountant or when completing Self Assessment.")

# ---------------------------
# Settings
# ---------------------------
elif page == "Settings":
    st.header("Settings")
    st.write("This is a local personal tool. Data is stored in `flex_tax.db` in the same folder as the app.")
    st.markdown("""
    - Keep records contemporaneous (log soon after the trip/block).
    - Business miles: depot/warehouse to deliveries and between stops are generally allowable. Home-to-depot is often commuting – check your situation.
    - Simplified mileage covers fuel, insurance, servicing, depreciation etc. Do **not** also claim actual vehicle costs.
    - This tool does **not** submit to HMRC.
    """)
    
    if st.button("Reset all data for current tax year (careful!)"):
        conn = get_conn()
        conn.execute("DELETE FROM income WHERE tax_year=?", (tax_year,))
        conn.execute("DELETE FROM mileage WHERE tax_year=?", (tax_year,))
        conn.execute("DELETE FROM expenses WHERE tax_year=?", (tax_year,))
        co
