from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

# ── Standard row — every field from your company sheet ──────────────────────
# Parser always returns this structure
# Fields found in email → filled with real value
# Fields not found → stays "N/A"
STANDARD_ROW = {
    "SR NO":                    "N/A",
    "MIS UNIQUE ID":            "N/A",
    "ENTRY DATE":               "N/A",
    "ENTRY DONE BY":            "AUTO",
    "CASE NO":                  "N/A",
    "ENQUIRY NO":               "N/A",
    "APPLICATION NUMBER":       "N/A",
    "COMPANY NAME":             "N/A",
    "CUSTOMER NAME":            "N/A",
    "BANK NAME":                "N/A",
    "CODE":                     "N/A",
    "BRANCH":                   "N/A",
    "RM NAME":                  "N/A",
    "PRODUCT":                  "N/A",
    "CONNECTOR":                "N/A",
    "CONNECTOR 2":              "N/A",
    "UNIT HEAD":                "N/A",
    "SM NAME":                  "N/A",
    "EXECUTIVE":                "N/A",
    "OTHERS":                   "N/A",
    "REGION":                   "N/A",
    "STATUS":                   "DISBURSED",
    "TOTAL DISB AMOUNT":        "N/A",
    "DISB DATE":                "N/A",
    "SPILL - FRESH":            "N/A",
    "PROFILE":                  "N/A",
    "BANK PAYOUT%":             "N/A",
    "BANK PAYOUTAMT":           "N/A",
    "CONNECTOR PAYOUT%":        "N/A",
    "CONNECTOR PAYOUT AMT":     "N/A",
    "CONNECTOR 2 PAYOUT%":      "N/A",
    "CONNECTOR 2 PAYOUT AMT":   "N/A",
    "UNIT HEAD%":               "N/A",
    "UNIT HEAD AMT":            "N/A",
    "SM PAYOUT%":               "N/A",
    "SM PAYOUT AMT":            "N/A",
    "SE PAYOUT%":               "N/A",
    "SE PAYOUT AMT":            "N/A",
    "OTHER PAYOUT %":           "N/A",
    "OTHER PAYOUT AMT":         "N/A",
    "INVOICE DATE":             "N/A",
    "INVOICE NO":               "N/A",
    "Taxable Amount":           "N/A",
    "Bill Status":              "N/A",
    "Receive date":             "N/A",
    "Case wise P&L":            "N/A",
    "Payout %":                 "N/A",
}

# ── Synonym dictionary ───────────────────────────────────────────────────────
# Maps every lender field name → your sheet column name
# Add new lender field names here as you discover them
FIELD_MAP = {
    # Customer / Company
    "customer name/ company name":          "CUSTOMER NAME",
    "customer name/company name":           "CUSTOMER NAME",
    "customer name":                        "CUSTOMER NAME",
    "company name":                         "COMPANY NAME",

    # Bank
    "nbfc/bank name":                       "BANK NAME",
    "nbfc / bank name":                     "BANK NAME",
    "bank name":                            "BANK NAME",
    "lender name":                          "BANK NAME",

    # Product
    "product":                              "PRODUCT",
    "loan type":                            "PRODUCT",
    "loan product":                         "PRODUCT",

    # DSA / Connector
    "dsa name":                             "CONNECTOR",
    "dsa code":                             "CODE",
    "dsa code ":                            "CODE",

    # Application / LAN
    "application number":                   "APPLICATION NUMBER",
    "application no":                       "APPLICATION NUMBER",
    "cas application id":                   "APPLICATION NUMBER",
    "lsq application id":                   "APPLICATION NUMBER",
    "loan account number":                  "APPLICATION NUMBER",
    "lan number":                           "APPLICATION NUMBER",
    "lan no":                               "APPLICATION NUMBER",

    # Amounts
    "disbursed amount":                     "TOTAL DISB AMOUNT",
    "disbursal amount":                     "TOTAL DISB AMOUNT",
    "loan amount approved":                 "TOTAL DISB AMOUNT",
    "loan amount":                          "TOTAL DISB AMOUNT",
    "disb amount":                          "TOTAL DISB AMOUNT",
    "sanction amount":                      "N/A",   # not in sheet — ignore

    # Dates
    "disbursed date":                       "DISB DATE",
    "disbursal date":                       "DISB DATE",
    "disb date":                            "DISB DATE",
    "disbursement date":                    "DISB DATE",
    "sanction date":                        "N/A",   # not in sheet — ignore

    # Payout
    "payout":                               "Payout %",

    # Status
    "status":                               "STATUS",
    "status of application":                "STATUS",
    "finnone stage":                        "STATUS",

    # Tenure / ROI — not in your main sheet but store in OTHERS
    "tenure":                               "N/A",
    "loan tenure approved":                 "N/A",
    "rate of interest":                     "N/A",
    "roi%":                                 "N/A",

    # Insurance / OTC / Cheque — not in your main sheet
    "insurance amount (if any)":            "N/A",
    "otc/pdd clearnce ( na / cleared/no)":  "N/A",
    "cheque handover stauts ( yes / no)":   "N/A",
    "cheque handover date":                 "N/A",
    "subvention ( if any )":                "N/A",
    "disbursed type ( part / full )":       "N/A",
}

# Header words — these are column header rows, skip them
HEADER_WORDS = [
    'descriptions', 'labels', 'field', 'sr no',
    'label', 'particulars', 'details'
]

# ── Helper: clean raw HTML text ──────────────────────────────────────────────


def clean(raw):
    text = re.sub(r'<[^>]+>', '', str(raw))
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ── Helper: make a fresh copy of the standard row ───────────────────────────


def fresh_row():
    return dict(STANDARD_ROW)

# ── Helper: map one lender field → sheet column ─────────────────────────────


def map_field(raw_label):
    key = raw_label.lower().strip()
    return FIELD_MAP.get(key, None)  # None means unknown field

# ── Core: parse all tables from email HTML ───────────────────────────────────


def parse_email_html(html_body, sender_email="", entry_date=""):
    soup = BeautifulSoup(html_body, 'html.parser')
    tables = soup.find_all('table')
    records = []

    for table in tables:
        rows = []
        for tr in table.find_all('tr'):
            cells = [clean(td) for td in tr.find_all(['td', 'th'])]
            # Only keep rows that have at least 2 non-empty cells
            if len(cells) >= 2 and any(c for c in cells):
                rows.append(cells)

        if len(rows) < 2:
            continue  # skip tiny tables (like signature tables)

        # ── Detect max columns in this table ──────────────────────────────
        max_cols = max(len(r) for r in rows)

        # ── FORMAT 3: Multiple customers side by side (3+ columns) ────────
        if max_cols >= 3:
            num_customers = max_cols - 1

            # Find header row — it usually has "Status | Status" repeated
            # or "Descriptions | Status | Status"
            start_row = 0
            if any(w in rows[0][0].lower() for w in HEADER_WORDS):
                start_row = 1

            # Build one record per customer column
            for c in range(num_customers):
                row = fresh_row()
                row["ENTRY DATE"] = entry_date
                row["OTHERS"] = sender_email

                for r in rows[start_row:]:
                    if len(r) < 2:
                        continue
                    label = r[0].strip()
                    value = r[c + 1].strip() if (c + 1) < len(r) else ''
                    if not value:
                        continue
                    target = map_field(label)
                    if target and target != "N/A":
                        row[target] = value

                # Only add if we got at least customer name or amount
                if row["CUSTOMER NAME"] != "N/A" or row["TOTAL DISB AMOUNT"] != "N/A":
                    records.append(row)

        # ── FORMAT 1 & 2: Single customer, 2 columns ──────────────────────
        else:
            row = fresh_row()
            row["ENTRY DATE"] = entry_date
            row["OTHERS"] = sender_email

            # Skip header row if first cell is a column label
            start_row = 0
            if rows and any(w in rows[0][0].lower() for w in HEADER_WORDS):
                start_row = 1

            for r in rows[start_row:]:
                if len(r) < 2:
                    continue
                label = r[0].strip()
                value = r[1].strip()
                if not value:
                    continue
                target = map_field(label)
                if target and target != "N/A":
                    row[target] = value

            # Only add if something meaningful was extracted
            if row["CUSTOMER NAME"] != "N/A" or row["TOTAL DISB AMOUNT"] != "N/A":
                records.append(row)

    return records

# ── API Endpoint ─────────────────────────────────────────────────────────────


@app.route('/parse-email', methods=['POST'])
def parse_email():
    data = request.get_json()

    if not data or 'html_body' not in data:
        return jsonify({
            'success': False,
            'error': 'html_body field is required',
            'records': []
        }), 400

    html_body = data.get('html_body', '')
    sender_email = data.get('sender', '')
    entry_date = data.get('date', '')

    records = parse_email_html(html_body, sender_email, entry_date)

    if not records:
        return jsonify({
            'success': False,
            'message': 'No disbursement table found in this email',
            'records': []
        })

    return jsonify({
        'success': True,
        'count': len(records),
        'records': records
    })

# ── Health check ─────────────────────────────────────────────────────────────


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running', 'service': 'Fineoteric Email Parser'})


# ── Run ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
