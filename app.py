
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import io
import base64

# Backend logic (unchanged)
def read_excel_data(file, sheet_name=0):
    """
    Read transaction data from Excel file, extract opening and closing balances, and parse transactions.
    """
    df = pd.read_excel(file, sheet_name=sheet_name)
    df.columns = df.columns.str.strip()
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
        if pd.isna(row.get(date_col)) or pd.isna(row.get(due_date_col)):
            continue
        date_val = row[date_col]
        due_date_val = row[due_date_col]
        date_str = parse_date(date_val)
        due_date_str = parse_date(due_date_val)
        if date_str is None or due_date_str is None:
            continue
        debit = 0
        if pd.notna(row.get(debit_col)):
            try: debit = float(row[debit_col])
            except: pass
        credit = 0
        if pd.notna(row.get(credit_col)):
            try: credit = float(row[credit_col])
            except: pass
        transactions.append({
            'Date': date_str,
            'Debit': debit,
            'Credit': credit,
            'Due_Date': due_date_str
        })
    return transactions, opening_balance, closing_balance

def parse_date(date_val):
    """
    Parse date from Excel serial date or string formats.
    Returns: String in '%d-%m-%Y' format or None if parsing fails.
    """
    try:
        if isinstance(date_val, (int, float)):  # Excel serial date
            return (datetime(1899, 12, 30) + timedelta(days=int(date_val))).strftime('%d-%m-%Y')
        elif isinstance(date_val, datetime):
            return date_val.strftime('%d-%m-%Y')
        elif isinstance(date_val, str):
            if '-' in date_val:
                return datetime.strptime(date_val, '%d-%m-%Y').strftime('%d-%m-%Y')
            elif '/' in date_val:
                return datetime.strptime(date_val, '%d/%m/%Y').strftime('%d-%m-%Y')
            else:
                date = pd.to_datetime(date_val, errors='coerce')
                if pd.notna(date):
                    return date.strftime('%d-%m-%Y')
        return None
    except:
        return None

def process_credit_debit_data(data):
    """
    Process credit and debit transactions, match debits to credits, and calculate interest (18% of 18% daily)
    on unpaid amounts after 180 days.
    """
    if not data:
        return [], [], 0, 0
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
    daily_rate = 0.18 * 0.18  # 18% of 18% per day = 3.24% per day
    for credit in credits:
        credit_date = credit['date']
        due_date = credit['due_date']
        credit_amount = credit['amount']
        remaining_principal = credit_amount
        matched_debits = []
        # Match debits to this credit
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
            debit['remaining'] -= alloc  # Ensure debit is used only once
            remaining_principal -= alloc
        # Calculate payments within 180 days
        paid_on_time = sum(match['allocated'] for match in matched_debits if match['payment_date'] <= due_date)
        late_payments = [match for match in matched_debits if match['payment_date'] > due_date]
        unpaid_at_due = credit_amount - paid_on_time
        if unpaid_at_due <= 0:
            # Credit fully paid on time or not yet due
            if remaining_principal > 0:
                days_remaining = max((due_date - last_date_in_data).days, 0)
                pending_credits.append({
                    'credit_date': credit['original_date'],
                    'credit_amount': credit_amount,
                    'due_date': credit['original_due_date'],
                    'unpaid_amount': remaining_principal,
                    'days_remaining': days_remaining,
                    'matched_debits': matched_debits
                })
            continue
        # Calculate interest on original unpaid amount after due date
        balance = unpaid_at_due
        current_date = due_date
        interest = 0.0
        for late in late_payments:
            days = max((late['payment_date'] - current_date).days, 0)
            interest += unpaid_at_due * daily_rate * days  # Interest on original unpaid amount
            balance -= late['allocated']
            current_date = late['payment_date']
            if balance <= 0:
                break
        if balance > 0:
            days = max((last_date_in_data - current_date).days, 0)
            interest += unpaid_at_due * daily_rate * days  # Interest on original unpaid amount
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
    return overdue_with_interest, pending_credits, total_credits, total_debits

def display_results(overdue_with_interest, pending_credits, opening_balance, closing_balance, total_credits, total_debits):
    """
    Write results to an Excel file with sheets for Overdue Amounts, Pending Credits, and Balance Summary.
    Returns the Excel file as a BytesIO buffer for Streamlit download.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Overdue Amounts Sheet
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
            total_unpaid = sum(item['unpaid_amount'] for item in overdue_with_interest)
            total_interest = sum(item['interest'] for item in overdue_with_interest)
            total_due = sum(item['total_with_interest'] for item in overdue_with_interest)
            totals_row = pd.DataFrame([{
                'Credit Date': 'TOTALS',
                'Amount': '',
                'Due Date': '',
                'Unpaid': total_unpaid,
                'Interest': total_interest,
                'Total Due': total_due
            }])
            overdue_df = pd.concat([overdue_df, totals_row], ignore_index=True)
            overdue_df.to_excel(writer, sheet_name='Overdue Amounts', index=False)
        else:
            pd.DataFrame([{'Message': 'No overdue amounts found!'}]).to_excel(writer, sheet_name='Overdue Amounts', index=False)
        # Pending Credits Sheet
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
        # Balance Summary Sheet
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
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Balance Summary', index=False)
    output.seek(0)
    return output

# Streamlit frontend
def main():
    st.set_page_config(page_title="Credit-Debit Analysis Tool", layout="wide")
    st.title("Credit-Debit Analysis Tool")
    st.markdown("Upload an Excel file to analyze credit and debit transactions, calculate interest (18% of 18% daily on overdue amounts), and download the results.")

    # File uploader
    uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"])

    if uploaded_file is not None:
        # Read Excel file to get sheet names
        xl = pd.ExcelFile(uploaded_file)
        sheet_names = xl.sheet_names
        sheet_name = st.selectbox("Select Sheet", ["First Sheet"] + sheet_names, index=0)
        sheet = 0 if sheet_name == "First Sheet" else sheet_name

        if st.button("Process Transactions"):
            try:
                # Reset file pointer
                uploaded_file.seek(0)
                # Read data
                transaction_data, opening_balance, closing_balance = read_excel_data(uploaded_file, sheet)
                
                if not transaction_data:
                    st.error("No valid transaction data found in the file.")
                    return
                
                st.success(f"Successfully loaded {len(transaction_data)} transactions.")
                
                # Process data
                with st.spinner("Processing data..."):
                    overdue_amounts, pending_credits, total_credits, total_debits = process_credit_debit_data(transaction_data)
                    output_buffer = display_results(overdue_amounts, pending_credits, opening_balance, closing_balance, total_credits, total_debits)
                
                # Display summary
                st.subheader("Summary")
                credits_count = len([x for x in transaction_data if x['Credit'] > 0])
                st.write(f"**Number of Credits Processed**: {credits_count}")
                st.write(f"**Overdue Credits**: {len(overdue_amounts)}")
                st.write(f"**Pending Credits**: {len(pending_credits)}")
                if overdue_amounts:
                    total_interest_due = sum(x['interest'] for x in overdue_amounts)
                    st.write(f"**Total Interest Due (18% of 18% daily)**: ₹{total_interest_due:,.2f}")
                
                # Display results
                st.subheader("Results")
                st.write("The results have been written to an Excel file with sheets: 'Overdue Amounts', 'Pending Credits', and 'Balance Summary'.")
                
                # Provide download link
                b64 = base64.b64encode(output_buffer.getvalue()).decode()
                href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="credit_debit_analysis.xlsx">Download Results</a>'
                st.markdown(href, unsafe_allow_html=True)
                
                # Display preview of results
                if overdue_amounts:
                    st.subheader("Overdue Amounts Preview")
                    overdue_df = pd.DataFrame([
                        {
                            'Credit Date': item['credit_date'],
                            'Amount': item['credit_amount'],
                            'Due Date': item['due_date'],
                            'Unpaid': item['unpaid_amount'],
                            'Interest': item['interest'],
                            'Total Due': item['total_with_interest']
                        }
                        for item in overdue_amounts
                    ])
                    st.dataframe(overdue_df)
                
                if pending_credits:
                    st.subheader("Pending Credits Preview")
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
                
            except Exception as e:
                st.error(f"Error processing file: {str(e)}")
    else:
        st.info("Please upload an Excel file to begin.")

if __name__ == "__main__":
    main()
