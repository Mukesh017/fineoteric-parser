from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
import re
import json

app = FastAPI()

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

FIELD_MAP = {
    "customer name/ company name":          "CUSTOMER NAME",
    "customer name/company name":           "CUSTOMER NAME",
    "customer name":                        "CUSTOMER NAME",
    "company name":                         "COMPANY NAME",
    "nbfc/bank name":                       "BANK NAME",
    "nbfc / bank name":                     "BANK NAME",
    "bank name":                            "BANK NAME",
    "lender name":                          "BANK NAME",
    "product":                              "PRODUCT",
    "loan type":                            "PRODUCT",
    "loan product":                         "PRODUCT",
    "dsa name":                             "CONNECTOR",
    "dsa code":                             "CODE",
    "dsa code ":                            "CODE",
    "application number":                   "APPLICATION NUMBER",
    "application no":                       "APPLICATION NUMBER",
    "cas application id":                   "APPLICATION NUMBER",
    "lsq application id":                   "APPLICATION NUMBER",
    "loan account number":                  "APPLICATION NUMBER",
    "lan number":                           "APPLICATION NUMBER",
    "lan no":                               "APPLICATION NUMBER",
    "disbursed amount":                     "TOTAL DISB AMOUNT",
    "disbursal amount":                     "TOTAL DISB AMOUNT",
    "loan amount approved":                 "TOTAL DISB AMOUNT",
    "loan amount":                          "TOTAL DISB AMOUNT",
    "disb amount":                          "TOTAL DISB AMOUNT",
    "sanction amount":                      "N/A",
    "disbursed date":                       "DISB DATE",
    "disbursal date":                       "DISB DATE",
    "disb date":                            "DISB DATE",
    "disbursement date":                    "DISB DATE",
    "sanction date":                        "N/A",
    "payout":                               "Payout %",
    "status":                               "STATUS",
    "status of application":                "STATUS",
    "finnone stage":                        "STATUS",
    "tenure":                               "N/A",
    "loan tenure approved":                 "N/A",
    "rate of interest":                     "N/A",
    "roi%":                                 "N/A",
    "insurance amount (if any)":            "N/A",
    "otc/pdd clearnce ( na / cleared/no)":  "N/A",
    "cheque handover stauts ( yes / no)":   "N/A",
    "cheque handover date":                 "N/A",
    "subvention ( if any )":               "N/A",
    "disbursed type ( part / full )":       "N/A",
}

HEADER_WORDS = [
    'descriptions', 'labels', 'field', 'sr no',
    'label', 'particulars', 'details'
]


def clean(raw):
    text = re.sub(r'<[^>]+>', '', str(raw))
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def fresh_row():
    return dict(STANDARD_ROW)


def map_field(raw_label):
    key = raw_label.lower().strip()
    return FIELD_MAP.get(key, None)


def parse_email_html(html_body, sender_email="", entry_date=""):
    soup = BeautifulSoup(html_body, 'html.parser')
    tables = soup.find_all('table')
    records = []

    for table in tables:
        rows = []
        for tr in table.find_all('tr'):
            cells = [clean(td) for td in tr.find_all(['td', 'th'])]
            if len(cells) >= 2 and any(c for c in cells):
                rows.append(cells)

        if len(rows) < 2:
            continue

        max_cols = max(len(r) for r in rows)

        if max_cols >= 3:
            num_customers = max_cols - 1
            start_row = 0
            if any(w in rows[0][0].lower() for w in HEADER_WORDS):
                start_row = 1

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

                if row["CUSTOMER NAME"] != "N/A" or row["TOTAL DISB AMOUNT"] != "N/A":
                    records.append(row)

        else:
            row = fresh_row()
            row["ENTRY DATE"] = entry_date
            row["OTHERS"] = sender_email

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

            if row["CUSTOMER NAME"] != "N/A" or row["TOTAL DISB AMOUNT"] != "N/A":
                records.append(row)

    return records


@app.post("/parse-email")
async def parse_email(request: Request):
    # Read raw body — accept ANY content type
    raw = await request.body()
    raw_text = raw.decode('utf-8', errors='replace')

    html_body = ''
    sender_email = ''
    entry_date = ''

    # Try JSON first
    try:
        data = json.loads(raw_text)
        html_body = data.get('html_body', '')
        sender_email = data.get('sender', '')
        entry_date = data.get('date', '')
    except Exception:
        pass

    # Try form-urlencoded if JSON failed
    if not html_body:
        try:
            from urllib.parse import parse_qs
            parsed = parse_qs(raw_text)
            html_body = parsed.get('html_body', [''])[0]
            sender_email = parsed.get('sender', [''])[0]
            entry_date = parsed.get('date', [''])[0]
        except Exception:
            pass

    if not html_body:
        return JSONResponse({
            'success': False,
            'error': 'html_body is required',
            'raw_preview': raw_text[:300],
            'records': []
        }, status_code=400)

    records = parse_email_html(html_body, sender_email, entry_date)

    if not records:
        return JSONResponse({
            'success': False,
            'message': 'No disbursement table found',
            'html_length': len(html_body),
            'table_count': len(BeautifulSoup(html_body, 'html.parser').find_all('table')),
            'records': []
        })

    return JSONResponse({
        'success': True,
        'record_count': len(records),
        'records': records
    })


@app.get("/health")
def health():
    return {"status": "running", "service": "Fineoteric Email Parser"}


@app.get("/")
def home():
    return {"status": "running", "service": "Fineoteric Email Parser"}
