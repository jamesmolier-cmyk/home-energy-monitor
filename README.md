# Home Energy Monitor

Daily electricity and heat pump monitoring for **Octopus Energy (Cosy)** + **Aira heat pump**.

## macOS setup (your machine)

```bash
# Install uv (Python manager) if needed
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

cd ~/home-energy-monitor
uv venv venv --python 3.12
source venv/bin/activate
uv pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials
python scripts/daily_report.py
```

## Linux / Raspberry Pi setup

```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv git -y
git clone https://github.com/jamesmolier-cmyk/home-energy-monitor.git
cd home-energy-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials
python scripts/daily_report.py
```

## Environment variables

| Variable | Source |
|----------|--------|
| `OCTOPUS_API_KEY` | Octopus developer settings |
| `OCTOPUS_ACCOUNT` | Your bill / dashboard |
| `OCTOPUS_MPAN` | Electricity meter point |
| `OCTOPUS_METER_SERIAL` | Meter serial number |
| `OCTOPUS_TARIFF_CODE` | Cosy tariff code |
| `OCTOPUS_PRODUCT_CODE` | Cosy product code |
| `AIRA_EMAIL` | Aira Home app login |
| `AIRA_PASSWORD` | Aira Home app password |

## Daily automation

**cron (Linux):**
```cron
0 7 * * * cd /home/pi/home-energy-monitor && ./venv/bin/python scripts/daily_report.py >> reports/cron.log 2>&1
```

**Grok (macOS):**
```
/loop 1d cd ~/home-energy-monitor && ./venv/bin/python scripts/daily_report.py
```

## Outputs

- Console report with Cosy band breakdown + heat pump COP
- JSON snapshot in `reports/YYYY-MM-DD.json`