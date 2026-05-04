# Snipe-IT → Google Sheets exporter

**Free, small Python utility** that copies your [Snipe-IT](https://snipeitapp.com/) hardware inventory into a **Google Sheet**, using the **same column layout** as Snipe-IT’s built-in **Custom Report**.

Use it for dashboards, sharing with people who do not use Snipe-IT, backups in spreadsheet form, or connecting to other tools (e.g. `IMPORTRANGE`, Looker Studio, etc.). There is **no paid service** in this repo: you run it on your own machine (or server) with your own Snipe-IT and Google accounts.

---

## What it does (in plain language)

1. Connects to your Snipe-IT server with an **API token** (read access to hardware is enough).  
2. Downloads **all** hardware records (paginated through the official `/hardware` API).  
3. Builds one spreadsheet row per asset, including **custom fields**, in the same order as Snipe-IT’s Custom Report.  
4. Opens a **Google Sheet** you choose, clears or creates a tab named **`Report Principal`**, and writes the data there.

Snipe-IT does **not** expose a “custom report” over the API, so this tool rebuilds that layout from raw API data. The result should match what you are used to seeing in the Snipe-IT UI for that report.

---

## What you need before you start

| Requirement | Why |
|-------------|-----|
| **Snipe-IT** you can reach over HTTPS | The script talks to your instance’s API. |
| Permission to create an **API token** in Snipe-IT | Authentication to read hardware. |
| A **Google account** and access to [Google Cloud Console](https://console.cloud.google.com/) | To create a **service account** and enable the **Google Sheets API** (Google’s free tier is usually enough for personal or small-team use; check [Google’s pricing](https://cloud.google.com/pricing) for your case). |
| A **Google Sheet** you own or can edit | Destination for the export; you will share it with the service account email. |
| **Python 3.10+** on your computer | The script is standard Python; basic terminal skills help (copy/paste commands). |

You do **not** need to modify Snipe-IT itself—only configuration files in this project.

---

## Cost and “is it really free?”

- **This repository:** no license fee; use and adapt it for your organization.  
- **Snipe-IT:** depends on how you host it (self-hosted is common in the community).  
- **Google Cloud / Sheets:** creating a service account and using the Sheets API may fall under Google’s free usage limits for small exports; large or very frequent runs are between you and Google’s billing policies.

This project is **not affiliated** with Snipe-IT or Google. Respect their terms of service and your company’s data policies.

---

## Setup overview (do these in order)

1. Install Python dependencies (`venv` recommended).  
2. Fill **`app/snipe_it_config.py`** (Snipe-IT URL + token + optional link base).  
3. Create **`google_credentials.json`** from **`google_credentials.example.json`** and fill it from your Google Cloud key (that file is **gitignored** so it is never pushed). Or set **`GOOGLE_APPLICATION_CREDENTIALS`** to a JSON path outside the repo.  
4. Set **`GOOGLE_SHEET_URL`** inside **`generate_custom_report_gsheets.py`** and **share the sheet** with the service account email (**Editor**).  
5. Run the script once to test; then use `--schedule` if you want automatic weekday runs.

Details for each step are below.

---

## 1. Install Python and dependencies

Open a terminal in the project folder (the one that contains `generate_custom_report_gsheets.py`).

**Recommended:** use a virtual environment so you do not mix packages with other Python projects.

```bash
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# Windows (PowerShell):  venv\Scripts\Activate.ps1
# Windows (cmd):         venv\Scripts\activate.bat

pip install -r requirements.txt
```

If `python3` is not found, try `python` instead (depends on how Python was installed on your system).

---

## 2. Configure Snipe-IT — `app/snipe_it_config.py`

1. **Create your config file** (first time only):  
   ```bash
   cp app/snipe_it_config.example.py app/snipe_it_config.py
   ```  
   Then edit `app/snipe_it_config.py` in any text editor.  
   That file is **gitignored** so your API token stays only on your machine when you clone or pull this repo.

2. **`api_token`** — In Snipe-IT: your avatar (top right) → **Manage API Tokens** → create a token with permission to read **hardware**. Paste the token as a string.

3. **`api_base_url`** — The API root for your instance, **no trailing slash**, must end with **`/api/v1`**.  
   Example: `https://inventory.mycompany.com/api/v1`  
   If this is wrong, you will see connection errors or `404` on `/hardware`.

4. **`web_ui_base_url`** — The same server as in the browser, **without** `/api/v1`.  
   Example: `https://inventory.mycompany.com`  
   Used only to fill the **URL** column in the sheet (clickable links to each asset). Use `""` if you prefer empty links.

The dictionary in the file is named **`SNIPE_IT_CONFIG`** — keep that name so the main script can import it.

---

## 3. Configure Google — `google_credentials.json`

The repository contains **`google_credentials.example.json`** (safe placeholders only). **Copy it** to **`google_credentials.json`** in the project root (same folder as the main script) and then replace every `<...>` with values from the JSON key Google downloads. **`google_credentials.json` is listed in `.gitignore`** so your real private key is not committed by mistake.

**Until you create and fill `google_credentials.json`, Google authentication will fail.**

**Typical flow:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → pick or create a project.  
2. **APIs & Services** → **Library** → search **Google Sheets API** → **Enable**.  
3. **IAM & Admin** → **Service Accounts** → **Create service account** (any display name you like).  
4. Open that service account → **Keys** → **Add key** → **JSON** → a file downloads.  
5. Copy each field from that downloaded JSON into your local **`google_credentials.json`**, replacing the matching placeholders.  
   - **`private_key`** must stay one JSON string with `\n` representing newlines, exactly like Google’s file.  
   - **`client_x509_cert_url`** must match Google’s pattern (the service account email appears with `%40` instead of `@` in the URL path).

**Safer option:** keep the real JSON **outside** this folder, and set the environment variable **`GOOGLE_APPLICATION_CREDENTIALS`** to the **full path** of that file before running the script. The script will use it automatically when set.

---

## 4. Google Sheet — URL and sharing

1. Open **`generate_custom_report_gsheets.py`** and find **`GOOGLE_SHEET_URL`**. Set it to your spreadsheet’s full URL from the browser, for example:  
   `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`

2. In Google Sheets, click **Share** and add the **`client_email`** from your `google_credentials.json` (it looks like `something@your-project.iam.gserviceaccount.com`) with **Editor** access.  
   If you skip this, Google returns **permission denied** even if the JSON is correct.

3. The script always writes to a worksheet titled **`Report Principal`**. If it already exists, its contents are **cleared** and replaced. If it does not exist, it is **created**. You can change the name in code (`REPORT_WORKSHEET_TITLE`) if you need a different tab name for `IMPORTRANGE` or other workflows.

---

## 5. Run the export

**Single run** (good for testing after setup):

```bash
python3 generate_custom_report_gsheets.py
```

Watch the terminal: you should see progress for fetching assets and uploading batches. When it finishes, open your Google Sheet and check the **Report Principal** tab.

**Scheduled runs** (optional): runs **twice on weekdays** at **08:00** and **12:00** in the **local timezone of the machine** where the script runs. **Saturday and Sunday are skipped.** The process must stay open (e.g. leave a terminal or a small VM running):

```bash
python3 generate_custom_report_gsheets.py --schedule
```

Stop it with **Ctrl+C** when you no longer need the scheduler.

---

## Before you push this project to Git (or any public host)

- **Never commit** real API tokens or Google private keys.  
- This repo **`.gitignore`** excludes **`google_credentials.json`** and **`app/snipe_it_config.py`**; only the **`*.example.*`** templates are meant to be public.  
- Review **`git status`** before every commit; avoid **`git add -f`** on ignored secret files.

Testing locally **before** pushing is the right approach.

---

## Troubleshooting

| What you see | What to try |
|----------------|-------------|
| Snipe-IT **401** / **403** | Check **`api_token`** and that the token was not revoked; confirm **`api_base_url`** matches your server and includes **`/api/v1`**. |
| Google **403** / permission denied | Sheets API enabled; spreadsheet **shared** with the exact **`client_email`**; **`GOOGLE_SHEET_URL`** is the correct spreadsheet. |
| Errors about **private key** / invalid JSON | Valid JSON; **`private_key`** is one string with `\n` like Google’s download—do not paste the PEM as multiple JSON strings. |
| SSL / certificate warnings | The script disables SSL verification for Snipe-IT requests (`verify=False`) so self-signed certificates work; for production, fix HTTPS on the Snipe-IT server and consider tightening verification in code. |

---

## Project files (short map)

| File | Purpose |
|------|--------|
| `generate_custom_report_gsheets.py` | Main program: fetch → build rows → upload. |
| `app/snipe_it_config.py` | **Local only** (gitignored): your Snipe-IT URL and token. |
| `app/snipe_it_config.example.py` | Copy this to `snipe_it_config.py` as a starting point. |
| `google_credentials.example.json` | Template for Google credentials (copy to `google_credentials.json`). |
| `google_credentials.json` | **Local only** (gitignored): your real service account JSON. |
| `requirements.txt` | Python packages to install with `pip`. |

---

## Privacy and responsibility

This tool reads **inventory and related fields** from Snipe-IT (including whatever custom fields you configured) and writes them into **Google Sheets**. You are responsible for:

- Who can access Snipe-IT and the API token.  
- Who can access the Google Sheet and the service account key.  
- Compliance with privacy laws and internal policies in your country and organization.

This software is provided **as-is**, without warranty; use it at your own risk and adapt it to your security standards.

---

## Sharing and improving

If you publish this as a **free tool** for others: link to this README, mention that users need their **own** Snipe-IT and Google setup, and encourage people to **test on a copy** of a sheet first (because **Report Principal** is overwritten each run).

Pull requests and forks are welcome if you host the project on a platform that supports them—keep changes small and documented so newcomers can follow along.

Enjoy a simple bridge between Snipe-IT and Google Sheets.
