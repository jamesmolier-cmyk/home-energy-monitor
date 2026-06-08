#!/usr/bin/env python3
"""Fetch Octopus + Aira data and print a daily home energy report."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TOKEN_PATH = ROOT / ".aira_tokens.json"


def require(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise SystemExit(f"Missing {name} in .env")
    return value


def classify_rate(p_inc_vat: float) -> str:
    if p_inc_vat < 20:
        return "off_peak"
    if p_inc_vat > 40:
        return "peak"
    return "standard"


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fetch_octopus() -> dict:
    api_key = require("OCTOPUS_API_KEY")
    account = require("OCTOPUS_ACCOUNT")
    mpan = require("OCTOPUS_MPAN")
    serial = require("OCTOPUS_METER_SERIAL")
    product = require("OCTOPUS_PRODUCT_CODE")
    tariff = require("OCTOPUS_TARIFF_CODE")
    base = "https://api.octopus.energy/v1"
    auth = HTTPBasicAuth(api_key, "")

    now = datetime.now(timezone.utc)
    period_to = now.isoformat().replace("+00:00", "Z")
    period_from_7d = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")

    def get(path: str, params: dict | None = None) -> dict:
        r = requests.get(f"{base}{path}", auth=auth, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # Local midnight boundaries (Europe/London) for half-hourly band analysis
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/London")
    today_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    hh_from = (today_local - timedelta(days=3)).isoformat()
    hh_to = today_local.isoformat()

    consumption = f"/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    rates_path = f"/products/{product}/electricity-tariffs/{tariff}/standard-unit-rates/"

    return {
        "account": get(f"/accounts/{account}/"),
        "daily_7d": get(consumption, {
            "period_from": period_from_7d,
            "period_to": period_to,
            "group_by": "day",
            "page_size": 100,
            "order_by": "period",
        }),
        "halfhourly": get(consumption, {
            "period_from": hh_from,
            "period_to": hh_to,
            "page_size": 100,
            "order_by": "period",
        }),
        "rates": get(rates_path, {
            "period_from": (now - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00Z"),
            "period_to": period_to,
            "page_size": 100,
        }),
    }


def analyse_octopus(data: dict) -> dict:
    rate_periods = []
    for r in data["rates"]["results"]:
        rate_periods.append({
            "from": parse_ts(r["valid_from"]),
            "to": parse_ts(r["valid_to"]) if r.get("valid_to") else datetime.max.replace(tzinfo=timezone.utc),
            "band": classify_rate(r["value_inc_vat"]),
            "p_kwh": r["value_inc_vat"] / 100,
        })

    def rate_at(dt: datetime):
        for rp in rate_periods:
            if rp["from"] <= dt < rp["to"]:
                return rp
        return None

    by_day: dict[str, list] = defaultdict(list)
    for item in data["halfhourly"]["results"]:
        day = item["interval_start"][:10]
        rp = rate_at(parse_ts(item["interval_start"]))
        if rp:
            by_day[day].append((item["consumption"], rp["band"], rp["p_kwh"]))

    analysis_day = next((d for d in sorted(by_day, reverse=True) if len(by_day[d]) >= 46), None)
    if not analysis_day and by_day:
        analysis_day = max(by_day, key=lambda d: len(by_day[d]))

    band_kwh: dict[str, float] = defaultdict(float)
    band_cost: dict[str, float] = defaultdict(float)
    for kwh, band, price in by_day.get(analysis_day, []):
        band_kwh[band] += kwh
        band_cost[band] += kwh * price

    daily_rows = [
        {"date": r["interval_start"][:10], "kwh": r["consumption"]}
        for r in data["daily_7d"]["results"]
    ]
    df = pd.DataFrame(daily_rows)
    complete = df.iloc[:-1] if len(df) > 1 else df
    avg_kwh = complete["kwh"].mean() if not complete.empty else 0

    total = sum(band_kwh.values())
    return {
        "analysis_day": analysis_day,
        "total_kwh": round(total, 2),
        "usage_cost_gbp": round(sum(band_cost.values()), 2),
        "off_peak_pct": round(band_kwh["off_peak"] / total * 100, 1) if total else 0,
        "bands": {k: round(v, 2) for k, v in band_kwh.items()},
        "band_costs": {k: round(v, 2) for k, v in band_cost.items()},
        "daily_7d": daily_rows,
        "avg_daily_kwh": round(avg_kwh, 2),
    }


def fetch_aira() -> dict:
    email = os.getenv("AIRA_EMAIL", "")
    password = os.getenv("AIRA_PASSWORD", "")
    if not email or not password:
        return {"available": False, "error": "AIRA_EMAIL / AIRA_PASSWORD not set"}

    try:
        from pyairahome import AiraHome
        from pyairahome.enums import Granularity
    except ImportError as exc:
        return {"available": False, "error": str(exc)}

    aira = AiraHome()
    if TOKEN_PATH.exists():
        tokens = json.loads(TOKEN_PATH.read_text())
        aira.cloud.login_with_tokens(tokens["id_token"], tokens["access_token"], tokens["refresh_token"])
    else:
        aira.cloud.login_with_credentials(email, password)
        tokens = aira.cloud.get_tokens().dict()
        TOKEN_PATH.write_text(json.dumps(tokens, indent=2))
        TOKEN_PATH.chmod(0o600)

    devices = aira.cloud.get_devices()
    if not devices.get("devices"):
        return {"available": False, "error": "No Aira devices found"}

    device_id = devices["devices"][0]["id"]["value"]
    states = aira.cloud.get_states(device_id)
    state = (states.get("heat_pump_states") or [{}])[0]

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    insights = aira.cloud.get_insights(
        device_id, Granularity.GRANULARITY_DAILY, start_time=start, end_time=end
    )

    daily = []
    for item in insights.get("insights", []):
        st = item.get("start_time", {})
        energy_wh = float(item.get("energy_consumption_wh") or 0)
        heat_wh = float(item.get("delivered_heat_wh") or 0)
        daily.append({
            "date": f"{st.get('year')}-{st.get('month'):02d}-{st.get('day'):02d}",
            "energy_kwh": round(energy_wh / 1000, 2),
            "delivered_heat_kwh": round(heat_wh / 1000, 2),
            "cop": round(heat_wh / energy_wh, 2) if energy_wh else None,
        })

    complete = [d for d in daily if d["energy_kwh"] > 0.1]
    analysis = complete[-1] if complete else (daily[-1] if daily else None)

    fresh = aira.cloud.get_tokens().dict()
    TOKEN_PATH.write_text(json.dumps(fresh, indent=2))

    mode = state.get("current_pump_mode_state", {})
    return {
        "available": True,
        "device_id": device_id,
        "analysis_day": analysis,
        "daily_7d": daily,
        "current_state": {
            "outdoor_c": state.get("current_outdoor_temperature"),
            "hot_water_c": state.get("current_hot_water_temperature"),
            "target_hot_water_c": state.get("target_hot_water_temperature"),
            "zone_1": mode.get("zone_1") if isinstance(mode, dict) else mode,
            "inline_heater": state.get("inline_heater_active"),
        },
    }


def print_report(octopus: dict, aira: dict) -> None:
    print(f"\n### Daily Energy Report — {datetime.now().strftime('%Y-%m-%d')}\n")

    print("#### Electricity (Octopus / Cosy)")
    day = octopus["analysis_day"]
    print(f"**{day}:** {octopus['total_kwh']} kWh · ~£{octopus['usage_cost_gbp']} · {octopus['off_peak_pct']}% off-peak")
    print(f"7-day average: {octopus['avg_daily_kwh']} kWh/day\n")

    print("| Band | kWh | Cost |")
    print("|------|-----|------|")
    for band in ("off_peak", "standard", "peak"):
        print(f"| {band} | {octopus['bands'].get(band, 0)} | £{octopus['band_costs'].get(band, 0)} |")

    print("\n| Date | kWh |")
    print("|------|-----|")
    for row in octopus["daily_7d"]:
        print(f"| {row['date']} | {row['kwh']} |")

    print("\n#### Heat Pump (Aira)")
    if not aira.get("available"):
        print(f"Unavailable: {aira.get('error')}")
        return

    ad = aira.get("analysis_day") or {}
    print(f"**{ad.get('date', 'n/a')}:** {ad.get('energy_kwh', 0)} kWh elec · {ad.get('delivered_heat_kwh', 0)} kWh heat · COP {ad.get('cop', 'n/a')}")

    st = aira["current_state"]
    print(f"**Now:** outdoor {st['outdoor_c']}°C · hot water {st['hot_water_c']}°C · {st['zone_1']}")

    octopus_on_day = next((r["kwh"] for r in octopus["daily_7d"] if r["date"] == ad.get("date")), None)
    if octopus_on_day and ad.get("energy_kwh"):
        share = round(ad["energy_kwh"] / octopus_on_day * 100, 1)
        other = round(octopus_on_day - ad["energy_kwh"], 2)
        print(f"**HP share of home meter (same day):** {share}% · other loads ~{other} kWh")


def main() -> int:
    octopus_raw = fetch_octopus()
    octopus = analyse_octopus(octopus_raw)
    aira = fetch_aira()

    report = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "octopus": octopus,
        "aira": aira,
    }

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
    out_file.write_text(json.dumps(report, indent=2, default=str))

    print_report(octopus, aira)
    print(f"\nSaved: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())