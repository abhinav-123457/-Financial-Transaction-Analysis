# 📊 Financial Transaction Analysis (Streamlit App)

A Streamlit-based tool for analyzing credit and debit transactions from CSV files.  
It calculates **overdue amounts**, **interest (18% per day or per annum)**, **GST**, and provides a downloadable **Excel report**.

---

## 🚀 Features
- Upload CSV file with transaction details.
- Detect **credits** and **debits** automatically.
- Calculate:
  - Total principal overdue.
  - Interest accrued (configurable rate type).
  - GST on interest.
  - Total amount due.
- Separate tabs for:
  - **Overdue Credits**
  - **Pending Credits**
- Download results as an **Excel report**.

---

## 📂 CSV File Requirements
The uploaded CSV must have:
- **Date** column (transaction date)
- **Debit** column
- **Credit** column
- **180 days** column (due date)

Optional:
- **Particulars** column (to detect opening/closing balances)

---

## 🛠 Installation & Local Run
1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR-USERNAME/financial-analysis.git
   cd financial-analysis
