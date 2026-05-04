#!/usr/bin/env python3
"""
=============================================================================
Snipe-IT assets → Google Sheets (Custom Report layout)
=============================================================================

WHAT IT DOES
  Exports all inventory assets from Snipe-IT into a Google Sheet, using the
  same column layout as Snipe-IT’s Custom Report.

HOW IT WORKS
  1. Fetches assets via Snipe-IT API (GET /hardware, paginated).
  2. Builds ~85 columns per row (standard + custom fields).
  3. Matches Snipe-IT Custom Report column order (no dedicated custom-report API).
  4. Authenticates to Google Sheets with a service account JSON file.
  5. Uses a fixed worksheet name: "Report Principal" (stable for IMPORTRANGE).
  6. If the sheet exists, clears it; otherwise creates it.
  7. Uploads header + rows in batches (up to 5000 rows per request).

PREREQUISITES (details: README.md)
  - Snipe-IT settings in app/snipe_it_config.py (api_token, api_base_url, web_ui_base_url)
  - google_credentials.json filled from Google Cloud (template ships with <PLACEHOLDERS>)
  - GOOGLE_SHEET_URL below; sheet shared with service account email from that JSON

RUN
  python3 generate_custom_report_gsheets.py
  python3 generate_custom_report_gsheets.py --schedule
=============================================================================
"""
import json
import sys
import os
from datetime import datetime, timedelta
import schedule
import time
import gspread
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from snipe_it_config import SNIPE_IT_CONFIG
import requests
import urllib3
from google.oauth2.service_account import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Snipe-IT: app/snipe_it_config.py | Google: path from env or default file in project root
SNIPE_IT_API_TOKEN = SNIPE_IT_CONFIG["api_token"]
SNIPE_IT_API_BASE_URL = SNIPE_IT_CONFIG["api_base_url"]
SNIPE_IT_WEB_UI_BASE_URL = (SNIPE_IT_CONFIG.get("web_ui_base_url") or "").rstrip("/")
# Full browser URL of the target spreadsheet; share the sheet with client_email from google_credentials.json
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/<YOUR_SHEET_ID>/edit"
GOOGLE_SERVICE_ACCOUNT_JSON_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS", "google_credentials.json"
)

# Fixed worksheet title (stable for IMPORTRANGE and bookmarks)
REPORT_WORKSHEET_TITLE = "Report Principal"


def nested_get(data, *keys, default=""):
    """Walk nested dicts, e.g. asset['model']['name'], without raising."""
    current = data
    for key in keys:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default


def format_snipe_date(value):
    """Turn Snipe-IT JSON date fields into plain text for the sheet."""
    if not value:
        return ""
    if isinstance(value, dict):
        return value.get("formatted", "") or value.get("date", "")
    return str(value)


def get_custom_field_value(custom_fields, field_name):
    """Read a custom field value by its Snipe-IT label (e.g. 'CPU', 'RAM')."""
    if not custom_fields or not isinstance(custom_fields, dict):
        return ""
    field = custom_fields.get(field_name, {})
    if isinstance(field, dict):
        return field.get("value", "")
    return str(field) if field else ""


def build_asset_row(asset):
    """Map one Snipe-IT hardware JSON object to one sheet row (~85 columns)."""

    assignee = asset.get("assigned_to", {}) or {}
    username = nested_get(assignee, "username")
    assignee_type = nested_get(assignee, "type")
    employee_number = nested_get(assignee, "employee_num")
    manager_name = nested_get(assignee, "manager", "name")
    department_name = nested_get(assignee, "department", "name")

    location = asset.get("location", {}) or {}
    location_name = nested_get(location, "name")
    location_address1 = nested_get(location, "address")
    location_address2 = nested_get(location, "address2")
    location_city = nested_get(location, "city")
    location_state = nested_get(location, "state")
    location_country = nested_get(location, "country")
    location_zip = nested_get(location, "zip")

    default_location = asset.get("rtd_location", {}) or {}
    default_location_name = nested_get(default_location, "name")
    default_location_address1 = nested_get(default_location, "address")
    default_location_address2 = nested_get(default_location, "address2")
    default_location_city = nested_get(default_location, "city")
    default_location_state = nested_get(default_location, "state")
    default_location_country = nested_get(default_location, "country")
    default_location_zip = nested_get(default_location, "zip")

    custom_fields_map = asset.get("custom_fields", {}) or {}

    hardware_url = ""
    if SNIPE_IT_WEB_UI_BASE_URL:
        hardware_url = f"{SNIPE_IT_WEB_UI_BASE_URL}/hardware/{asset.get('id', '')}"

    return [
        asset.get("id", ""),
        nested_get(asset, "company", "name"),
        asset.get("name", ""),
        asset.get("asset_tag", ""),
        nested_get(asset, "model", "name"),
        nested_get(asset, "model", "model_number"),
        nested_get(asset, "category", "name"),
        nested_get(asset, "manufacturer", "name"),
        asset.get("serial", ""),
        format_snipe_date(asset.get("purchase_date")),
        asset.get("purchase_cost", ""),
        asset.get("eol", ""),
        asset.get("warranty_months", ""),
        format_snipe_date(asset.get("warranty_expires")),
        asset.get("book_value", "0.00"),
        "", "",  # Diff, Fully Depreciated
        asset.get("order_number", ""),
        nested_get(asset, "supplier", "name"),
        location_name,
        location_address1,
        location_address2,
        location_city,
        location_state,
        location_country,
        location_zip,
        default_location_name,
        default_location_address1,
        default_location_address2,
        default_location_city,
        default_location_state,
        default_location_country,
        default_location_zip,
        username,
        assignee_type,
        username,
        employee_number,
        manager_name,
        department_name,
        nested_get(assignee, "jobtitle"),
        nested_get(assignee, "phone"),
        "", "", "", nested_get(assignee, "country"), "",
        nested_get(asset, "status_label", "name"),
        format_snipe_date(asset.get("last_checkout")),
        format_snipe_date(asset.get("last_checkin")),
        format_snipe_date(asset.get("expected_checkin")),
        format_snipe_date(asset.get("created_at")),
        format_snipe_date(asset.get("updated_at")),
        "Yes" if asset.get("deleted_at") else "",
        format_snipe_date(asset.get("last_audit_date")),
        format_snipe_date(asset.get("next_audit_date")),
        asset.get("notes", ""),
        hardware_url,
        get_custom_field_value(custom_fields_map, "Nota Fiscal"),
        get_custom_field_value(custom_fields_map, "third_party"),
        get_custom_field_value(custom_fields_map, "Link NF"),
        get_custom_field_value(custom_fields_map, "Leasing Start Date"),
        get_custom_field_value(custom_fields_map, "Leasing End Date"),
        get_custom_field_value(custom_fields_map, "Validated"),
        get_custom_field_value(custom_fields_map, "SIM Card"),
        get_custom_field_value(custom_fields_map, "Termo de Responsabilidade Enviado"),
        get_custom_field_value(custom_fields_map, "Termo de Responsabilidade Assinado"),
        get_custom_field_value(custom_fields_map, "No de Factura"),
        get_custom_field_value(custom_fields_map, "Repair Reason"),
        get_custom_field_value(custom_fields_map, "Warranty Expiration Date"),
        get_custom_field_value(custom_fields_map, "Type"),
        get_custom_field_value(custom_fields_map, "Enviroment"),
        get_custom_field_value(custom_fields_map, "Nubank Owner"),
        get_custom_field_value(custom_fields_map, "OS Name"),
        get_custom_field_value(custom_fields_map, "Allocated"),
        get_custom_field_value(custom_fields_map, "IP Address"),
        get_custom_field_value(custom_fields_map, "MAC Address"),
        get_custom_field_value(custom_fields_map, "Leasing Contract"),
        get_custom_field_value(custom_fields_map, "Leasing Company"),
        get_custom_field_value(custom_fields_map, "substatus"),
        get_custom_field_value(custom_fields_map, "CPU"),
        get_custom_field_value(custom_fields_map, "RAM"),
        get_custom_field_value(custom_fields_map, "Storage"),
        get_custom_field_value(custom_fields_map, "Leasing Date of Return"),
        get_custom_field_value(custom_fields_map, "Fixed Asset Number"),
        get_custom_field_value(custom_fields_map, "ITCLI User Executer"),
        get_custom_field_value(custom_fields_map, "Ticket Link"),
        get_custom_field_value(custom_fields_map, "Year"),
        get_custom_field_value(custom_fields_map, "Display Size"),
        "",
    ]


def fetch_all_hardware_assets():
    """Paginate GET /hardware until all rows are collected."""
    logger.info("Fetching assets from Snipe-IT...")

    headers = {
        "authorization": f"Bearer {SNIPE_IT_API_TOKEN}",
        "accept": "application/json",
        "content-type": "application/json",
    }

    all_assets = []
    page_size = 500
    offset = 0

    while True:
        url = f"{SNIPE_IT_API_BASE_URL}/hardware?limit={page_size}&offset={offset}"

        try:
            response = requests.get(url, headers=headers, verify=False, timeout=30)

            if response.status_code != 200:
                logger.error(f"API error: {response.status_code}")
                break

            payload = response.json()
            rows = payload.get("rows", [])
            total = payload.get("total", 0)

            if not rows:
                break

            all_assets.extend(rows)
            print(f"   📦 Fetched: {len(all_assets)} of {total} assets...")

            if len(rows) < page_size:
                break

            offset += page_size

        except Exception as err:
            logger.error(f"Error fetching assets: {err}", exc_info=True)
            break

    logger.info(f"Total assets fetched: {len(all_assets)}")
    return all_assets


def upload_rows_to_google_sheet(data_rows):
    """Authorize with Google and write header + data rows to the worksheet."""
    logger.info("Connecting to Google Sheets...")

    column_headers = [
        "ID", "Company", "Asset Name", "Asset Tag", "Model", "Model No.", "Category",
        "Manufacturer", "Serial", "Purchased", "Cost", "EOL", "Warranty",
        "Warranty Expires", "Current Value", "Diff", "Fully Depreciated",
        "Order Number", "Supplier", "Location",
        "Address", "Address", "City", "State", "Country", "Zip",
        "Default Location",
        "Address", "Address", "City", "State", "Country", "Zip",
        "Checked Out", "Type", "Username", "Employee No.", "Manager", "Department",
        "Title", "Phone", "User Address", "User City", "User State", "User Country",
        "User Zip", "Status", "Checkout Date", "Last Checkin Date",
        "Expected Checkin Date", "Created At", "Updated at", "Deleted",
        "Last Audit", "Next Audit Date", "Notes", "URL",
        "Nota Fiscal", "third_party", "Link NF", "Leasing Start Date",
        "Leasing End Date", "Validated", "SIM Card",
        "Termo de Responsabilidade Enviado", "Termo de Responsabilidade Assinado",
        "No de Factura", "Repair Reason", "Warranty Expiration Date", "Type",
        "Enviroment", "Nubank Owner", "OS Name", "Allocated", "IP Address",
        "MAC Address", "Leasing Contract", "Leasing Company", "substatus",
        "CPU", "RAM", "Storage", "Leasing Date of Return", "Fixed Asset Number",
        "ITCLI User Executer", "Ticket Link", "Year", "Display Size", "",
    ]

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    google_credentials = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON_PATH, scopes=scopes
    )
    gspread_client = gspread.authorize(google_credentials)
    spreadsheet = gspread_client.open_by_url(GOOGLE_SHEET_URL)

    try:
        worksheet = spreadsheet.worksheet(REPORT_WORKSHEET_TITLE)
        worksheet.clear()
        logger.info(f"Worksheet '{REPORT_WORKSHEET_TITLE}' found and cleared.")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=REPORT_WORKSHEET_TITLE, rows=len(data_rows) + 10, cols=90
        )
        logger.info(f"New worksheet '{REPORT_WORKSHEET_TITLE}' created.")

    all_sheet_values = [column_headers] + data_rows

    logger.info(f"Uploading {len(data_rows)} rows to Google Sheets...")

    batch_size = 5000
    total_batches = (len(all_sheet_values) + batch_size - 1) // batch_size

    for batch_index, start_row in enumerate(range(0, len(all_sheet_values), batch_size), 1):
        batch_values = all_sheet_values[start_row : start_row + batch_size]
        range_start_row = start_row + 1
        print(f"   📤 Uploading batch {batch_index}/{total_batches}...")
        worksheet.update(
            values=batch_values,
            range_name=f"A{range_start_row}",
            value_input_option="USER_ENTERED",
        )

    logger.info("Upload completed successfully")

    sheet_base = GOOGLE_SHEET_URL.rstrip("/").split("#")[0]
    if not sheet_base.endswith("/edit"):
        sheet_base = f"{sheet_base}/edit"
    worksheet_url = f"{sheet_base}#gid={worksheet.id}"
    return worksheet_url, REPORT_WORKSHEET_TITLE


def is_weekday():
    """Return True Monday–Friday (local time)."""
    return datetime.now().weekday() < 5


def run_export(skip_weekends=False):
    """Fetch from Snipe-IT, build rows, upload to Google Sheets.

    skip_weekends: when True (used with --schedule), skip Saturday and Sunday.
    """
    if skip_weekends and not is_weekday():
        logger.info("Weekend - skipping export (scheduled run)")
        return

    started_at = datetime.now()
    logger.info("=" * 70)
    logger.info("Starting export process")
    logger.info("=" * 70)

    assets = fetch_all_hardware_assets()
    if not assets:
        logger.warning("No assets found")
        return

    logger.info(f"Processing {len(assets)} assets...")
    data_rows = []
    for index, asset in enumerate(assets, 1):
        data_rows.append(build_asset_row(asset))
        if index % 1000 == 0:
            print(f"   ⚙️  Processed: {index}/{len(assets)} assets...")

    logger.info(f"Processed {len(data_rows)} rows")

    try:
        sheet_url, worksheet_title = upload_rows_to_google_sheet(data_rows)

        finished_at = datetime.now()
        elapsed = finished_at - started_at
        minutes_elapsed = int(elapsed.total_seconds() / 60)
        seconds_elapsed = int(elapsed.total_seconds() % 60)

        logger.info("=" * 70)
        logger.info("Export completed successfully")
        logger.info(f"Sheet: {worksheet_title}")
        logger.info(f"Total assets: {len(data_rows)}")
        logger.info(f"Duration: {minutes_elapsed}min {seconds_elapsed}s")
        logger.info(f"URL: {sheet_url}")
        logger.info("=" * 70)

    except Exception as err:
        logger.error(f"Export failed: {err}", exc_info=True)


def run_scheduler():
    """Run scheduled exports twice on weekdays (08:00 and 12:00, local machine time)."""
    schedule.every().day.at("08:00").do(run_export, skip_weekends=True)
    schedule.every().day.at("12:00").do(run_export, skip_weekends=True)

    logger.info("Snipe-IT Export - Scheduler Started")
    logger.info("Daily exports at 08:00 and 12:00 (weekends skipped)")

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            break
        except Exception as err:
            logger.error(f"Scheduler error: {err}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args()

    if args.schedule:
        run_scheduler()
    else:
        run_export()
