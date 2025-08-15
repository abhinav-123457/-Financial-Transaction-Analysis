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
    target_date = last_date_in_data  # Remove time component, keep only date
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
            days = max((target_date - current_date).days, 0)
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
    return overdue_with_interest, pending_credits, total_credits, total_debits, target_date

def display_results(overdue_with_interest, pending_credits, opening_balance, closing_balance, total_credits, total_debits, target_date, transaction_data):
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
        summary_data = [
            {'Category': 'Opening Balance', 'Amount': f'₹{opening_balance:,.2f}' if opening_balance is not None else ''},
            {'Category': 'Total Credits Processed', 'Amount': f'₹{total_credits:,.2f}'},
            {'Category': 'Total Debits Processed', 'Amount': f'₹{total_debits:,.2f}'},
            {'Category': 'Computed Closing Balance', 'Amount': f'₹{(opening_balance + total_credits - total_debits):,.2f}' if opening_balance is not None else ''},
            {'Category': 'Actual Closing Balance', 'Amount': f'₹{closing_balance:,.2f}' if closing_balance is not None else ''},
            {'Category': 'Target Date', 'Amount': target_date.strftime('%d-%m-%Y')},
            {'Category': 'Total Principal Due (Overdue)', 'Amount': f'₹{total_unpaid:,.2f}'},
            {'Category': 'Total Interest Accrued', 'Amount': f'₹{total_interest:,.2f}'},
            {'Category': 'GST (18% on Interest)', 'Amount': f'₹{(0.18 * total_interest):,.2f}'},
            {'Category': 'Total Amount Due (Principal + Interest + GST)', 'Amount': f'₹{(total_unpaid + total_interest + 0.18 * total_interest):,.2f}'}
        ]
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Balance Summary', index=False)
    output.seek(0)
    return output

# Streamlit frontend
def main():
    st.set_page_config(page_title="Credit-Debit Analysis Tool", layout="wide")
    st.title("Credit-Debit Analysis Tool")
    st.markdown("Upload an Excel file to analyze credit and debit transactions, calculate interest (18% of 18% daily on overdue amounts), and download the results. *Last updated: August 15, 2025*")

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
                    overdue_amounts, pending_credits, total_credits, total_debits, target_date = process_credit_debit_data(transaction_data)
                    output_buffer = display_results(overdue_amounts, pending_credits, opening_balance, closing_balance, total_credits, total_debits, target_date, transaction_data)
                
                # Display summary metrics
                st.header("Financial Summary")
                col1, col2, col3, col4 = st.columns(4)
                total_unpaid = sum(item['unpaid_amount'] for item in overdue_amounts) if overdue_amounts else 0
                total_interest = sum(item['interest'] for item in overdue_amounts) if overdue_amounts else 0
                total_amount_due = total_unpaid + total_interest + (0.18 * total_interest) if overdue_amounts else 0
                col1.metric("Principal Due", f"₹{total_unpaid:,.2f}")
                col2.metric("Interest Accrued", f"₹{total_interest:,.2f}")
                col3.metric("GST (18%)", f"₹{(0.18 * total_interest):,.2f}")
                col4.metric("Total Amount Due", f"₹{total_amount_due:,.2f}")
                st.write(f"**Target Date:** {target_date.strftime('%d-%m-%Y')}")

                # Display summary
                st.subheader("Summary")
                credits_count = len([x for x in transaction_data if x['Credit'] > 0])
                st.write(f"**Number of Credits Processed**: {credits_count}")
                st.write(f"**Overdue Credits**: {len(overdue_amounts)}")
                st.write(f"**Pending Credits**: {len(pending_credits)}")
                if overdue_amounts:
                    st.write(f"**Total Interest Due (18% of 18% daily)**: ₹{total_interest:,.2f}")

                # Display charts side by side
                st.header("Transaction Breakdown and Trends")
                col_left, col_right = st.columns(2)

                # Pie Chart for Breakdown
                with col_left:
                    st.subheader("Breakdown of Total Amount Due")
                    if total_unpaid > 0 or total_interest > 0:
                        chart_data = pd.DataFrame({
                            'Category': ['Principal', 'Interest', 'GST'],
                            'Amount': [total_unpaid, total_interest, 0.18 * total_interest]
                        })
                        fig = px.pie(
                            chart_data,
                            values='Amount',
                            names='Category',
                            title="Breakdown of Total Amount Due",
                            color_discrete_sequence=['#3498db', '#e74c3c', '#2ecc71'],
                            hole=0.3,
                            labels={'Amount': '₹ Amount'}
                        )
                        fig.update_traces(textinfo='percent+label', pull=[0.1, 0, 0], marker=dict(line=dict(color='#000000', width=2)))
                        fig.update_layout(
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            margin=dict(t=50, b=50, l=50, r=50),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)"
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.write("No data to display in pie chart.")

                # Line Chart: Aggregates by Month
                with col_right:
                    st.subheader("Monthly Transaction and Interest Trends")
                    if transaction_data:
                        # Prepare data for line chart
                        df_transactions = pd.DataFrame(transaction_data)
                        df_transactions['Date'] = pd.to_datetime(df_transactions['Date'], format='%d-%m-%Y')
                        df_transactions['Month'] = df_transactions['Date'].dt.to_period('M').astype(str)
                        
                        # Aggregate credits and debits by month
                        monthly_data = df_transactions.groupby('Month').agg({
                            'Credit': 'sum',
                            'Debit': 'sum'
                        }).reset_index()
                        
                        # Add interest data from overdue amounts
                        monthly_interest = []
                        for month in monthly_data['Month']:
                            month_start = pd.to_datetime(month + '-01')
                            month_interest = sum(
                                item['interest'] for item in overdue_amounts
                                if pd.to_datetime(item['credit_date'], format='%d-%m-%Y').to_period('M') == month_start.to_period('M')
                            )
                            monthly_interest.append(month_interest)
                        monthly_data['Interest'] = monthly_interest
                        
                        # Melt data for plotting
                        monthly_data_melted = monthly_data.melt(id_vars='Month', value_vars=['Credit', 'Debit', 'Interest'], 
                                                              var_name='Category', value_name='Amount')
                        
                        # Create line chart
                        fig_line = px.line(
                            monthly_data_melted,
                            x='Month',
                            y='Amount',
                            color='Category',
                            title="Monthly Credits, Debits, and Interest Accrued",
                            color_discrete_sequence=['#3498db', '#2ecc71', '#e74c3c'],
                            labels={'Amount': '₹ Amount', 'Month': 'Month'}
                        )
                        fig_line.update_traces(line=dict(width=3))
                        fig_line.update_layout(
                            xaxis_title="Month",
                            yaxis_title="Amount (₹)",
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            margin=dict(t=50, b=50, l=50, r=50),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)"
                        )
                        st.plotly_chart(fig_line, use_container_width=True)
                    else:
                        st.write("No data to display in line chart.")

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
