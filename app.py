import os
import re
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup

# ============== CONFIG ==============
DB_PATH = os.environ.get("DB_PATH", "fineoteric.db")
MODEL_PATH = os.environ.get("MODEL_PATH", "email_classifier.pkl")
ML_MODE = os.environ.get("ML_MODE", "rules")

# ============== 39 FIELDS - EXACT SHEET MATCH ==============
STANDARD_ROW = {
    "SR NO": "N/A", "MIS UNIQUE ID": "N/A", "ENTRY DATE": "N/A",
    "ENTRY DONE BY": "AUTO", "CASE NO": "N/A", "ENQUIRY NO": "N/A",
    "APPLICATION NUMBER": "", "COMPANY NAME": "N/A", "CUSTOMER NAME": "",
    "BANK NAME": "N/A", "CODE": "N/A", "BRANCH": "N/A", "RM NAME": "N/A",
    "PRODUCT": "N/A", "CONNECTOR": "N/A", "CONNECTOR 2": "N/A",
    "UNIT HEAD": "N/A", "SM NAME": "N/A", "EXECUTIVE": "N/A",
    "OTHERS": "N/A", "REGION": "N/A", "STATUS": "N/A",
    "TOTAL DISB AMOUNT": "N/A", "DISB DATE": "N/A", "SPILL - FRESH": "N/A",
    "PROFILE": "N/A", "BANK PAYOUT%": "N/A", "BANK PAYOUTAMT": "N/A",
    "CONNECTOR PAYOUT%": "N/A", "CONNECTOR PAYOUT AMT": "N/A",
    "CONNECTOR 2 PAYOUT%": "N/A", "CONNECTOR 2 PAYOUT AMT": "N/A",
    "UNIT HEAD%": "N/A", "UNIT HEAD AMT": "N/A", "SM PAYOUT%": "N/A",
    "SM PAYOUT AMT": "N/A", "SE PAYOUT%": "N/A", "SE PAYOUT AMT": "N/A",
    "OTHER PAYOUT %": "N/A",
}

DB_COL_MAP = {
    "SR NO": "sr_no", "MIS UNIQUE ID": "mis_unique_id", "ENTRY DATE": "entry_date",
    "ENTRY DONE BY": "entry_done_by", "CASE NO": "case_no", "ENQUIRY NO": "enquiry_no",
    "APPLICATION NUMBER": "application_number", "COMPANY NAME": "company_name",
    "CUSTOMER NAME": "customer_name", "BANK NAME": "bank_name", "CODE": "code",
    "BRANCH": "branch", "RM NAME": "rm_name", "PRODUCT": "product",
    "CONNECTOR": "connector", "CONNECTOR 2": "connector_2", "UNIT HEAD": "unit_head",
    "SM NAME": "sm_name", "EXECUTIVE": "executive", "OTHERS": "others",
    "REGION": "region", "STATUS": "status", "TOTAL DISB AMOUNT": "total_disb_amount",
    "DISB DATE": "disb_date", "SPILL - FRESH": "spill_fresh", "PROFILE": "profile",
    "BANK PAYOUT%": "bank_payout_perc", "BANK PAYOUTAMT": "bank_payout_amt",
    "CONNECTOR PAYOUT%": "connector_payout_perc", "CONNECTOR PAYOUT AMT": "connector_payout_amt",
    "CONNECTOR 2 PAYOUT%": "connector_2_payout_perc", "CONNECTOR 2 PAYOUT AMT": "connector_2_payout_amt",
    "UNIT HEAD%": "unit_head_perc", "UNIT HEAD AMT": "unit_head_amt",
    "SM PAYOUT%": "sm_payout_perc", "SM PAYOUT AMT": "sm_payout_amt",
    "SE PAYOUT%": "se_payout_perc", "SE PAYOUT AMT": "se_payout_amt",
    "OTHER PAYOUT %": "other_payout_perc",
}

# ============== DB SETUP ==============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS loan_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, application_number TEXT UNIQUE,
        customer_name TEXT, company_name TEXT, bank_name TEXT, code TEXT,
        branch TEXT, rm_name TEXT, product TEXT, connector TEXT, connector_2 TEXT,
        unit_head TEXT, sm_name TEXT, executive TEXT, others TEXT, region TEXT,
        status TEXT, total_disb_amount TEXT, disb_date TEXT, spill_fresh TEXT,
        profile TEXT, bank_payout_perc TEXT, bank_payout_amt TEXT,
        connector_payout_perc TEXT, connector_payout_amt TEXT,
        connector_2_payout_perc TEXT, connector_2_payout_amt TEXT,
        unit_head_perc TEXT, unit_head_amt TEXT, sm_payout_perc TEXT,
        sm_payout_amt TEXT, se_payout_perc TEXT, se_payout_amt TEXT,
        other_payout_perc TEXT, entry_date TEXT, entry_done_by TEXT,
        case_no TEXT, enquiry_no TEXT, sr_no TEXT, mis_unique_id TEXT,
        invoice_date TEXT, invoice_no TEXT, taxable_amount TEXT,
        bill_status TEXT, receive_date TEXT, case_wise_pl TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        record_hash TEXT, history TEXT DEFAULT '[]')""")
    c.execute("""CREATE TABLE IF NOT EXISTS review_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email_id TEXT, subject TEXT,
        sender TEXT, reason TEXT, raw_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email_id TEXT, subject TEXT,
        sender TEXT, action TEXT, details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, metric_name TEXT,
        metric_value INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    conn.close()

# ============== ML CLASSIFIER ==============
class MLClassifier:
    def __init__(self):
        self.mode = ML_MODE
        self.trusted_domains = [
            "kotak.com", "hdfcbank.com", "icicibank.com", "axisbank.com",
            "sbi.co.in", "bankofbaroda.in", "pnbindia.in", "canarabank.com",
            "unionbankofindia.co.in", "indianbank.in", "centralbank.co.in",
            "bankofindia.co.in", "idbi.com", "yesbank.in", "rblbank.com",
            "federalbank.co.in", "ltfs.com", "bajajfinserv.in",
            "mahindrafinance.com", "tata.com", "cholamandalam.com",
            "shriram.com", "indiabulls.com", "adityabirlacapital.com",
            "muthootgroup.com", "manappuram.com", "dcbbank.com", "idfcfirstbank.com",
        ]
        self.keywords = {
            "high": ["disbursement", "disbursed", "sanction", "sanctioned",
                     "loan approved", "amount disbursed", "payout", "login",
                     "file login", "case login", "approved", "rejected",
                     "part disbursed", "full disbursed"],
            "medium": ["loan", "application", "customer", "amount", "bank",
                       "nbfc", "finance", "credit", "status", "update"],
            "low": ["newsletter", "promotion", "offer", "marketing", "spam"]
        }

    def classify(self, subject, sender, body_text, body_html=""):
        if self.mode == "rules":
            return self._rule_based(subject, sender, body_text, body_html)
        return self._rule_based(subject, sender, body_text, body_html)

    def _rule_based(self, subject, sender, body_text, body_html):
        domain = sender.split("@")[-1].lower() if "@" in sender else ""
        text = f"{subject} {body_text} {body_html}".lower()
        domain_score = 0.30 if any(td in domain for td in self.trusted_domains) else 0.10
        keyword_score = 0.0
        for kw in self.keywords["high"]:
            if kw in text: keyword_score += 0.08
        for kw in self.keywords["medium"]:
            if kw in text: keyword_score += 0.03
        for kw in self.keywords["low"]:
            if kw in text: keyword_score -= 0.15
        keyword_score = min(0.25, keyword_score)
        subject_score = 0.10 if any(k in subject.lower() for k in self.keywords["high"]) else 0.0
        density_score = 0.05 if "disbursement" in text or "disbursed" in text else 0.0
        total = max(0.0, min(1.0, domain_score + keyword_score + subject_score + density_score))
        is_relevant = total >= 0.40
        if is_relevant:
            reason = "trusted_domain_with_keywords" if domain_score >= 0.30 else "keywords_match"
        else:
            reason = "low_confidence"
        return {
            "is_relevant": is_relevant, "confidence": round(total, 2), "reason": reason,
            "score_breakdown": {
                "domain_score": round(domain_score, 2), "keyword_score": round(keyword_score, 2),
                "subject_score": round(subject_score, 2), "density_score": round(density_score, 2),
                "total": round(total, 2)
            }
        }

# ============== EMAIL PARSER - ALL FORMATS ==============
def parse_email_html(html_body, plain_text=""):
    """Parse email body and extract loan records. Handles HTML tables, tab-separated, and space-separated formats."""
    records = []
    if not html_body and not plain_text:
        return records

    # Try HTML parsing first
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # Try HTML table format (multi-column)
        records = _parse_html_table(soup)
        if records:
            return [standardize_record(r) for r in records]

        # Try tab-separated from HTML text
        records = _parse_tab_separated(text)
        if records:
            return [standardize_record(r) for r in records]

    # Try plain text
    if plain_text:
        # Try tab-separated
        records = _parse_tab_separated(plain_text)
        if records:
            return [standardize_record(r) for r in records]

        # Try space-separated with known labels (NEW - handles 2 customers)
        records = _parse_space_separated_v2(plain_text)
        if records:
            return [standardize_record(r) for r in records]

        # Try old space-separated
        records = _parse_space_separated(plain_text)
        if records:
            return [standardize_record(r) for r in records]

        # Try colon-separated
        records = _parse_colon_separated(plain_text)
        if records:
            return [standardize_record(r) for r in records]

    return records


def _parse_html_table(soup):
    """Parse HTML <table> with multiple columns (1 customer per column after Description)."""
    records = []
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Get all rows as list of cell texts
        table_data = []
        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(strip=True) for c in cells]
            if cell_texts:
                table_data.append(cell_texts)

        if not table_data:
            continue

        # Check if first row has "Descriptions" or similar
        first_row = [c.lower() for c in table_data[0]]
        if not any("description" in c for c in first_row):
            continue

        # Number of customer columns = total columns - 1 (description column)
        num_customers = len(table_data[0]) - 1
        if num_customers < 1:
            continue

        # Extract data for each customer column
        for cust_idx in range(1, num_customers + 1):
            record = dict(STANDARD_ROW)
            for row in table_data[1:]:
                if len(row) > cust_idx:
                    key = row[0]
                    val = row[cust_idx]
                    _map_cell_to_field(record, key, val)

            if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
                records.append(record)

    return records if records else None


def _parse_tab_separated(text):
    """Parse tab-separated format: Description\tValue or Description\tCust1\tCust2."""
    records = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None

    # Check if tabs exist
    has_tabs = any("\t" in line for line in lines)
    if not has_tabs:
        return None

    # Find header row
    header_row = None
    for i, line in enumerate(lines):
        if "description" in line.lower():
            header_row = i
            break

    if header_row is None:
        header_row = 0

    # Count columns from header
    header_parts = lines[header_row].split("\t")
    num_cols = len(header_parts)

    if num_cols == 2:
        # Single customer: Description | Status
        record = dict(STANDARD_ROW)
        for line in lines[header_row + 1:]:
            parts = line.split("\t", 1)
            if len(parts) == 2:
                key, val = parts[0].strip(), parts[1].strip()
                _map_cell_to_field(record, key, val)
                if val and (val.startswith("DRBL") or val.startswith("KH") or val.startswith("HL")):
                    record["APPLICATION NUMBER"] = val

        if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
            records.append(record)

    elif num_cols >= 3:
        # Multiple customers: Description | Cust1 | Cust2 | ...
        num_customers = num_cols - 1

        for cust_idx in range(1, num_cols):
            record = dict(STANDARD_ROW)
            for line in lines[header_row + 1:]:
                parts = line.split("\t")
                if len(parts) > cust_idx:
                    key = parts[0].strip()
                    val = parts[cust_idx].strip()
                    _map_cell_to_field(record, key, val)
                    if val and (val.startswith("DRBL") or val.startswith("KH") or val.startswith("HL")):
                        record["APPLICATION NUMBER"] = val

            if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
                records.append(record)

    return records if records else None


def _parse_space_separated_v2(text):
    """Parse space-separated text with known labels and multiple customers.

    Handles format like:
    Descriptions Status Status
    Customer name/ Company Name KANHAIYALAL SHANKARLAL JAIN RAHUL KANHAIYLAL JAIN
    NBFC/Bank Name Kotak Mahindra Bank Ltd Kotak Mahindra Bank Ltd
    ...
    """
    records = []
    text_clean = text.replace("\r", " ").strip()

    # Known labels in order of appearance
    KNOWN_LABELS = [
        ("Customer name/ Company Name", ["customer", "name", "company"]),
        ("NBFC/Bank Name", ["nbfc", "bank", "name"]),
        ("Product", ["product"]),
        ("DSA Name", ["dsa", "name"]),
        ("DSA code", ["dsa", "code"]),
        ("Sanction Amount", ["sanction", "amount"]),
        ("Sanction Date", ["sanction", "date"]),
        ("Disbursed Amount", ["disbursed", "amount"]),
        ("Disbursed Date", ["disbursed", "date"]),
        ("Disbursed Type ( part / Full )", ["disbursed", "type", "part", "full"]),
        ("Insurance Amount (if any)", ["insurance", "amount"]),
        ("LAN Number", ["lan", "number"]),
        ("Subvention ( if any )", ["subvention"]),
        ("OTC/PDD clearnce ( NA / Cleared/NO)", ["otc", "pdd", "clearance"]),
        ("Cheque Handover Stauts ( yes / No)", ["cheque", "handover", "status"]),
        ("Cheque Handover date", ["cheque", "handover", "date"]),
        ("Payout", ["payout"]),
    ]

    # Find all label positions in text
    label_positions = []
    for label, _ in KNOWN_LABELS:
        # Try exact match first, then fuzzy
        idx = text_clean.find(label)
        if idx == -1:
            # Try lowercase
            idx = text_clean.lower().find(label.lower())
        if idx != -1:
            label_positions.append((idx, label))

    if len(label_positions) < 3:
        return None  # Not enough labels found

    # Sort by position
    label_positions.sort()

    # Extract values between labels
    extracted = {}
    for i, (pos, label) in enumerate(label_positions):
        start = pos + len(label)
        if i + 1 < len(label_positions):
            end = label_positions[i + 1][0]
        else:
            end = len(text_clean)
        value_text = text_clean[start:end].strip()
        extracted[label] = value_text

    # Determine number of customers by checking duplicate values
    # If values are repeated (like "Kotak Mahindra Bank Ltd Kotak Mahindra Bank Ltd"), 
    # we have 2 customers
    num_customers = 1
    for label, val in extracted.items():
        if label in ["Product", "DSA code", "DSA Name"]:
            # Check if value contains duplicates
            words = val.split()
            if len(words) >= 2:
                # Simple heuristic: if first half == second half when split by middle
                mid = len(words) // 2
                first_half = " ".join(words[:mid])
                second_half = " ".join(words[mid:])
                if first_half == second_half:
                    num_customers = 2
                    break

    # Build records for each customer
    for cust_idx in range(num_customers):
        record = dict(STANDARD_ROW)

        for label, val in extracted.items():
            words = val.split()

            if num_customers == 2 and len(words) >= 2:
                # Split value for 2 customers
                mid = len(words) // 2
                if cust_idx == 0:
                    cust_val = " ".join(words[:mid])
                else:
                    cust_val = " ".join(words[mid:])
            else:
                cust_val = val

            _map_cell_to_field(record, label, cust_val)

            # Special: LAN Number = APPLICATION NUMBER
            if "lan" in label.lower() and "number" in label.lower():
                record["APPLICATION NUMBER"] = cust_val

        if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
            records.append(record)

    return records if records else None


def _parse_space_separated(text):
    """Parse space-separated format without tabs or colons."""
    records = []
    record = dict(STANDARD_ROW)
    text_clean = text.replace("\n", " ").replace("\r", " ").strip()

    # Extract Customer Name / Company Name
    cust_patterns = [
        r'Customer\s*name[/\\]?\s*Company\s*Name\s+(.+?)(?:\s+NBFC|Bank|Product|$)',
        r'Customer\s*name[/\\]?\s*Company\s*Name\s+(.+?)(?:\s*-\s*NBFC|Bank|Product|$)',
    ]
    for pat in cust_patterns:
        m = re.search(pat, text_clean, re.IGNORECASE)
        if m:
            record["CUSTOMER NAME"] = m.group(1).strip()
            break

    # Extract Bank Name
    bank_match = re.search(r'NBFC[/\\]?Bank\s*Name\s+(.+?)(?:\s+Product|$)', text_clean, re.IGNORECASE)
    if bank_match:
        record["BANK NAME"] = bank_match.group(1).strip()

    # Extract Product
    prod_match = re.search(r'Product\s+(.+?)(?:\s+DSA\s*Name|$)', text_clean, re.IGNORECASE)
    if prod_match:
        record["PRODUCT"] = prod_match.group(1).strip()

    # Extract DSA Name / Connector
    dsa_match = re.search(r'DSA\s*Name\s+(.+?)(?:\s+DSA\s*code|$)', text_clean, re.IGNORECASE)
    if dsa_match:
        record["CONNECTOR"] = dsa_match.group(1).strip()

    # Extract DSA Code
    code_match = re.search(r'DSA\s*code\s+(\S+)', text_clean, re.IGNORECASE)
    if code_match:
        record["CODE"] = code_match.group(1).strip()

    # Extract Amount
    amt_match = re.search(r'(?:Sanction|Disbursed|Amount)\s*Amount\s+([\d,./\-]+)', text_clean, re.IGNORECASE)
    if amt_match:
        record["TOTAL DISB AMOUNT"] = amt_match.group(1).strip()

    # Extract Disbursed Date
    disb_date_match = re.search(r'Disbursed\s*Date\s+([\d\-A-Za-z/]+)', text_clean, re.IGNORECASE)
    if disb_date_match:
        record["DISB DATE"] = disb_date_match.group(1).strip()

    # Extract Payout
    payout_match = re.search(r'Payout\s+(.+)', text_clean, re.IGNORECASE)
    if payout_match:
        record["CONNECTOR PAYOUT%"] = payout_match.group(1).strip()
        record["OTHER PAYOUT %"] = payout_match.group(1).strip()

    # Extract LAN Number
    lan_match = re.search(r'LAN\s*Number\s+(\S+)', text_clean, re.IGNORECASE)
    if lan_match:
        record["APPLICATION NUMBER"] = lan_match.group(1).strip()

    if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
        records.append(record)

    return records if records else None


def _parse_colon_separated(text):
    """Parse colon-separated format: Key: Value."""
    records = []
    record = dict(STANDARD_ROW)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        if ":" in line:
            key, val = line.split(":", 1)
            _map_cell_to_field(record, key.strip(), val.strip())

    if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
        records.append(record)

    return records if records else None


def _map_cell_to_field(record, header_text, cell_text):
    """Map a cell header and value to the correct field in the record."""
    h = header_text.lower()
    val = cell_text.strip()

    if not val or val == "N/A":
        return

    if "customer" in h and "name" in h:
        record["CUSTOMER NAME"] = val
    elif "application" in h and any(x in h for x in ["id", "number", "no", "lan"]):
        record["APPLICATION NUMBER"] = val
    elif "company" in h and "name" in h:
        record["COMPANY NAME"] = val
    elif "bank" in h and "name" in h:
        record["BANK NAME"] = val
    elif "code" in h and "dsa" in h:
        record["CODE"] = val
    elif "branch" in h:
        record["BRANCH"] = val
    elif "rm" in h and "name" in h:
        record["RM NAME"] = val
    elif "product" in h:
        record["PRODUCT"] = val
    elif "connector" in h and "2" not in h and "payout" not in h:
        record["CONNECTOR"] = val
    elif "unit head" in h and "payout" not in h and "%" not in h and "amt" not in h:
        record["UNIT HEAD"] = val
    elif "sm" in h and "name" in h:
        record["SM NAME"] = val
    elif "executive" in h:
        record["EXECUTIVE"] = val
    elif "region" in h:
        record["REGION"] = val
    elif "status" in h and "bill" not in h:
        record["STATUS"] = val
    elif "disburs" in h and "amount" in h:
        record["TOTAL DISB AMOUNT"] = val
    elif "disburs" in h and "date" in h:
        record["DISB DATE"] = val
    elif "spill" in h or "fresh" in h:
        record["SPILL - FRESH"] = val
    elif "profile" in h:
        record["PROFILE"] = val
    elif "bank payout" in h and "%" in h:
        record["BANK PAYOUT%"] = val
    elif "bank payout" in h and ("amt" in h or "amount" in h):
        record["BANK PAYOUTAMT"] = val
    elif "connector payout" in h and "2" not in h and "%" in h:
        record["CONNECTOR PAYOUT%"] = val
        record["OTHER PAYOUT %"] = val
    elif "connector payout" in h and "2" not in h and ("amt" in h or "amount" in h):
        record["CONNECTOR PAYOUT AMT"] = val
    elif "connector 2 payout" in h and "%" in h:
        record["CONNECTOR 2 PAYOUT%"] = val
    elif "connector 2 payout" in h and ("amt" in h or "amount" in h):
        record["CONNECTOR 2 PAYOUT AMT"] = val
    elif "unit head payout" in h and "%" in h:
        record["UNIT HEAD%"] = val
    elif "unit head payout" in h and ("amt" in h or "amount" in h):
        record["UNIT HEAD AMT"] = val
    elif "sm payout" in h and "%" in h:
        record["SM PAYOUT%"] = val
    elif "sm payout" in h and ("amt" in h or "amount" in h):
        record["SM PAYOUT AMT"] = val
    elif "se payout" in h and "%" in h:
        record["SE PAYOUT%"] = val
    elif "se payout" in h and ("amt" in h or "amount" in h):
        record["SE PAYOUT AMT"] = val
    elif "other payout" in h and "%" in h:
        record["OTHER PAYOUT %"] = val
    elif "payout" in h and "%" in h and "bank" not in h and "connector" not in h and "unit" not in h and "sm" not in h and "se" not in h:
        record["CONNECTOR PAYOUT%"] = val
        record["OTHER PAYOUT %"] = val


# ============== STANDARDIZATION ==============
def standardize_record(record):
    std = dict(STANDARD_ROW)
    for key in std:
        val = record.get(key)
        std[key] = val if val not in [None, "", " "] else "N/A"
    std["TOTAL DISB AMOUNT"] = _std_amount(std["TOTAL DISB AMOUNT"])
    std["BANK PAYOUTAMT"] = _std_amount(std["BANK PAYOUTAMT"])
    std["CONNECTOR PAYOUT AMT"] = _std_amount(std["CONNECTOR PAYOUT AMT"])
    std["CONNECTOR 2 PAYOUT AMT"] = _std_amount(std["CONNECTOR 2 PAYOUT AMT"])
    std["UNIT HEAD AMT"] = _std_amount(std["UNIT HEAD AMT"])
    std["SM PAYOUT AMT"] = _std_amount(std["SM PAYOUT AMT"])
    std["SE PAYOUT AMT"] = _std_amount(std["SE PAYOUT AMT"])
    std["DISB DATE"] = _std_date(std["DISB DATE"])
    std["ENTRY DATE"] = _std_date(std["ENTRY DATE"])
    std["CONNECTOR PAYOUT%"] = _std_payout(std["CONNECTOR PAYOUT%"])
    std["OTHER PAYOUT %"] = _std_payout(std["OTHER PAYOUT %"])
    std["BANK PAYOUT%"] = _std_payout(std["BANK PAYOUT%"])
    return std


def _std_amount(val):
    if not val or val == "N/A":
        return "N/A"
    v = str(val).strip()
    if "as per" in v.lower():
        return v
    if "+gst" in v.lower():
        return v
    v = re.sub(r'[Rs,\s/]', '', v, flags=re.IGNORECASE)
    nums = re.findall(r'\d+\.?\d*', v)
    return nums[0] if nums else (v if v else "N/A")


def _std_date(val):
    if not val or val == "N/A":
        return "N/A"
    v = str(val).strip()
    patterns = [
        (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', lambda m: f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"),
        (r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', lambda m: f"{m.group(3)}-{_mon(m.group(2))}-{int(m.group(1)):02d}"),
        (r'(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})', lambda m: f"{m.group(3)}-{_mon(m.group(2))}-{int(m.group(1)):02d}"),
    ]
    for pat, fmt in patterns:
        m = re.match(pat, v)
        if m:
            try:
                return fmt(m)
            except:
                pass
    return v


def _mon(s):
    m = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
         "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
         "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
         "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
         "november": 11, "december": 12}
    return f"{m.get(s.lower(), 1):02d}"


def _std_payout(val):
    if not val or val == "N/A":
        return "N/A"
    v = str(val).strip()
    if "as per" in v.lower():
        return v
    if "%" in v:
        nums = re.findall(r'\d+\.?\d*', v)
        return nums[0] if nums else v
    return v


# ============== VALIDATION ==============
def validate_record(record):
    errors = []
    app = record.get("APPLICATION NUMBER", "")
    cust = record.get("CUSTOMER NAME", "")
    if not app or app == "N/A":
        errors.append("APPLICATION NUMBER is required")
    if not cust or cust == "N/A":
        errors.append("CUSTOMER NAME is required")
    return {"is_valid": len(errors) == 0, "errors": errors}


# ============== UPSERT ==============
def _record_hash(record):
    keys = ["APPLICATION NUMBER", "CUSTOMER NAME", "BANK NAME",
            "TOTAL DISB AMOUNT", "DISB DATE", "STATUS", "PRODUCT"]
    return hashlib.md5("|".join([str(record.get(k, "")) for k in keys]).encode()).hexdigest()


def upsert_records(records):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    results = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0, "details": []}

    for rec in records:
        try:
            app_no = rec.get("APPLICATION NUMBER")
            if not app_no or app_no == "N/A":
                results["failed"] += 1
                results["details"].append({"action": "failed", "reason": "No APPLICATION NUMBER", "application_number": app_no})
                continue

            c.execute("SELECT * FROM loan_records WHERE application_number = ?", (app_no,))
            existing = c.fetchone()
            new_hash = _record_hash(rec)

            if existing:
                ex = dict(existing)
                if new_hash == ex.get("record_hash"):
                    results["skipped"] += 1
                    results["details"].append({"action": "skipped", "reason": "Exact duplicate", "application_number": app_no})
                else:
                    updates = []
                    params = []
                    for key in STANDARD_ROW.keys():
                        dbk = DB_COL_MAP[key]
                        if dbk not in ex:
                            continue
                        old_val = ex[dbk] or "N/A"
                        new_val = rec.get(key, "N/A")
                        if old_val == "N/A" and new_val not in ["N/A", ""]:
                            updates.append(f"{dbk} = ?")
                            params.append(new_val)
                        elif key in ["TOTAL DISB AMOUNT", "DISB DATE", "STATUS"] and old_val != new_val and new_val not in ["N/A", ""]:
                            updates.append(f"{dbk} = ?")
                            params.append(new_val)

                    if updates:
                        hist = json.loads(ex.get("history", "[]"))
                        hist.append({"timestamp": datetime.now().isoformat(), "changes": updates})
                        updates.extend(["record_hash = ?", "updated_at = ?", "history = ?"])
                        params.extend([new_hash, datetime.now().isoformat(), json.dumps(hist)])
                        sql = f"UPDATE loan_records SET {', '.join(updates)} WHERE application_number = ?"
                        params.append(app_no)
                        c.execute(sql, params)
                        results["updated"] += 1
                        results["details"].append({"action": "updated", "application_number": app_no, "fields_changed": len(updates) - 3})
                    else:
                        results["skipped"] += 1
                        results["details"].append({"action": "skipped", "reason": "No meaningful change", "application_number": app_no})
            else:
                db_keys = list(DB_COL_MAP.values())
                placeholders = ["?"] * len(db_keys)
                values = [rec.get(k, "N/A") for k in STANDARD_ROW.keys()]
                db_keys.extend(["record_hash", "created_at", "updated_at"])
                placeholders.extend(["?", "?", "?"])
                values.extend([new_hash, datetime.now().isoformat(), datetime.now().isoformat()])
                sql = f"INSERT INTO loan_records ({', '.join(db_keys)}) VALUES ({', '.join(placeholders)})"
                c.execute(sql, values)
                results["inserted"] += 1
                results["details"].append({"action": "inserted", "application_number": app_no})

            conn.commit()
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"action": "failed", "reason": str(e), "application_number": rec.get("APPLICATION NUMBER", "")})

    conn.close()
    return results


# ============== FASTAPI APP ==============
app = FastAPI(title="Fineoteric Email Processor", version="4.1.0")

@app.on_event("startup")
def startup():
    init_db()


class ProcessRequest(BaseModel):
    html_body: str = ""
    plain_text: str = ""
    subject: str = ""
    sender: str = ""
    date: str = ""


class ClassifyRequest(BaseModel):
    subject: str = ""
    sender: str = ""
    body_text: str = ""
    body_html: str = ""


class MarkReadRequest(BaseModel):
    message_id: str = ""
    thread_id: str = ""


class ValidateRequest(BaseModel):
    records: List[Dict]


class UpsertRequest(BaseModel):
    records: List[Dict]


@app.get("/")
def root():
    return {"message": "Fineoteric Email Processor API", "version": "4.1.0", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy", "version": "4.1.0", "ml_mode": ML_MODE, "db_path": DB_PATH, "timestamp": datetime.now().isoformat()}


@app.get("/config")
def config():
    return {"ml_mode": ML_MODE, "db_path": DB_PATH, "model_path": MODEL_PATH, "total_fields": 39,
            "mandatory_fields": ["APPLICATION NUMBER", "CUSTOMER NAME"], "fallback_value": "N/A"}


@app.post("/classify")
def classify_email(req: ClassifyRequest):
    classifier = MLClassifier()
    result = classifier.classify(req.subject, req.sender, req.body_text, req.body_html)
    return {"success": True, "classification": result}


@app.post("/extract")
def extract_email(req: ProcessRequest):
    records = parse_email_html(req.html_body, req.plain_text)
    return {"success": True, "record_count": len(records), "records": records}


@app.post("/validate")
def validate_records(req: ValidateRequest):
    validated = []
    for rec in req.records:
        v = validate_record(rec)
        validated.append({"record": rec, "validation": v})
    all_valid = all(v["validation"]["is_valid"] for v in validated)
    return {"success": True, "all_valid": all_valid, "results": validated}


@app.post("/upsert")
def upsert_endpoint(req: UpsertRequest):
    results = upsert_records(req.records)
    return {"success": True, "upsert": results}


@app.post("/process")
def process_email(req: ProcessRequest):
    classifier = MLClassifier()
    classification = classifier.classify(req.subject, req.sender, req.plain_text, req.html_body)

    if not classification["is_relevant"]:
        return {"success": True, "action": "skipped", "reason": classification["reason"],
                "pipeline": {"classification": classification, "sender_validation": None, "extraction": None, "validation": None, "upsert": None},
                "records": []}

    domain = req.sender.split("@")[-1].lower() if "@" in req.sender else ""
    sender_valid = True

    records = parse_email_html(req.html_body, req.plain_text)
    valid_records, invalid_records = [], []

    for rec in records:
        v = validate_record(rec)
        if v["is_valid"]:
            valid_records.append(rec)
        else:
            invalid_records.append({"record": rec, "errors": v["errors"]})

    upsert_results = upsert_records(valid_records) if valid_records else None

    if invalid_records:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for inv in invalid_records:
            c.execute("INSERT INTO review_queue (email_id, subject, sender, reason, raw_data) VALUES (?, ?, ?, ?, ?)",
                      ("", req.subject, req.sender, json.dumps(inv["errors"]), json.dumps(inv["record"])))
        conn.commit()
        conn.close()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO email_log (email_id, subject, sender, action, details) VALUES (?, ?, ?, ?, ?)",
              ("", req.subject, req.sender, "processed", json.dumps({"classification": classification,
               "records_found": len(records), "valid": len(valid_records), "invalid": len(invalid_records)})))
    conn.commit()
    conn.close()

    msg = f"Processed {len(records)}: {upsert_results['inserted'] if upsert_results else 0} inserted, {upsert_results['updated'] if upsert_results else 0} updated, {upsert_results['skipped'] if upsert_results else 0} skipped, {len(invalid_records)} queued" if upsert_results else f"Processed {len(records)}: 0 inserted, 0 updated, 0 skipped, {len(invalid_records)} queued"

    return {"success": True, "action": "processed", "message": msg,
            "pipeline": {"classification": classification,
                         "sender_validation": {"is_valid": True, "domain": domain, "note": "All domains allowed"},
                         "extraction": {"record_count": len(records)},
                         "validation": {"valid": len(valid_records), "invalid": len(invalid_records)},
                         "upsert": upsert_results},
            "records": valid_records}


@app.post("/mark-read")
def mark_read(req: MarkReadRequest):
    return {"success": True, "action": "mark_read", "payload": {"message_id": req.message_id, "thread_id": req.thread_id, "mark_read": True}}


@app.get("/check/{lan}")
def check_lan(lan: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM loan_records WHERE application_number = ?", (lan,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"found": True, "record": dict(row)}
    return {"found": False, "record": None}


@app.get("/metrics")
def metrics():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM loan_records")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM review_queue")
    review = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM email_log WHERE action = 'processed'")
    processed = c.fetchone()[0]
    conn.close()
    return {"total_records": total, "review_queue": review, "processed_emails": processed, "ml_mode": ML_MODE}


@app.get("/review-queue")
def review_queue():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM review_queue ORDER BY created_at DESC LIMIT 100")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {"success": True, "count": len(rows), "records": rows}


@app.post("/parse-email")
def parse_email_legacy(req: ProcessRequest):
    records = parse_email_html(req.html_body, req.plain_text)
    return {"success": True, "records": records, "record_count": len(records)}
