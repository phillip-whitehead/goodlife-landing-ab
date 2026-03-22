# Good Life Bahamas — CRO Analytics

This directory contains the analytics and weekly iteration tooling for The Good Life Bahamas CRO programme.

---

## Overview

The system triangulates three data sources every week:

| Source | What it provides |
|---|---|
| **GA4** | Sessions, bounce rate, form funnel events, per-version page metrics |
| **HubSpot** | Pipeline stage counts, deal conversion, leads by AB version |
| **Microsoft Clarity** | Heatmaps, scroll depth, session recordings (reviewed manually) |

From those signals, `weekly_cycle.py` automatically:

1. Identifies the best-performing landing page version (by inquiry conversion rate)
2. Derives a hypothesis for the next iteration
3. Generates `versions/week-N.html` — a copy of the winning version with an updated hypothesis comment block and version-tracking cookie
4. Appends a metrics row to `GoodLife_CRO_Tracker.xlsx`
5. Updates `versions/index.html` to show the new week card in the Weekly Evolution timeline
6. Commits and pushes to deploy

---

## Setup

### 1. Install Python dependencies

```bash
cd cro-analytics
pip install -r requirements.txt
pip install openpyxl   # required for Excel tracker
```

The full dependency list:

```
google-analytics-data>=0.18.0
google-auth>=2.20.0
requests>=2.31.0
python-dotenv>=1.0.0
openpyxl>=3.1.0
```

### 2. Create a `.env` file

```bash
cp .env.example .env
```

Edit `.env` and fill in the three required values:

```env
# Path to your GA4 service account JSON key file
GA4_KEY_FILE=/absolute/path/to/your-service-account-key.json

# GA4 property ID (Admin > Property Settings > Property ID)
GA4_PROPERTY_ID=375125067

# HubSpot Private App token (Settings > Integrations > Private Apps)
HUBSPOT_TOKEN=pat-na1-xxxxxxxxxxxx
```

The `.env` file is gitignored. Never commit real credentials.

### 3. GA4 service account

1. Go to [Google Cloud Console](https://console.cloud.google.com) > IAM & Admin > Service Accounts
2. Create a service account, download the JSON key
3. In GA4 Admin > Property Access Management, add the service account email with **Viewer** role
4. Set `GA4_KEY_FILE` to the absolute path of the downloaded JSON

### 4. HubSpot Private App

1. In HubSpot: Settings > Integrations > Private Apps > Create a private app
2. Grant scopes: `crm.objects.contacts.read`, `crm.objects.deals.read`
3. Copy the access token into `HUBSPOT_TOKEN`

---

## Running the weekly cycle

```bash
# From the repo root:
python3 cro-analytics/weekly_cycle.py

# Or from inside cro-analytics/:
cd cro-analytics
python3 weekly_cycle.py
```

The script is designed to be run once per week, ideally on the same day each week (e.g. Monday morning). It detects the current week number automatically by counting existing `versions/week-N.html` files.

### Automating with cron

```bash
# Run every Monday at 9am:
0 9 * * 1 cd /path/to/repo && python3 cro-analytics/weekly_cycle.py >> cro-analytics/logs/weekly.log 2>&1
```

---

## Running the standalone report

To generate just the analytics report (without creating a new version):

```bash
python3 cro-analytics/cro_report.py              # last 7 days, auto-saves HTML
python3 cro-analytics/cro_report.py --days 30   # last 30 days
python3 cro-analytics/cro_report.py --output custom_report.html
```

Reports are saved to `cro-analytics/reports/cro_report_YYYYMMDD.html`.

---

## Files created

Each weekly cycle creates or updates:

| File | Description |
|---|---|
| `versions/week-N.html` | New landing page iteration for the week |
| `GoodLife_CRO_Tracker.xlsx` | Excel tracker with one row per week (created on first run) |
| `versions/index.html` | Updated with the new week card in the Weekly Evolution timeline |
| `cro-analytics/reports/cro_report_YYYYMMDD.html` | Full analytics report for the week |

---

## Metrics tracked in the Excel sheet

Each row in `GoodLife_CRO_Tracker.xlsx` contains:

| Column | Description |
|---|---|
| **Week** | Week number (1, 2, 3, …) |
| **Date Generated** | Date the cycle was run |
| **Week Start / End** | The 7-day window the data covers |
| **Base Version** | The version this week's page was forked from |
| **Hypothesis (short)** | The testable hypothesis for this week (first 120 chars) |
| **Total Sessions (7d)** | GA4 sessions for the 7-day window |
| **Mobile % of Sessions** | Share of traffic that is mobile |
| **Avg Bounce Rate %** | Average bounce rate across all version pages |
| **Form Starts** | GA4 `form_start` event count |
| **Form Submits** | GA4 `form_submit` + `inquire_form_submit` events |
| **Form Completion %** | Submits / Starts × 100 |
| **Inquiry Rate % (submits/sessions)** | Form submits / total sessions × 100 |
| **New HubSpot Deals (7d)** | Deals created in HubSpot in the period |
| **Converted (Booked, 7d)** | Deals that reached "Booked" stage or beyond in the period |
| **Period Conversion %** | Converted / New Deals × 100 |
| **Close Lost % (all-time pipeline)** | Close Lost deals / total pipeline deals |
| **Booked or Beyond (all-time)** | Total deals at Booked or beyond stages |
| **Best Version (by conv rate)** | The version with the highest inquiry conversion rate |
| **Best Version Conv Rate %** | Conversion rate of the best version |
| **HTML File** | Filename of the generated HTML (e.g. `week-3.html`) |

---

## Weekly workflow (manual steps)

The automated script handles data pull, file generation, and deployment. The recommended weekly ritual:

1. **Run the cycle** on Monday morning: `python3 cro-analytics/weekly_cycle.py`
2. **Review the HTML report** in `cro-analytics/reports/` — read all insights and recommendations
3. **Review Clarity** recordings from the past week — look for rage clicks, scroll dropoff, form abandonment
4. **Augment the generated page** — `weekly_cycle.py` creates a baseline copy; a developer or LLM can then layer in the specific UX changes implied by the hypothesis before the page goes fully live
5. **Check the index** at `https://ccd69671.goodlife-landing-ab.pages.dev/versions/` to confirm the week card appeared
6. **Update the tracker** with any manual observations in the Notes column of the Excel sheet

---

## Architecture notes

- `weekly_cycle.py` imports `pull_ga4_data`, `pull_hubspot_data`, `generate_insights` directly from `cro_report.py` — no duplication
- Week detection is file-system based: counts `versions/week-N.html` files
- Base version selection: highest HubSpot contacts-per-session across all tracked versions; falls back to `v5-best-combined` if no data
- Hypothesis selection: decision tree that prioritises form completion rate, mobile bounce, then pipeline close-lost rate, then the top recommendation from `generate_insights()`
- The generated HTML is a verbatim copy of the base version with (a) a metadata comment block at the top and (b) the version-tracking cookie updated to `week-N`
- The index.html injection uses a `<!-- /weekly-evolution-cards -->` marker comment to locate the insertion point
