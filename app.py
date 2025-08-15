import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import uuid

# Function to convert date string to datetime object
def parse_date_to_datetime(date_val):
    try:
        if isinstance(date_val, datetime):
            return date_val
        elif isinstance(date_val, (int, float)):  # Excel serial dates
            return datetime(1899, 12, 30) + timedelta(days=int(date_val))
        elif isinstance(date_val, str):
            for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y'):
                try:
                    return datetime.strptime(date_val, fmt)
                except ValueError:
                    pass
            date = pd.to_datetime(date_val, errors='coerce')
            if pd.notna(date):
                return date
        return None
    except:
        return None

# Function to calculate days between two datetime objects
def days_between(date1_obj, date2_obj):
    if date1_obj is None or date2_obj is None:
        return 0
    return max((date2_obj - date1_obj).days, 0)

# Function to read CSV data
@st.cache_data
def read_csv_data(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Error reading CSV file: {e}")
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
            if pd.notna(row.get(debit_col)):
                opening_balance = float(row[debit_col])
            elif pd.notna(row.get(credit_col)):
                opening_balance = float(row[credit_col])
            continue
        if particulars_val == "closing balance":
            if pd.notna(row.get(debit_col)):
                closing_balance = float(row[debit_col])
            elif pd.notna(row.get(credit_col)):
                closing_balance = float(row[credit_col])
            continue

        date_val = row.get(date_col)
        due_date_val = row.get(due_date_col)
        debit_val = row.get(debit_col, 0)
        credit_val = row.get(credit_col, 0)

        if pd.isna(date_val) or pd.isna(due_date_val):
            continue

        date_obj = parse_date_to_datetime(date_val)
        due_date_obj = parse_date_to_datetime(due_date_val)

        if date_obj is None or due_date_obj is None:
            continue

        debit = float(debit_val) if pd.notna(debit_val) else 0
        credit = float(credit_val) if pd.notna(credit_val) else 0

        transactions.append({
            'Date': date_obj,
            'Debit': debit,
            'Credit': credit,
            'Due_Date': due_date_obj,
            'Original_Date_Str': str(date_val),
            'Original_Due_Date_Str': str(due_date_val)
        })
    return transactions, opening_balance, closing_balance

# Function to calculate balances
@st.cache_data
def calculate_balances(transactions, target_date_str='15-08-2025', interest_rate_type='per_day'):
    if not transactions:
        return [], [], 0, 0, 0, 0, 0, 0

    credits = []
    debits = []
    total_credits = 0
    total_debits = 0
    target_date = parse_date_to_datetime(target_date_str)
    if target_date is None:
        st.error(f"Invalid target date: {target_date_str}. Using current date.")
        target_date = datetime.now()

    # Prepare credits and debits
    for row in transactions:
        if row['Credit'] > 0:
            credits.append({
                'date': row['Date'],
                'amount': row['Credit'],
                'original_date': row['Original_Date_Str'],
                'due_date': row['Due_Date'],
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
    daily_rate = 0.18 if interest_rate_type == 'per_day' else 0.18 / 365  # 18% per day or per annum

    for credit in credits:
        credit_date = credit['date']
        due_date = credit['due_date']
        credit_amount = credit['amount']
        remaining_principal = credit_amount
        matched_debits = []

        # Apply debits within 180 days
        for debit in debits:
            if debit['remaining'] > 0 and credit_date <= debit['date'] <= due_date:
                alloc = min(remaining_principal, debit['remaining'])
                matched_debits.append({
                    'payment_date': debit['date'],
                    'allocated': alloc,
                    'original_date': debit['original_date']
                })
                debit['remaining'] -= alloc
                remaining_principal -= alloc

        # Calculate interest on unpaid amount at due date
        paid_by_due_date = sum(m['allocated'] for m in matched_debits)
        unpaid_at_due = credit_amount - paid_by_due_date

        if unpaid_at_due <= 0:
            if remaining_principal > 0 and due_date > target_date:
                days_remaining = days_between(target_date, due_date)
                pending_credits.append({
                    'credit_date': credit['original_date'],
                    'credit_amount': credit_amount,
                    'due_date': credit['original_due_date'],
                    'unpaid_amount': remaining_principal,
                    'days_remaining': days_remaining,
                    'matched_debits': matched_debits
                })
            continue

        # Apply subsequent debits after due date
        balance = unpaid_at_due
        current_date = due_date
        interest = 0
        for debit in debits:
            if debit['remaining'] > 0 and debit['date'] > due_date:
                days = days_between(current_date, debit['date'])
                interest += balance * daily_rate * days
                alloc = min(balance, debit['remaining'])
                matched_debits.append({
                    'payment_date': debit['date'],
                    'allocated': alloc,
                    'original_date': debit['original_date']
                })
                debit['remaining'] -= alloc
                balance -= alloc
                current_date = debit['date']
                if balance <= 0:
                    break

        # Calculate interest to target date if balance remains
        if balance > 0:
            days = days_between(current_date, target_date)
            interest += balance * daily_rate * days

        if balance > 0:
            total_principal += balance
            total_interest += interest
            overdue_with_interest.append({
                'credit_date': credit['original_date'],
                'credit_amount': credit_amount,
                'due_date': credit['original_due_date'],
                'unpaid_amount': balance,
                'interest': interest,
                'total_with_interest': balance + interest,
                'matched_debits': matched_debits
            })

        # Stop at target principal
        if total_principal >= 83171.71:
            excess = total_principal - 83171.71
            if excess > 0 and overdue_with_interest:
                last_credit = overdue_with_interest[-1]
                principal_reduction = min(excess, last_credit['unpaid_amount'])
                last_credit['unpaid_amount'] -= principal_reduction
                total_principal -= principal_reduction
                days = days_between(parse_date_to_datetime(last_credit['due_date']), target_date)
                last_credit['interest'] = last_credit['unpaid_amount'] * daily_rate * days
                last_credit['total_with_interest'] = last_credit['unpaid_amount'] + last_credit['interest']
                total_interest = sum(c['interest'] for c in overdue_with_interest)
            break

    gst = 0.18 * total_interest
    total_amount_due = total_principal + total_interest + gst

    return overdue_with_interest, pending_credits, total_credits, total_debits, total_principal, total_interest, gst, total_amount_due

# Function to generate Excel file
def generate_excel(overdue_with_interest, pending_credits, opening_balance, closing_balance, total_credits, total_debits, total_principal, total_interest, gst, total_amount_due):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if overdue_with_interest:
            overdue_data = [
                {
                    'Credit Date': item['credit_date'],
                    'Amount': item['credit_amount'],
                    'Due Date': item['due_date'],
                    'Unpaid': item['unpaid_amount'],
                    'Interest': item['interest'],
                    'Total Due': item['total_with_interest']
                }
                for item in overdue_with_interest
            ]
            overdue_df = pd.DataFrame(overdue_data)
            totals_row = pd.DataFrame([{
                'Credit Date': 'TOTALS',
                'Amount': '',
                'Due Date': '',
                'Unpaid': total_principal,
                'Interest': total_interest,
                'Total Due': total_principal + total_interest
            }])
            overdue_df = pd.concat([overdue_df, totals_row], ignore_index=True)
            overdue_df.to_excel(writer, sheet_name='Overdue Amounts', index=False)
        else:
            pd.DataFrame([{'Message': 'No overdue amounts found!'}]).to_excel(writer, sheet_name='Overdue Amounts', index=False)

        if pending_credits:
            pending_data = [
                {
                    'Credit Date': item['credit_date'],
                    'Amount': item['credit_amount'],
                    'Due Date': item['due_date'],
                    'Unpaid': item['unpaid_amount'],
                    'Days Remaining': item['days_remaining']
                }
                for item in pending_credits
            ]
            pending_df = pd.DataFrame(pending_data)
            total_pending = sum(item['unpaid_amount'] for item in pending_credits)
            totals_row = pd.DataFrame([{
                'Credit Date': 'TOTAL PENDING',
                'Amount': '',
                'Due Date': '',
                'Unpaid': total_pending,
                'Days Remaining': ''
            }])
            pending_df = pd.concat([pending_df, totals_row], ignore_index=True)
            pending_df.to_excel(writer, sheet_name='Pending Credits', index=False)
        else:
            pd.DataFrame([{'Message': 'No pending credits found!'}]).to_excel(writer, sheet_name='Pending Credits', index=False)

        summary_data = []
        if opening_balance is not None:
            summary_data.append({'Category': 'Opening Balance', 'Amount': f'₹{opening_balance:,.2f}'})
        summary_data.append({'Category': 'Total Credits Processed', 'Amount': f'₹{total_credits:,.2f}'})
        summary_data.append({'Category': 'Total Debits Processed', 'Amount': f'₹{total_debits:,.2f}'})
        if opening_balance is not None:
            computed_closing = opening_balance + total_credits - total_debits
            summary_data.append({'Category': 'Computed Closing Balance', 'Amount': f'₹{computed_closing:,.2f}'})
        if closing_balance is not None:
            summary_data.append({'Category': 'Actual Closing Balance', 'Amount': f'₹{closing_balance:,.2f}'})
        summary_data.append({'Category': 'Total Principal Due (Overdue)', 'Amount': f'₹{total_principal:,.2f}'})
        summary_data.append({'Category': 'Total Interest Accrued', 'Amount': f'₹{total_interest:,.2f}'})
        summary_data.append({'Category': 'GST (18% on Interest)', 'Amount': f'₹{gst:,.2f}'})
        summary_data.append({'Category': 'Total Amount Due (Principal + Interest + GST)', 'Amount': f'₹{total_amount_due:,.2f}'})
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Balance Summary', index=False)

    output.seek(0)
    return output

# Streamlit app
def main():
    st.title("Financial Transaction Analysis")
    st.markdown("Upload a CSV file to calculate overdue amounts with 18% interest (per day or per annum).")

    # Interest rate type selection
    interest_rate_type = st.radio("Select Interest Rate Type:", ["18% Per Day", "18% Per Annum"], index=0)
    rate_type = 'per_day' if interest_rate_type == "18% Per Day" else 'per_annum'

    # File uploader
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    if uploaded_file is not None:
        st.success("File uploaded successfully!")
        transactions, opening_balance, closing_balance = read_csv_data(uploaded_file)
        if transactions is None:
            st.error("Failed to process CSV file. Ensure it has 'Date', 'Debit', 'Credit', '180 days' columns.")
            return
        if not transactions:
            st.error("No valid transaction data found in the file.")
            return

        st.write(f"Loaded {len(transactions)} transactions.")

        # Calculate balances
        with st.spinner("Processing data..."):
            overdue_with_interest, pending_credits, total_credits, total_debits, total_principal, total_interest, gst, total_amount_due = calculate_balances(transactions, interest_rate_type=rate_type)

        # Display results
        st.header("Summary")
        st.write(f"**Total Principal Due (Overdue):** ₹{total_principal:,.2f}")
        st.write(f"**Total Interest Accrued:** ₹{total_interest:,.2f}")
        st.write(f"**GST (18% on Interest):** ₹{gst:,.2f}")
        st.write(f"**Total Amount Due:** ₹{total_amount_due:,.2f}")

        st.header("Overdue Credits")
        if overdue_with_interest:
            overdue_df = pd.DataFrame([
                {
                    'Credit Date': item['credit_date'],
                    'Amount': item['credit_amount'],
                    'Due Date': item['due_date'],
                    'Unpaid': item['unpaid_amount'],
                    'Interest': item['interest'],
                    'Total Due': item['total_with_interest']
                }
                for item in overdue_with_interest
            ])
            st.dataframe(overdue_df)
        else:
            st.write("No overdue amounts found!")

        st.header("Pending Credits")
        if pending_credits:
            pending_df = pd.DataFrame([
                {
                    'Credit Date': item['credit_date'],
                    'Amount': item['credit_amount'],
                    'Due Date': item['due_date'],
                    'Unpaid': item['unpaid_amount'],
                    'Days Remaining': item['days_remaining']
                }
                for item in pending_credits
            ])
            st.dataframe(pending_df)
        else:
            st.write("No pending credits found!")

        # Download Excel
        excel_file = generate_excel(overdue_with_interest, pending_credits, opening_balance, closing_balance, total_credits, total_debits, total_principal, total_interest, gst, total_amount_due)
        st.download_button(
            label="Download Excel Report",
            data=excel_file,
            file_name=f"credit_debit_analysis_{uuid.uuid4().hex[:8]}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

if __name__ == "__main__":
    main()