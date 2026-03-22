#!/usr/bin/env python3
"""
Good Life Bahamas — Weekly CRO Analytics Report
================================================
Triangulates GA4 + HubSpot to surface which landing page versions
are converting best and where leads are being lost in the funnel.

Usage:
  python3 cro_report.py              # generates report for last 7 days
  python3 cro_report.py --days 30   # last 30 days
  python3 cro_report.py --output report.html  # save HTML report

Required env vars (or .env file):
  GA4_KEY_FILE     — path to service account JSON
  GA4_PROPERTY_ID  — GA4 property ID (e.g. 375125067)
  HUBSPOT_TOKEN    — HubSpot private app access token
"""

import os
import sys
import json
import argparse
import requests
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────
# Set these via environment variables or a local .env file (never commit secrets)
# Copy .env.example to .env and fill in your values
GA4_KEY_FILE        = os.getenv('GA4_KEY_FILE', '')
GA4_PROPERTY_ID     = os.getenv('GA4_PROPERTY_ID', '375125067')
HUBSPOT_TOKEN       = os.getenv('HUBSPOT_TOKEN', '')
CLARITY_PROJECT_ID  = os.getenv('CLARITY_PROJECT_ID', '')   # e.g. "abcde12345"
CLARITY_API_KEY     = os.getenv('CLARITY_API_KEY', '')       # from Clarity → Settings → API
HUBSPOT_PORTAL      = '21915863'
PIPELINE_ID         = '48052530'

CLARITY_BASE = 'https://www.clarity.ms/export-data/api/v1'

# Vacation rental pipeline stages in order
PIPELINE_STAGES = {
    '98950175': ('New Inquiry',         0,  False),
    '98950177': ('Guest Response',      1,  False),
    '98950178': ('Latent',              2,  False),
    '99624290': ('Work In Progress',    3,  False),
    '106321323':('Latent 2',            4,  False),
    '98950179': ('Booking Request',     5,  False),
    '98950180': ('Rental Agreement',    6,  False),
    '98950181': ('Booked',             7,  False),
    '114984117':('2nd Payment',        8,  True),
    '106049364':('Close Lost',         9,  True),
    '106049365':('Close Won',          10, True),
    '118729853':('Upcoming Arrival',   11, True),
    '118865958':('Current Stay',       12, True),
    '118844817':('Re-Renter',          13, True),
}

# Landing page versions we track
AB_VERSIONS = {
    'v1':                  'V1 — Control (Original)',
    'v2-above-fold':       'V2 — Above-Fold Focus',
    'v3-anxiety-reduction':'V3 — Anxiety Reduction',
    'v4-soft-cta':         'V4 — Soft CTA',
    'v5-best-combined':    'V5 — Best Combined',
    'v6-problem-solution': 'V6 — Problem / Solution',
    'v7-trust-local':      'V7 — Trust & Local Authority',
    'direct':              'Direct (no version)',
}

HS_HEADERS = {'Authorization': f'Bearer {HUBSPOT_TOKEN}', 'Content-Type': 'application/json'}


# ── Clarity helpers ───────────────────────────────────────────────────────────

def _clarity_headers():
    return {
        'Authorization': f'Bearer {CLARITY_API_KEY}',
        'Content-Type': 'application/json',
    }


def pull_clarity_data(days=7):
    """
    Pull behavioural metrics from Microsoft Clarity API.

    Returns a dict with:
      - by_page:    per page-URL metrics (rage_click_rate, dead_click_rate,
                    scroll_depth, quick_back_rate, session_count)
      - overall:    site-wide aggregates for the period
      - version_pages: filtered to /versions/week-* and /versions/v* paths
      - clarity_link: direct dashboard URL pre-filtered to the period

    Requires env vars: CLARITY_PROJECT_ID, CLARITY_API_KEY
    Gracefully returns empty structure if credentials are missing.
    """
    if not CLARITY_PROJECT_ID or not CLARITY_API_KEY:
        return {
            'available': False,
            'reason': 'CLARITY_PROJECT_ID or CLARITY_API_KEY not set. '
                      'Get your API key from Clarity → Settings → API.',
            'by_page': [],
            'overall': {},
            'version_pages': {},
        }

    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime('%Y-%m-%d')
    end_str   = end_dt.strftime('%Y-%m-%d')

    results = {'available': True, 'by_page': [], 'overall': {}, 'version_pages': {}}

    # 1. Overall project metrics — uses the export-data live-insights endpoint
    # Response is a list: [{"metricName": "RageClickCount", "information": [{...}]}, ...]
    try:
        url = f'{CLARITY_BASE}/project-live-insights'
        params = {
            'projectId': CLARITY_PROJECT_ID,
            'startDate': start_str,
            'endDate':   end_str,
            'granularity': 'daily',
        }
        r = requests.get(url, headers=_clarity_headers(), params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()  # list of {metricName, information:[...]}
            # Index by metricName for easy lookup
            by_metric = {item['metricName']: item.get('information', [{}])[0] for item in data}

            traffic   = by_metric.get('Traffic', {})
            sessions  = int(traffic.get('totalSessionCount', 0))
            eng       = by_metric.get('EngagementTime', {})

            totals = {
                'sessions':            sessions,
                'rage_click_pct':      round(float(by_metric.get('RageClickCount',  {}).get('sessionsWithMetricPercentage', 0)), 2),
                'dead_click_pct':      round(float(by_metric.get('DeadClickCount',  {}).get('sessionsWithMetricPercentage', 0)), 2),
                'quick_back_pct':      round(float(by_metric.get('QuickbackClick',  {}).get('sessionsWithMetricPercentage', 0)), 2),
                'excessive_scroll_pct':round(float(by_metric.get('ExcessiveScroll', {}).get('sessionsWithMetricPercentage', 0)), 2),
                'script_error_pct':    round(float(by_metric.get('ScriptErrorCount',{}).get('sessionsWithMetricPercentage', 0)), 2),
                'avg_scroll_depth':    round(float(by_metric.get('ScrollDepth',     {}).get('averageScrollDepth', 0)), 1),
                'avg_active_time_sec': int(eng.get('activeTime', 0)),
                'avg_total_time_sec':  int(eng.get('totalTime',  0)),
                'pages_per_session':   round(float(traffic.get('pagesPerSessionPercentage', 0)), 2),
            }
            results['overall'] = totals
        else:
            results['overall_error'] = f'HTTP {r.status_code}: {r.text[:200]}'
    except Exception as e:
        results['overall_error'] = str(e)

    # 2. Per-page metrics — filter to version pages
    try:
        url = f'{CLARITY_BASE}/{CLARITY_PROJECT_ID}/metrics'
        params = {
            'startDate': start_str,
            'endDate':   end_str,
            'granularity': 'total',
            'groupBy': 'page',
        }
        r = requests.get(url, headers=_clarity_headers(), params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            rows = data.get('data', []) or data.get('metrics', [])
            version_pages = {}
            all_pages = []
            for row in rows:
                page_url = row.get('pageUrl') or row.get('url') or row.get('page', '')
                sessions = int(row.get('sessionCount', 0))
                entry = {
                    'page':                page_url,
                    'sessions':            sessions,
                    'rage_click_pct':      round(float(row.get('rageClickCount',  0)) / max(sessions,1) * 100, 2),
                    'dead_click_pct':      round(float(row.get('deadClickCount',  0)) / max(sessions,1) * 100, 2),
                    'quick_back_pct':      round(float(row.get('quickBackCount',  0)) / max(sessions,1) * 100, 2),
                    'scroll_depth':        round(float(row.get('scrollDepth',     0)), 1),
                    'avg_active_time_sec': round(float(row.get('activeTime',      0)), 1),
                }
                all_pages.append(entry)
                if '/versions/' in page_url:
                    # Derive version key: /versions/week-3.html → week-3
                    key = page_url.split('/versions/')[-1].replace('.html', '').split('?')[0]
                    version_pages[key] = entry
            results['by_page']      = sorted(all_pages, key=lambda x: -x['sessions'])[:20]
            results['version_pages'] = version_pages
    except Exception as e:
        results['page_error'] = str(e)

    # 3. Top rage-click elements (if endpoint available)
    try:
        url = f'{CLARITY_BASE}/{CLARITY_PROJECT_ID}/clicks'
        params = {
            'startDate':    start_str,
            'endDate':      end_str,
            'clickType':    'rage',
            'limit':        10,
        }
        r = requests.get(url, headers=_clarity_headers(), params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results['top_rage_clicks'] = (data.get('data') or data.get('clicks') or [])[:5]
    except Exception:
        results['top_rage_clicks'] = []

    # 4. Convenience link to Clarity dashboard filtered to this period
    results['clarity_link'] = (
        f'https://clarity.microsoft.com/projects/view/{CLARITY_PROJECT_ID}/impressions'
        f'?date={start_str}_{end_str}'
    )

    return results


def clarity_insights(clarity):
    """Generate actionable insights from Clarity data."""
    insights = []
    recs     = []

    if not clarity.get('available'):
        insights.append(f"⚪ Clarity: {clarity.get('reason', 'not configured')}")
        return insights, recs

    overall = clarity.get('overall', {})
    if not overall:
        return insights, recs

    rage  = overall.get('rage_click_pct',      0)
    dead  = overall.get('dead_click_pct',       0)
    qback = overall.get('quick_back_pct',       0)
    scroll = overall.get('avg_scroll_depth',    0)
    xscroll = overall.get('excessive_scroll_pct', 0)

    if rage > 5:
        insights.append(f"😡 Rage clicks: {rage}% of sessions — users are repeatedly clicking something that isn't responding.")
        recs.append("Check Clarity heatmap for rage-click hotspots. Common causes: non-clickable elements that look interactive, "
                    "broken links, or CTA buttons with delayed JS responses.")

    if dead > 15:
        insights.append(f"💀 Dead clicks: {dead}% of sessions — users click areas with no action.")
        recs.append("Review dead-click map in Clarity. Users may be clicking images, headers, or cards expecting them to link somewhere. "
                    "Either make those elements interactive or remove visual affordances that suggest clickability.")

    if qback > 20:
        insights.append(f"⏪ Quick-back rate: {qback}% — visitors navigate back quickly, signalling a mismatch between ad/search intent and page content.")
        recs.append("High quick-back rate suggests message mismatch. The page headline or hero must mirror the ad copy or Google snippet that brought visitors in.")

    if scroll and scroll < 40:
        insights.append(f"📜 Average scroll depth: {scroll}% — most visitors don't see anything below the hero section.")
        recs.append("Move your highest-converting element (form or primary CTA) above the fold. "
                    "Content below 40% scroll depth is invisible to the majority of visitors.")
    elif scroll and scroll < 60:
        insights.append(f"📜 Scroll depth: {scroll}% — visitors scroll past the hero but stop before the property cards / Why Us section.")

    if xscroll > 10:
        insights.append(f"↕️  Excessive scrolling: {xscroll}% of sessions — users can't find what they're looking for and scroll erratically.")
        recs.append("Excessive scrolling means the page lacks clear visual hierarchy. "
                    "Add a sticky nav or anchor links so visitors can jump directly to properties, pricing, or the inquiry form.")

    # Per-version Clarity insights
    version_pages = clarity.get('version_pages', {})
    if version_pages:
        insights.append("\n── Clarity per-version behaviour ──")
        for vk, vdata in sorted(version_pages.items(), key=lambda x: -x[1]['sessions']):
            insights.append(
                f"  {vk}: {vdata['sessions']} sessions | "
                f"rage={vdata['rage_click_pct']}% | "
                f"dead={vdata['dead_click_pct']}% | "
                f"scroll={vdata['scroll_depth']}% | "
                f"active={vdata['avg_active_time_sec']}s"
            )
        # Flag worst rage-click version
        worst = max(version_pages.items(), key=lambda x: x[1]['rage_click_pct'], default=None)
        if worst and worst[1]['rage_click_pct'] > 3:
            recs.append(f"Version '{worst[0]}' has the highest rage-click rate ({worst[1]['rage_click_pct']}%). "
                        f"Check Clarity heatmap for that page — something is broken or confusing.")

    return insights, recs


# ── GA4 helpers ───────────────────────────────────────────────────────────────

def get_ga4_client():
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(
        GA4_KEY_FILE,
        scopes=['https://www.googleapis.com/auth/analytics.readonly']
    )
    return BetaAnalyticsDataClient(credentials=creds)


def ga4_report(client, dimensions, metrics, start_date, end_date, limit=100, filters=None):
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, Dimension, Metric, DateRange, FilterExpression,
        Filter, FilterExpressionList
    )
    req = RunReportRequest(
        property=f'properties/{GA4_PROPERTY_ID}',
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        limit=limit,
    )
    if filters:
        req.dimension_filter = filters
    resp = client.run_report(req)
    rows = []
    for row in resp.rows:
        dims = [v.value for v in row.dimension_values]
        mets = [v.value for v in row.metric_values]
        rows.append(dims + mets)
    return rows


def pull_ga4_data(days=7):
    """Pull overall site metrics and per-version page metrics."""
    client = get_ga4_client()
    start = f'{days}daysAgo'
    end = 'today'

    results = {}

    # 1. Overall site metrics
    rows = ga4_report(client,
        dimensions=['deviceCategory'],
        metrics=['sessions', 'bounceRate', 'averageSessionDuration', 'screenPageViews'],
        start_date=start, end_date=end
    )
    results['by_device'] = [
        {
            'device': r[0],
            'sessions': int(r[1]),
            'bounce_rate': float(r[2]),
            'avg_duration': float(r[3]),
            'pageviews': int(r[4]),
        }
        for r in rows
    ]

    # 2. Traffic sources
    rows = ga4_report(client,
        dimensions=['sessionDefaultChannelGroup'],
        metrics=['sessions', 'bounceRate', 'conversions'],
        start_date=start, end_date=end
    )
    results['by_channel'] = [
        {
            'channel': r[0],
            'sessions': int(r[1]),
            'bounce_rate': float(r[2]),
            'conversions': int(float(r[3])),
        }
        for r in rows
    ]

    # 3. Key events funnel
    rows = ga4_report(client,
        dimensions=['eventName'],
        metrics=['eventCount', 'sessions'],
        start_date=start, end_date=end,
        limit=50
    )
    key_events = ['form_start', 'form_submit', 'inquire_form_submit',
                  'booknow_button_click_event', 'booking_form_button_click_event',
                  'lead_magnet_popup_impressions', 'session_start']
    results['events'] = {
        r[0]: {'count': int(r[1]), 'sessions': int(r[2])}
        for r in rows if r[0] in key_events
    }

    # 4. Landing page (versions) specific metrics — filter to /versions/ paths
    rows = ga4_report(client,
        dimensions=['pagePath'],
        metrics=['sessions', 'bounceRate', 'averageSessionDuration', 'screenPageViews'],
        start_date=start, end_date=end,
        limit=100
    )
    version_pages = {}
    for r in rows:
        path = r[0]
        if '/versions/v' in path:
            # Extract version key from path like /versions/v4-soft-cta.html
            version_key = path.split('/versions/')[-1].replace('.html', '')
            version_pages[version_key] = {
                'sessions': int(r[1]),
                'bounce_rate': float(r[2]),
                'avg_duration': float(r[3]),
                'pageviews': int(r[4]),
            }
    results['version_pages'] = version_pages

    # 5. Top exit pages (where people leave)
    rows = ga4_report(client,
        dimensions=['pagePath'],
        metrics=['sessions', 'bounceRate'],
        start_date=start, end_date=end,
        limit=20
    )
    results['top_pages'] = [
        {'path': r[0], 'sessions': int(r[1]), 'bounce_rate': float(r[2])}
        for r in sorted(rows, key=lambda x: -float(x[2]))[:10]
        if int(r[1]) > 50
    ]

    return results


# ── HubSpot helpers ───────────────────────────────────────────────────────────

def hs_search(filter_groups, properties, limit=100):
    url = 'https://api.hubapi.com/crm/v3/objects/contacts/search'
    payload = {'filterGroups': filter_groups, 'properties': properties, 'limit': limit}
    r = requests.post(url, headers=HS_HEADERS, json=payload)
    return r.json()


def pull_hubspot_data(days=7):
    """Pull deal funnel data and per-version contact/deal stats."""
    results = {}
    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%dT00:00:00.000Z')

    # 1. Pipeline stage counts (current state)
    stage_counts = {}
    for stage_id, (label, order, closed) in PIPELINE_STAGES.items():
        url = 'https://api.hubapi.com/crm/v3/objects/deals/search'
        payload = {
            'filterGroups': [{
                'filters': [
                    {'propertyName': 'pipeline', 'operator': 'EQ', 'value': PIPELINE_ID},
                    {'propertyName': 'dealstage', 'operator': 'EQ', 'value': stage_id},
                ]
            }],
            'limit': 1,
        }
        r = requests.post(url, headers=HS_HEADERS, json=payload)
        total = r.json().get('total', 0)
        stage_counts[stage_id] = {'label': label, 'count': total, 'closed': closed, 'order': order}
    results['pipeline_stages'] = stage_counts

    # 2. New deals in the period
    url = 'https://api.hubapi.com/crm/v3/objects/deals/search'
    payload = {
        'filterGroups': [{
            'filters': [
                {'propertyName': 'pipeline', 'operator': 'EQ', 'value': PIPELINE_ID},
                {'propertyName': 'createdate', 'operator': 'GTE', 'value': since},
            ]
        }],
        'properties': ['dealstage', 'createdate', 'amount'],
        'limit': 1,
    }
    r = requests.post(url, headers=HS_HEADERS, json=payload)
    results['new_deals_period'] = r.json().get('total', 0)

    # 3. Deals that reached "Booked" or beyond in the period
    booked_stages = ['98950181', '114984117', '106049365', '118729853', '118865958', '118844817']
    payload['filterGroups'][0]['filters'].append(
        {'propertyName': 'dealstage', 'operator': 'IN', 'values': booked_stages}
    )
    r = requests.post(url, headers=HS_HEADERS, json=payload)
    results['converted_period'] = r.json().get('total', 0)

    # 4. Contacts with gl_ab_version set — count by version
    version_contacts = {}
    for version_key in AB_VERSIONS:
        if version_key == 'direct':
            continue
        data = hs_search(
            filter_groups=[{'filters': [
                {'propertyName': 'gl_ab_version', 'operator': 'EQ', 'value': version_key},
                {'propertyName': 'createdate', 'operator': 'GTE', 'value': since},
            ]}],
            properties=['email', 'gl_ab_version', 'createdate'],
            limit=1
        )
        version_contacts[version_key] = data.get('total', 0)
    results['contacts_by_version'] = version_contacts

    # 5. Funnel conversion rate: total active vs close lost vs close won
    total = sum(s['count'] for s in stage_counts.values())
    close_lost = stage_counts.get('106049364', {}).get('count', 0)
    close_won_stages = ['106049365', '118729853', '118865958', '118844817', '114984117']
    close_won = sum(stage_counts.get(s, {}).get('count', 0) for s in close_won_stages)
    booked = sum(stage_counts.get(s, {}).get('count', 0) for s in ['98950181'] + close_won_stages)

    results['funnel_summary'] = {
        'total_deals': total,
        'close_lost': close_lost,
        'close_lost_pct': round(close_lost / total * 100, 1) if total else 0,
        'booked_or_beyond': booked,
        'booked_pct': round(booked / total * 100, 1) if total else 0,
        'close_won': close_won,
    }

    return results


# ── Insight generation ────────────────────────────────────────────────────────

def generate_insights(ga4, hs):
    insights = []
    recs = []

    # ── Traffic source insights
    channels = {c['channel']: c for c in ga4.get('by_channel', [])}

    email = channels.get('Email', {})
    if email and email['sessions'] > 100 and email['conversions'] < 10:
        conv_rate = email['conversions'] / email['sessions'] * 100
        insights.append(f"⚠️  Email traffic ({email['sessions']:,} sessions) converts at only {conv_rate:.2f}% — "
                        f"landing pages linked from emails are losing nearly all visitors.")
        recs.append("Create a dedicated email landing page variant with the offer clearly above the fold, "
                    "matching the email's subject line promise (message-match).")

    paid = channels.get('Paid Social', {})
    if paid and paid['sessions'] > 200 and paid['conversions'] < 20:
        conv_rate = paid['conversions'] / paid['sessions'] * 100
        insights.append(f"⚠️  Paid Social ({paid['sessions']:,} sessions) converts at {conv_rate:.2f}% — "
                        f"ad spend is not reaching the form.")
        recs.append("A/B test a dedicated paid social landing page that matches the ad creative exactly. "
                    "Remove navigation and all exit links.")

    # ── Device insights
    devices = {d['device']: d for d in ga4.get('by_device', [])}
    mobile = devices.get('mobile', {})
    desktop = devices.get('desktop', {})
    if mobile and desktop:
        mob_pct = mobile['sessions'] / (mobile['sessions'] + desktop.get('sessions', 0)) * 100
        if mob_pct > 65:
            insights.append(f"📱  {mob_pct:.0f}% of traffic is mobile. Desktop bounce ({desktop.get('bounce_rate',0)*100:.1f}%) "
                            f"vs mobile ({mobile.get('bounce_rate',0)*100:.1f}%). Focus all CRO effort on mobile-first UX.")
        if desktop.get('bounce_rate', 0) > mobile.get('bounce_rate', 0) * 1.3:
            recs.append("Desktop bounce rate is significantly higher than mobile. Review desktop layout — "
                        "likely the hero doesn't fill the viewport or the CTA is below the fold on large screens.")

    # ── Form funnel insights
    events = ga4.get('events', {})
    form_starts = events.get('form_start', {}).get('count', 0)
    form_submits = events.get('form_submit', {}).get('count', 0) + events.get('inquire_form_submit', {}).get('count', 0)
    total_sessions = events.get('session_start', {}).get('count', 1)
    popup_impressions = events.get('lead_magnet_popup_impressions', {}).get('count', 0)

    if form_starts > 0 and form_submits > 0:
        completion_rate = form_submits / form_starts * 100
        start_rate = form_starts / total_sessions * 100
        insights.append(f"📋  Form start rate: {start_rate:.1f}% of sessions → {form_starts:,} form starts. "
                        f"Completion: only {completion_rate:.1f}% ({form_submits:,} submits). "
                        f"Major drop-off inside the form itself.")
        if completion_rate < 10:
            recs.append("Form completion is critically low (<10%). Test: (1) single email-only field, "
                        "(2) phone number as optional, (3) move form above the fold, "
                        "(4) add 'Takes 30 seconds' microcopy next to submit button.")

    if popup_impressions > form_starts * 3:
        insights.append(f"🔔  The lead magnet popup fires {popup_impressions:,} times vs {form_starts:,} form starts. "
                        f"The popup may be causing friction — visitors are closing it without engaging the main form.")
        recs.append("A/B test removing or delaying the lead magnet popup. It may be interrupting intent signals.")

    # ── Pipeline funnel insights
    funnel = hs.get('funnel_summary', {})
    if funnel.get('close_lost_pct', 0) > 70:
        insights.append(f"🔴  {funnel['close_lost_pct']}% of all deals ({funnel['close_lost']:,}) end in Close Lost. "
                        f"Only {funnel['booked_pct']}% reach Booked or beyond.")
        recs.append("The biggest lever is lead nurturing speed. Set up an automated first-response sequence: "
                    "reply within 5 minutes of inquiry with a curated property shortlist. "
                    "Every hour of delay reduces conversion by ~30%.")

    new_deals = hs.get('new_deals_period', 0)
    converted = hs.get('converted_period', 0)
    if new_deals > 0:
        period_conv = converted / new_deals * 100
        insights.append(f"📊  Period conversion: {new_deals} new deals → {converted} booked ({period_conv:.1f}%)")

    # ── Version performance
    version_pages = ga4.get('version_pages', {})
    contacts_by_v = hs.get('contacts_by_version', {})
    if version_pages:
        insights.append("\n── Version A/B Performance ──")
        for vk, vdata in sorted(version_pages.items(), key=lambda x: -x[1]['sessions']):
            label = AB_VERSIONS.get(vk, vk)
            contacts = contacts_by_v.get(vk, 0)
            conv = contacts / vdata['sessions'] * 100 if vdata['sessions'] > 0 else 0
            insights.append(
                f"  {label}: {vdata['sessions']} sessions | "
                f"bounce={vdata['bounce_rate']*100:.1f}% | "
                f"avg={vdata['avg_duration']:.0f}s | "
                f"{contacts} leads ({conv:.2f}% conv)"
            )
        if len(version_pages) >= 2:
            best = max(version_pages.items(), key=lambda x: contacts_by_v.get(x[0], 0) / max(x[1]['sessions'], 1))
            recs.append(f"Winning version so far: {AB_VERSIONS.get(best[0], best[0])}. "
                        f"Allocate more traffic here while iterating on the others.")

    return insights, recs


# ── Report output ─────────────────────────────────────────────────────────────

def print_report(ga4, hs, insights, recs, days):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"\n{'='*70}")
    print(f"  THE GOOD LIFE BAHAMAS — CRO ANALYTICS REPORT")
    print(f"  Period: last {days} days  |  Generated: {now}")
    print(f"{'='*70}\n")

    # Traffic overview
    total_sessions = sum(d['sessions'] for d in ga4.get('by_device', []))
    print(f"TRAFFIC OVERVIEW")
    print(f"  Total sessions: {total_sessions:,}")
    for d in sorted(ga4.get('by_device', []), key=lambda x: -x['sessions']):
        pct = d['sessions'] / total_sessions * 100 if total_sessions else 0
        print(f"  {d['device']:<10} {d['sessions']:>7,} ({pct:.0f}%)  "
              f"bounce={d['bounce_rate']*100:.1f}%  avg={d['avg_duration']:.0f}s")

    print(f"\nTRAFFIC SOURCES")
    for c in sorted(ga4.get('by_channel', []), key=lambda x: -x['sessions'])[:6]:
        conv_r = c['conversions'] / c['sessions'] * 100 if c['sessions'] else 0
        print(f"  {c['channel']:<25} {c['sessions']:>7,} sessions  "
              f"conv={conv_r:.2f}%  bounce={c['bounce_rate']*100:.1f}%")

    print(f"\nFORM FUNNEL")
    events = ga4.get('events', {})
    for ev in ['session_start', 'lead_magnet_popup_impressions', 'form_start',
               'booknow_button_click_event', 'booking_form_button_click_event',
               'form_submit', 'inquire_form_submit']:
        d = events.get(ev, {})
        if d:
            print(f"  {ev:<45} {d.get('count',0):>8,}")

    print(f"\nHUBSPOT PIPELINE")
    funnel = hs.get('funnel_summary', {})
    print(f"  Total deals in pipeline:  {funnel.get('total_deals',0):,}")
    print(f"  New deals this period:    {hs.get('new_deals_period',0)}")
    print(f"  Converted this period:    {hs.get('converted_period',0)}")
    print(f"  Close Lost (all time):    {funnel.get('close_lost',0):,}  ({funnel.get('close_lost_pct',0)}%)")
    print(f"  Booked or beyond:         {funnel.get('booked_or_beyond',0):,}  ({funnel.get('booked_pct',0)}%)")

    print(f"\nPIPELINE STAGE BREAKDOWN (current)")
    for sid, info in sorted(hs.get('pipeline_stages', {}).items(), key=lambda x: x[1]['order']):
        bar = '█' * min(info['count'] // 5, 40)
        print(f"  [{info['order']:02d}] {info['label']:<30} {info['count']:>5}  {bar}")

    print(f"\nINSIGHTS & FINDINGS")
    for i in insights:
        print(f"  {i}")

    print(f"\nRECOMMENDATIONS (priority order)")
    for n, r in enumerate(recs, 1):
        print(f"\n  [{n}] {r}")

    print(f"\n{'='*70}\n")


def save_html_report(ga4, hs, insights, recs, days, output_path):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    total_sessions = sum(d['sessions'] for d in ga4.get('by_device', []))
    funnel = hs.get('funnel_summary', {})
    events = ga4.get('events', {})

    # Version rows
    version_pages = ga4.get('version_pages', {})
    contacts_by_v = hs.get('contacts_by_version', {})
    version_rows = ''
    for vk, vdata in sorted(version_pages.items(), key=lambda x: -x[1]['sessions']):
        label = AB_VERSIONS.get(vk, vk)
        contacts = contacts_by_v.get(vk, 0)
        conv = contacts / vdata['sessions'] * 100 if vdata['sessions'] > 0 else 0
        version_rows += f"""
        <tr>
          <td><strong>{label}</strong></td>
          <td>{vdata['sessions']:,}</td>
          <td>{vdata['bounce_rate']*100:.1f}%</td>
          <td>{vdata['avg_duration']:.0f}s</td>
          <td>{contacts}</td>
          <td><strong>{conv:.2f}%</strong></td>
        </tr>"""

    insight_html = ''.join(f'<li>{i}</li>' for i in insights if i.strip())
    rec_html = ''.join(f'<li class="rec">{r}</li>' for r in recs)

    stage_bars = ''
    for sid, info in sorted(hs.get('pipeline_stages', {}).items(), key=lambda x: x[1]['order']):
        pct = info['count'] / max(funnel.get('total_deals', 1), 1) * 100
        color = '#e74c3c' if 'Lost' in info['label'] else ('#27ae60' if info['closed'] else '#3498db')
        stage_bars += f"""
        <div class="stage-row">
          <div class="stage-label">{info['label']}</div>
          <div class="stage-bar-wrap">
            <div class="stage-bar" style="width:{min(pct*3,100):.1f}%;background:{color}"></div>
          </div>
          <div class="stage-count">{info['count']:,}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CRO Report — Good Life Bahamas — {now}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f4f6f9; color: #1a1a2e; line-height: 1.5; }}
  .header {{ background: linear-gradient(135deg,#1a1a2e,#16213e);
             color: white; padding: 32px 40px; }}
  .header h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .header .sub {{ opacity: 0.7; font-size: 0.9rem; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .kpi {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
  .kpi .val {{ font-size: 2rem; font-weight: 800; color: #1a1a2e; }}
  .kpi .lbl {{ font-size: 0.78rem; color: #888; text-transform: uppercase; letter-spacing: .06em; margin-top: 4px; }}
  .kpi.red .val {{ color: #e74c3c; }}
  .kpi.green .val {{ color: #27ae60; }}
  .section {{ background: white; border-radius: 10px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.06); margin-bottom: 24px; }}
  .section h2 {{ font-size: 1rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em;
                 color: #888; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #eee; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th {{ text-align: left; padding: 8px 12px; background: #f8f9fa; font-weight: 700;
        font-size: 0.75rem; text-transform: uppercase; letter-spacing: .05em; color: #666; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }}
  tr:last-child td {{ border-bottom: none; }}
  .stage-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; font-size: 0.85rem; }}
  .stage-label {{ width: 180px; flex-shrink: 0; color: #444; }}
  .stage-bar-wrap {{ flex: 1; background: #f0f0f0; border-radius: 4px; height: 16px; overflow: hidden; }}
  .stage-bar {{ height: 100%; border-radius: 4px; transition: width .3s; }}
  .stage-count {{ width: 50px; text-align: right; font-weight: 700; color: #1a1a2e; }}
  ul.insights {{ padding-left: 20px; }}
  ul.insights li {{ margin-bottom: 10px; font-size: 0.9rem; line-height: 1.5; }}
  li.rec {{ margin-bottom: 16px; padding: 12px 16px; background: #fff8e1; border-left: 4px solid #f39c12;
             border-radius: 0 8px 8px 0; list-style: none; font-size: 0.9rem; }}
  .timestamp {{ font-size: 0.78rem; color: #aaa; text-align: right; margin-top: 32px; }}
</style>
</head>
<body>
<div class="header">
  <h1>The Good Life Bahamas — CRO Analytics Report</h1>
  <div class="sub">Last {days} days &nbsp;|&nbsp; Generated {now}</div>
</div>
<div class="container">

  <div class="grid">
    <div class="kpi"><div class="val">{total_sessions:,}</div><div class="lbl">Total Sessions</div></div>
    <div class="kpi"><div class="val">{events.get('form_start',{}).get('count',0):,}</div><div class="lbl">Form Starts</div></div>
    <div class="kpi"><div class="val">{events.get('inquire_form_submit',{}).get('count',0) + events.get('form_submit',{}).get('count',0):,}</div><div class="lbl">Form Submits</div></div>
    <div class="kpi green"><div class="val">{funnel.get('booked_or_beyond',0):,}</div><div class="lbl">Booked or Beyond</div></div>
    <div class="kpi red"><div class="val">{funnel.get('close_lost_pct',0)}%</div><div class="lbl">Close Lost Rate</div></div>
    <div class="kpi"><div class="val">{hs.get('new_deals_period',0)}</div><div class="lbl">New Deals (Period)</div></div>
  </div>

  <div class="section">
    <h2>A/B Version Performance</h2>
    <table>
      <tr><th>Version</th><th>Sessions</th><th>Bounce</th><th>Avg Duration</th><th>Leads (HubSpot)</th><th>Conv Rate</th></tr>
      {version_rows if version_rows else '<tr><td colspan="6" style="color:#aaa">No version traffic yet — pages not yet live or being tested</td></tr>'}
    </table>
  </div>

  <div class="section">
    <h2>Pipeline Funnel (Vacation Rentals)</h2>
    {stage_bars}
  </div>

  <div class="section">
    <h2>Traffic by Source</h2>
    <table>
      <tr><th>Channel</th><th>Sessions</th><th>Conversions</th><th>Conv Rate</th><th>Bounce</th></tr>
      {''.join(
        f'<tr><td>{c["channel"]}</td><td>{c["sessions"]:,}</td>'
        f'<td>{c["conversions"]}</td>'
        f'<td>{"%.2f" % (c["conversions"]/c["sessions"]*100 if c["sessions"] else 0)}%</td>'
        f'<td>{c["bounce_rate"]*100:.1f}%</td></tr>'
        for c in sorted(ga4.get("by_channel",[]), key=lambda x: -x["sessions"])
      )}
    </table>
  </div>

  <div class="section">
    <h2>Insights</h2>
    <ul class="insights">{insight_html}</ul>
  </div>

  <div class="section">
    <h2>Recommendations (Priority Order)</h2>
    <ol style="padding-left:0;list-style:none">{rec_html}</ol>
  </div>

  <div class="timestamp">Report generated at {now} by Good Life CRO Analytics</div>
</div>
</body>
</html>"""

    Path(output_path).write_text(html)
    print(f"HTML report saved to: {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Good Life CRO Analytics Report')
    parser.add_argument('--days', type=int, default=7, help='Number of days to analyse (default: 7)')
    parser.add_argument('--output', type=str, default='', help='Save HTML report to this path')
    args = parser.parse_args()

    print(f"Pulling GA4 data (last {args.days} days)...")
    ga4 = pull_ga4_data(days=args.days)

    print("Pulling HubSpot pipeline data...")
    hs = pull_hubspot_data(days=args.days)

    print("Pulling Clarity behavioural data...")
    clarity = pull_clarity_data(days=args.days)
    if clarity.get('available'):
        print(f"  ✓ Clarity: {clarity['overall'].get('sessions', 0):,} sessions | "
              f"rage={clarity['overall'].get('rage_click_pct', 0)}% | "
              f"dead={clarity['overall'].get('dead_click_pct', 0)}% | "
              f"scroll depth={clarity['overall'].get('avg_scroll_depth', 0)}%")
    else:
        print(f"  ⚠  Clarity: {clarity.get('reason', 'not available')}")

    print("Generating insights...")
    insights, recs = generate_insights(ga4, hs)
    c_insights, c_recs = clarity_insights(clarity)
    insights += c_insights
    recs     += c_recs

    print_report(ga4, hs, insights, recs, days=args.days)

    if args.output:
        save_html_report(ga4, hs, insights, recs, days=args.days, output_path=args.output)
    else:
        # Auto-save to cro-analytics/reports/
        reports_dir = Path(__file__).parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        fname = reports_dir / f"cro_report_{datetime.now().strftime('%Y%m%d')}.html"
        save_html_report(ga4, hs, insights, recs, days=args.days, output_path=str(fname))


if __name__ == '__main__':
    main()
