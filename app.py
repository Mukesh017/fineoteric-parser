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

# ============== 39 FIELDS — EXACT SHEET MATCH ==============
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

# ============== EMAIL PARSER ==============
def parse_email_html(html_body, plain_text=""):
    records = []
    if not html_body and not plain_text:
        return records
    soup = BeautifulSoup(html_body or plain_text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    records = _parse_format_3(soup, text, lines)
    if not records:
        records = _parse_format_2(soup, text, lines)
    if not records:
        records = _parse_format_1(soup, text, lines)
    if not records and plain_text:
        records = _parse_plain_text(plain_text)
    if not records and text:
        records = _parse_plain_text(text)
    return [standardize_record(r) for r in records]

def _parse_format_1(soup, text, lines):
    records = []
    record = dict(STANDARD_ROW)
    for line in lines:
        if ":" not in line: continue
        key, val = line.split(":", 1)
        _map_cell_to_field(record, key.strip(), val.strip())
    if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
        records.append(record)
    return records if records else None

def _parse_format_2(soup, text, lines):
    records = []
    record = dict(STANDARD_ROW)
    for line in lines:
        if ":" not in line: continue
        key, val = line.split(":", 1)
        _map_cell_to_field(record, key.strip(), val.strip())
    if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
        records.append(record)
    return records if records else None

def _parse_format_3(soup, text, lines):
    records = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2: continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not headers: continue
        cust_cols = []
        for idx, h in enumerate(headers):
            if any(k in h for k in ["customer", "applicant", "name", "lan", "application"]):
                cust_cols.append(idx)
        if len(cust_cols) >= 2:
            for col_idx in cust_cols:
                record = dict(STANDARD_ROW)
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if col_idx < len(cells) and cells:
                        row_header = cells[0].get_text(strip=True)
                        cell_text = cells[col_idx].get_text(strip=True)
                        _map_cell_to_field(record, row_header, cell_text)
                if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
                    records.append(record)
    return records if records else None

def _parse_plain_text(text):
    """Parse plain text with space-separated labels (no colons)."""
    records = []
    record = dict(STANDARD_ROW)
    text_clean = text.replace("\n", " ").replace("\r", " ").strip()
    
    # Extract Customer Name / Company Name
    cust_match = re.search(r'Customer\s*name[/\\]?\s*Company\s*Name\s+([^-]+?)(?:\s*[-\u2013]\s*NBFC|Bank|$)', text_clean, re.IGNORECASE)
    if cust_match:
        record["CUSTOMER NAME"] = cust_match.group(1).strip()
    
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
    
    # Fallback: colon-separated format
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        if ":" in line:
            key, val = line.split(":", 1)
            _map_cell_to_field(record, key.strip(), val.strip())
    
    if record["CUSTOMER NAME"] or record["APPLICATION NUMBER"]:
        records.append(record)
    return records if records else []

def _map_cell_to_field(record, header_text, cell_text):
    h = header_text.lower()
    if "customer" in h and "name" in h:
        record["CUSTOMER NAME"] = cell_text
    elif "application" in h and any(x in h for x in ["id", "number", "no", "lan"]):
        record["APPLICATION NUMBER"] = cell_text
    elif "company" in h and "name" in h:
        record["COMPANY NAME"] = cell_text
    elif "bank" in h and "name" in h:
        record["BANK NAME"] = cell_text
    elif "code" in h and "dsa" in h:
        record["CODE"] = cell_text
    elif "branch" in h:
        record["BRANCH"] = cell_text
    elif "rm" in h and "name" in h:
        record["RM NAME"] = cell_text
    elif "product" in h:
        record["PRODUCT"] = cell_text
    elif "connector" in h and "2" not in h and "payout" not in h:
        record["CONNECTOR"] = cell_text
    elif "unit head" in h and "payout" not in h and "%" not in h and "amt" not in h:
        record["UNIT HEAD"] = cell_text
    elif "sm" in h and "name" in h:
        record["SM NAME"] = cell_text
    elif "executive" in h:
        record["EXECUTIVE"] = cell_text
    elif "region" in h:
        record["REGION"] = cell_text
    elif "status" in h and "bill" not in h:
        record["STATUS"] = cell_text
    elif "disburs" in h and "amount" in h:
        record["TOTAL DISB AMOUNT"] = cell_text
    elif "disburs" in h and "date" in h:
        record["DISB DATE"] = cell_text
    elif "spill" in h or "fresh" in h:
        record["SPILL - FRESH"] = cell_text
    elif "profile" in h:
        record["PROFILE"] = cell_text
    elif "bank payout" in h and "%" in h:
        record["BANK PAYOUT%"] = cell_text
    elif "bank payout" in h and ("amt" in h or "amount" in h):
        record["BANK PAYOUTAMT"] = cell_text
    elif "connector payout" in h and "2" not in h and "%" in h:
        record["CONNECTOR PAYOUT%"] = cell_text
        record["OTHER PAYOUT %"] = cell_text
    elif "connector payout" in h and "2" not in h and ("amt" in h or "amount" in h):
        record["CONNECTOR PAYOUT AMT"] = cell_text
    elif "connector 2 payout" in h and "%" in h:
        record["CONNECTOR 2 PAYOUT%"] = cell_text
    elif "connector 2 payout" in h and ("amt" in h or "amount" in h):
        record["CONNECTOR 2 PAYOUT AMT"] = cell_text
    elif "unit head payout" in h and "%" in h:
        record["UNIT HEAD%"] = cell_text
    elif "unit head payout" in h and ("amt" in h or "amount" in h):
        record["UNIT HEAD AMT"] = cell_text
    elif "sm payout" in h and "%" in h:
        record["SM PAYOUT%"] = cell_text
    elif "sm payout" in h and ("amt" in h or "amount" in h):
        record["SM PAYOUT AMT"] = cell_text
    elif "se payout" in h and "%" in h:
        record["SE PAYOUT%"] = cell_text
    elif "se payout" in h and ("amt" in h or "amount" in h):
        record["SE PAYOUT AMT"] = cell_text
    elif "other payout" in h and "%" in h:
        record["OTHER PAYOUT %"] = cell_text
    elif "payout" in h and "%" in h and "bank" not in h and "connector" not in h and "unit" not in h and "sm" not in h and "se" not in h:
        record["CONNECTOR PAYOUT%"] = cell_text
        record["OTHER PAYOUT %"] = cell_text

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
    if not val or val == "N/A": return "N/A"
    v = str(val).strip()
    if "as per" in v.lower(): return v
    if "+gst" in v.lower(): return v
    v = re.sub(r'[₹Rs,\s/]', '', v, flags=re.IGNORECASE)
    nums = re.findall(r'\d+\.?\d*', v)
    return nums[0] if nums else (v if v else "N/A")

def _std_date(val):
    if not val or val == "N/A": return "N/A"
    v = str(val).strip()
    patterns = [
        (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', lambda m: f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"),
        (r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', lambda m: f"{m.group(3)}-{_mon(m.group(2))}-{int(m.group(1)):02d}"),
        (r'(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})', lambda m: f"{m.group(3)}-{_mon(m.group(2))}-{int(m.group(1)):02d}"),
    ]
    for pat, fmt in patterns:
        m = re.match(pat, v)
        if m:
            try: return fmt(m)
            except: pass
    return v

def _mon(s):
    m = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
         "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
    return f"{m.get(s.lower(), 1):02d}"

def _std_payout(val):
    if not val or val == "N/A": return "N/A"
    v = str(val).strip()
    if "as per" in v.lower(): return v
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
                        if dbk not in ex: continue
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
                        results["details"].append({"action": "updated", "application_number": app_no, "fields_changed": len(updates)-3})
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
app = FastAPI(title="Fineoteric Email Processor", version="3.2.0")

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
    return {"message": "Fineoteric Email Processor API", "version": "3.2.0", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "healthy", "version": "3.2.0", "ml_mode": ML_MODE, "db_path": DB_PATH, "timestamp": datetime.now().isoformat()}

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
