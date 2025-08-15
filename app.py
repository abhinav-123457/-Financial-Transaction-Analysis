import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import io
import uuid

# ===== Custom CSS Styling =====
st.markdown("""
    <style>
    .main {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
    }
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
        padding: 10px 20px;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    .stFileUploader>label {
        font-size: 16px;
        font-weight: bold;
        color: #333;
    }
    .stDataFrame {
        background-color: white;
        border-radius: 5px;
        padding: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    h1, h2, h3 {
        color: #1f77b4;
        font-family: 'Arial', sans-serif;
    }
    .sidebar .sidebar-content {
        background-color: #ffffff;
        border-right: 1px solid #ddd;
    }
    </style>
""", unsafe_allow_html=True)


# ===== Helper Functions =====
def safe_float(val):
    """Safely convert value to float, handling currency symbols and commas."""
    try:
        if pd.isna(val):
            return 0.0
        if isinstance(val, str):
            val = val.replace(',', '').replace('₹', '').strip()
        return float(val)
    except:
        return 0.0


def parse_date_to_datetime(date_val):
    """Convert date value to datetime object."""
    try:
        if isinstance(date_val, datetime):
            return date_val
        elif isinstance(date_val, (int, float)):  # Excel serial dates
            return datetime(1899, 12, 30) + timedelta(days=int(date_val))
        elif isinstance(date_val, str):
            for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y'):
                try:
                    return datetime.strptime(date_val.strip(), fmt)
                except ValueError:
                    pass
            date = pd.to_datetime(date_val, errors='coerce')
            if pd.notna(date):
                return date.to_pydatetime()
        return None
    except:
        return None


def days_between(date1_obj, date2_obj):
    """Calculate days between two datetime objects."""
    if date1_obj is None or date2_obj is None:
        return 0
    return max((date2_obj - date1_obj).days, 0)


# ===== File Reading =====
@st.cache_data
def read_file_data(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        elif uploaded_file.name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file)
        else:
            st.error("Unsupported file format. Please upload a CSV or Excel file.")
            return None, None, None
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None, None, None

    date_col = next((col for col in df.columns if 'date' in col.lower()), 'Date')
    debit_col = next((col for col in df.columns if 'debit' in col.lower()), 'Debit')
    credit_col = next((col for col in df.columns if 'credit' in col.lower()), 'Credit')
    due_date_col = next((col for col in df.columns if '180 days' in col.lower()), '180 days')
    particulars_col = next((col for col in df.columns if 'particular' in col.lower()), None)

    opening_balance = None
    closing_balance = None
    transactions = []

    for _, row in df.iterrows():
        particulars_val = str(row.get(particulars_col, '')).strip().lower() if particulars_col else ''
        if particulars_val == "opening balance":
            opening_balance = safe_float(row.get(debit_col) or row.get(credit_col))
            continue
        if particulars_val == "closing balance":
            closing_balance = safe_float(row.get(debit_col) or row.get(credit_col))
            continue

        date_obj = parse_date_to_datetime(row.get(date_col))
        due_date_obj = parse_date_to_datetime(row.get(due_date_col))

        if date_obj is None or due_date_obj is None:
            continue

        debit = safe_float(row.get(debit_col))
        credit = safe_float(row.get(credit_col))

        transactions.append({
            'Date': date_obj,
            'Debit': debit,
            'Credit': credit,
            'Due_Date': due_date_obj,
            'Original_Date_Str': str(row.get(date_col)),
            'Original_Due_Date_Str': str(row.get(due_date_col))
        })
    return transactions, opening_balance, closing_balance


# ===== Balance Calculation =====
@st.cache_data
def calculate_balances(transactions):
    if not transactions:
        return [], [], 0, 0, 0, 0, 0, 0, datetime.now()

    last_date = max(t['Date'] for t in transactions)
    target_date = last_date.replace(hour=16, minute=43, second=0, microsecond=0)

    credits = []
    debits = []
    total_credits = 0
    total_debits = 0
    daily_rate = 0.18  # 18% daily interest

    for row in transactions:
        if row['Credit'] > 0:
            credits.append({
                'date': row['Date'],
                'amount': row['Credit'],
                'due_date': row['Due_Date'],
                'original_date': row['Original_Date_Str'],
                'original_due_date': row['Original_Due_Date_Str']
            })
            total_credits += row['Credit']
        if row['Debit'] > 0:
            debits.append({
                'date': row['Date'],
                'amount': row['Debit'],
                'remaining': row['Debit'],
                'original_date': row['Original_Date_Str']
            })
            total_debits += row['Debit']

    credits.sort(key=lambda x: x['date'])
    debits.sort(key=lambda x: x['date'])

    overdue_with_interest = []
    pending_credits = []
    total_principal = 0
    total_interest = 0

    for credit in credits:
        credit_amount = credit['amount']
        remaining_principal = credit_amount
        matched_debits = []

        # Match debits before due date
        for debit in debits:
            if debit['remaining'] > 0 and credit['date'] <= debit['date'] <= credit['due_date']:
                alloc = min(remaining_principal, debit['remaining'])
                matched_debits.append({'payment_date': debit['date'], 'allocated': alloc})
                debit['remaining'] -= alloc
                remaining_principal -= alloc

        paid_by_due_date = sum(m['allocated'] for m in matched_debits)
        unpaid_at_due = credit_amount - paid_by_due_date

        # No overdue
        if unpaid_at_due <= 0:
            continue

        balance = unpaid_at_due
        current_date = credit['due_date']
        interest = 0

        # Match late payments
        for debit in debits:
            if debit['remaining'] > 0 and debit['date'] > credit['due_date']:
                days = days_between(current_date, debit['date'])
                interest += balance * daily_rate * days
                alloc = min(balance, debit['remaining'])
                debit['remaining'] -= alloc
                balance -= alloc
                current_date = debit['date']
                if balance <= 0:
                    break

        # Still unpaid until target date
        if balance > 0:
            days = days_between(current_date, target_date)
            interest += balance * daily_rate * days

        total_principal += balance
        total_interest += interest
        overdue_with_interest.append({
            'credit_date': credit['original_date'],
            'credit_amount': credit_amount,
            'due_date': credit['original_due_date'],
            'unpaid_amount': balance,
            'interest': interest,
            'total_with_interest': balance + interest
        })

    gst = 0.18 * total_interest
    total_amount_due = total_principal + total_interest + gst

    return overdue_with_interest, pending_credits, total_credits, total_debits, total_principal, total_interest, gst, total_amount_due, target_date


# ===== Excel Report =====
def generate_excel(overdue_with_interest, pending_credits, opening_balance, closing_balance,
                   total_credits, total_debits, total_principal, total_interest, gst, total_amount_due, target_date):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(overdue_with_interest).to_excel(writer, sheet_name='Overdue Amounts', index=False)
        pd.DataFrame(pending_credits).to_excel(writer, sheet_name='Pending Credits', index=False)
        summary_df = pd.DataFrame([
            {'Category': 'Opening Balance', 'Amount': opening_balance},
            {'Category': 'Total Credits Processed', 'Amount': total_credits},
            {'Category': 'Total Debits Processed', 'Amount': total_debits},
            {'Category': 'Total Principal Due', 'Amount': total_principal},
            {'Category': 'Total Interest Accrued', 'Amount': total_interest},
            {'Category': 'GST (18% on Interest)', 'Amount': gst},
            {'Category': 'Total Amount Due', 'Amount': total_amount_due}
        ])
        summary_df.to_excel(writer, sheet_name='Balance Summary', index=False)
    output.seek(0)
    return output


# ===== Streamlit App =====
def main():
    st.title("Financial Transaction Analysis")
    st.sidebar.header("Upload File")
    uploaded_file = st.sidebar.file_uploader("Choose a file", type=["csv", "xlsx", "xls"])

    if uploaded_file:
        transactions, opening_balance, closing_balance = read_file_data(uploaded_file)
        if not transactions:
            st.error("No valid transaction data found.")
            return

        overdue_with_interest, pending_credits, total_credits, total_debits, total_principal, total_interest, gst, total_amount_due, target_date = calculate_balances(transactions)

        st.metric("Principal Due", f"₹{total_principal:,.2f}")
        st.metric("Interest Accrued", f"₹{total_interest:,.2f}")
        st.metric("GST (18%)", f"₹{gst:,.2f}")
        st.metric("Total Amount Due", f"₹{total_amount_due:,.2f}")

        if overdue_with_interest:
            st.subheader("Overdue Credits")
            st.dataframe(pd.DataFrame(overdue_with_interest))

        excel_file = generate_excel(overdue_with_interest, pending_credits, opening_balance, closing_balance,
                                    total_credits, total_debits, total_principal, total_interest, gst, total_amount_due, target_date)
        st.download_button("Download Excel Report", data=excel_file,
                           file_name=f"credit_debit_analysis_{uuid.uuid4().hex[:8]}.xlsx")


if __name__ == "__main__":
    main()
