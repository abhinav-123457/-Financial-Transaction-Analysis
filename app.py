import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import io
import base64
import plotly.express as px

# Custom CSS for enhanced styling
st.markdown("""
    <style>
    .main {
        background: linear-gradient(135deg, #e6f0fa, #f5f9fc);
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 6px 15px rgba(0,0,0,0.1);
        max-width: 1200px;
        margin: 0 auto;
    }
    .stButton>button {
        background: linear-gradient(90deg, #2ecc71, #27ae60);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 12px 30px;
        font-weight: bold;
        font-size: 16px;
        transition: transform 0.2s, background 0.2s;
    }
    .stButton>button:hover {
        transform: scale(1.05);
        background: linear-gradient(90deg, #27ae60, #219653);
    }
    .stFileUploader>label {
        font-size: 18px;
        font-weight: bold;
        color: #34495e;
        background-color: #ecf0f1;
        padding: 12px;
        border-radius: 8px;
        display: flex;
        align-items: center;
    }
    .stFileUploader>label:before {
        content: "📥 ";
    }
    .stDataFrame {
        background-color: #ffffff;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        font-size: 14px;
    }
    h1, h2, h3 {
        color: #34495e;
        font-family: 'Helvetica', sans-serif;
        text-align: center;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }
    .sidebar .sidebar-content {
        background: linear-gradient(135deg, #ffffff, #f8fafc);
        border-right: 2px solid #bdc3c7;
        padding: 25px;
        border-radius: 10px 0 0 10px;
    }
    .stMetric {
        background-color: rgb(38, 39, 48);
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# Backend logic
# ... (Keep existing imports and CSS)

# Backend logic (unchanged except for interest rate and progress)
def process_credit_debit_data(data, custom_rate=None):
    if not data:
        return [], [], 0, 0, None
    credits = []
    debits = []
    total_credits = 0
    total_debits = 0
    for row in data:
        date = datetime.strptime(row['Date'], '%d-%m-%Y')
        due_date = datetime.strptime(row['Due_Date'], '%d-%m-%Y')
        if date is None or due_date is None:
            continue
        if row['Credit'] > 0:
            credits.append({
                'date': date,
                'amount': row['Credit'],
                'original_date': row['Date'],
                'due_date': due_date,
                'original_due_date': row['Due_Date']
            })
            total_credits += row['Credit']
        if row['Debit'] > 0:
            debits.append({
                'date': date,
                'amount': row['Debit'],
                'remaining': row['Debit'],
                'original_date': row['Date']
            })
            total_debits += row['Debit']
    credits.sort(key=lambda x: x['date'])
    debits.sort(key=lambda x: x['date'])
    overdue_with_interest = []
    pending_credits = []
    valid_dates = [datetime.strptime(row['Date'], '%d-%m-%Y') for row in data if parse_date(row['Date']) is not None]
    if valid_dates:
        last_date_in_data = max(valid_dates)
    else:
        raise ValueError("No valid dates found in the data")
    target_date = last_date_in_data.replace(hour=16, minute=59, second=0, microsecond=0)  # 04:59 PM IST
    daily_rate = custom_rate if custom_rate else 0.18 * 0.18  # Use custom rate or default 3.24%
    for i, credit in enumerate(credits, 1):
        # Progress bar update
        st.progress(i / len(credits))
        credit_date = credit['date']
        due_date = credit['due_date']
        credit_amount = credit['amount']
        remaining_principal = credit_amount
        matched_debits = []
        for debit in debits:
            if debit['remaining'] <= 0 or debit['date'] < credit_date:
                continue
            avail = debit['remaining']
            alloc = min(remaining_principal, avail)
            matched_debits.append({
                'payment_date': debit['date'],
                'allocated': alloc,
                'original_date': debit['original_date']
            })
            debit['remaining'] -= alloc
            remaining_principal -= alloc
        paid_on_time = sum(match['allocated'] for match in matched_debits if match['payment_date'] <= due_date)
        late_payments = [match for match in matched_debits if match['payment_date'] > due_date]
        unpaid_at_due = credit_amount - paid_on_time
        if unpaid_at_due <= 0:
            if remaining_principal > 0:
                days_remaining = max((due_date - target_date).days, 0)
                pending_credits.append({
                    'credit_date': credit['original_date'],
                    'credit_amount': credit_amount,
                    'due_date': credit['original_due_date'],
                    'unpaid_amount': remaining_principal,
                    'days_remaining': days_remaining,
                    'matched_debits': matched_debits
                })
            continue
        balance = unpaid_at_due
        current_date = due_date
        interest = 0.0
        for late in late_payments:
            days = max((late['payment_date'] - current_date).days, 0)
            interest += unpaid_at_due * daily_rate * days
            balance -= late['allocated']
            current_date = late['payment_date']
            if balance <= 0:
                break
        if balance > 0:
            days = max((target_date - current_date).days, 0)
            interest += unpaid_at_due * daily_rate * days
        total_due = balance + interest
        overdue_with_interest.append({
            'credit_date': credit['original_date'],
            'credit_amount': credit_amount,
            'due_date': credit['original_due_date'],
            'unpaid_amount': balance,
            'interest': interest,
            'total_with_interest': total_due,
            'matched_debits': matched_debits
        })
    return overdue_with_interest, pending_credits, total_credits, total_debits, target_date

# Streamlit frontend (partial update)
def main():
    st.set_page_config(page_title="Credit-Debit Analysis Tool", layout="wide")
    st.title("Credit-Debit Analysis Tool")
    st.markdown("Upload an Excel file to analyze credit and debit transactions, calculate interest (customizable rate on overdue amounts), and download the results. *Last updated: 04:59 PM IST, August 15, 2025*")

    # Sidebar for custom inputs
    st.sidebar.header("Settings")
    custom_rate = st.sidebar.slider("Custom Interest Rate (% of 18% daily)", 0.0, 100.0, 100.0, 0.1) / 100 * 0.18
    target_date_override = st.sidebar.date_input("Override Target Date", value=None)

    # File uploader
    uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"])

    if uploaded_file is not None:
        xl = pd.ExcelFile(uploaded_file)
        sheet_names = xl.sheet_names
        sheet_name = st.selectbox("Select Sheet", ["First Sheet"] + sheet_names, index=0)
        sheet = 0 if sheet_name == "First Sheet" else sheet_name

        if st.button("Process Transactions"):
            try:
                uploaded_file.seek(0)
                transaction_data, opening_balance, closing_balance = read_excel_data(uploaded_file, sheet)
                
                if not transaction_data:
                    st.error("No valid transaction data found in the file.")
                    return
                
                st.success(f"Successfully loaded {len(transaction_data)} transactions.")
                
                with st.spinner("Processing data..."):
                    overdue_amounts, pending_credits, total_credits, total_debits, target_date = process_credit_debit_data(transaction_data, custom_rate if custom_rate else None)
                    if target_date_override:
                        target_date = datetime.combine(target_date_override, datetime.min.time()).replace(hour=16, minute=59, second=0)
                    output_buffer = display_results(overdue_amounts, pending_credits, opening_balance, closing_balance, total_credits, total_debits, target_date)
                
                # ... (Keep existing summary, pie chart, and result display logic)
                # Add line chart for trends
                st.header("Transaction Trends")
                dates = [datetime.strptime(t['Date'], '%d-%m-%Y') for t in transaction_data]
                credits = [t['Credit'] for t in transaction_data if t['Credit'] > 0]
                debits = [t['Debit'] for t in transaction_data if t['Debit'] > 0]
                trend_data = pd.DataFrame({'Date': dates, 'Credits': credits, 'Debits': debits})
                trend_data = trend_data.groupby(trend_data['Date'].dt.to_period('M').astype(str)).sum().reset_index()
                trend_data['Date'] = pd.to_datetime(trend_data['Date'])
                fig = px.line(trend_data, x='Date', y=['Credits', 'Debits'], title="Credit and Debit Trends")
                st.plotly_chart(fig, use_container_width=True)

            except Exception as e:
                st.error(f"Error processing file: {str(e)}")
    else:
        st.info("Please upload an Excel file to begin.")

if __name__ == "__main__":
    main()
