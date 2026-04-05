# FULL AUTOMATION: S1 + Meridian Pipeline Scheduling

## Overview
Both S1 and Meridian need to run end-to-end automatically every trading day.
Mac should wake at scheduled times, run pipelines, then sleep.
No 24/7 running required.

## Daily Schedule (all times ET)

```
04:45 PM — Mac wakes (pmset)
05:00 PM — Meridian orchestrator runs
             Stage 1: Cache warm (Alpaca IEX download)
             Stage 2: Prefilter
             Stage 3: Factor engine
             Stage 4B: TCN scorer
             Stage 5: Selection
             Stage 6: Risk filters
             Stage 5T: Forward tracker snapshot
             → Writes shortlist_daily, pick_tracking
             → API server starts (port 8080)
             → Cloudflare tunnel starts

05:15 PM — S1 FUC cache update
             → Downloads OHLCV for S1 universe

05:30 PM — S1 Evening scan
             → Router → Strategies → ML Gate → ML Scorer
             → Convergence pipeline (JSON output)
             → Forward tracker --capture
             → Telegram evening summary

06:30 AM — Mac wakes (pmset)
06:30 AM — S1 Morning report v2
             → Reads S1 DB + Meridian DB
             → Applies validated thresholds
             → Haiku news check per pick
             → Telegram morning report (4 tables)
             → JSON saved for dashboard

07:00 AM — Meridian API server starts
             → Cloudflare tunnel starts
             → Dashboard available at signalstack-app.vercel.app

11:00 PM — Mac sleeps (pmset)
```

## Step 1: macOS Scheduled Wake/Sleep

```bash
# Schedule Mac to wake at 4:45 PM ET daily (for evening pipelines)
sudo pmset repeat wakeorpoweron MTWRF 16:45:00

# Schedule Mac to wake at 6:15 AM ET daily (for morning report)  
# Note: pmset only supports one repeat event, so we use TWO approaches:
# Option A: Use a single wake at 6:15 AM and let the Mac stay awake until 11 PM
# Option B: Use a caffeinate + sleep approach

# Option A (simpler):
sudo pmset repeat wakeorpoweron MTWRF 06:15:00

# Then use a launchd job at 6:15 AM that also triggers the 5 PM pipeline
# via a "wait until 5 PM" approach — OR just let the Mac stay awake all day

# Option B (power efficient):
# Wake at 6:15 AM, run morning report, sleep at 7:30 AM
# Wake at 4:45 PM, run evening pipelines, sleep at 11 PM
# This requires TWO wake events — pmset repeat only supports one
# Solution: Use a secondary launchd job that calls pmset schedule

# RECOMMENDED: Just wake at 6:15 AM and stay awake until 11 PM
sudo pmset repeat wakeorpoweron MTWRF 06:15:00
sudo pmset repeat sleep MTWRF 23:00:00
```

## Step 2: LaunchAgent Plists

### Meridian Evening Pipeline (5:00 PM ET)
File: ~/Library/LaunchAgents/com.signalstack.meridian.evening.plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.signalstack.meridian.evening</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/sjani008/SS/Meridian/stages/v2_orchestrator.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/sjani008/SS/Meridian</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>17</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/sjani008/SS/Meridian/logs/meridian_evening.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/sjani008/SS/Meridian/logs/meridian_evening_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
        <key>PYTHONPATH</key>
        <string>/Users/sjani008/SS/Meridian</string>
    </dict>
</dict>
</plist>
```

### Meridian API Server (starts at 6:30 AM, stays running)
File: ~/Library/LaunchAgents/com.signalstack.meridian.api.plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.signalstack.meridian.api</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/sjani008/SS/Meridian/stages/v2_api_server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/sjani008/SS/Meridian</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>6</integer>
        <key>Minute</key><integer>30</integer>
    </dict>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/Users/sjani008/SS/Meridian/logs/api_server.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/sjani008/SS/Meridian/logs/api_server_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
        <key>PYTHONPATH</key>
        <string>/Users/sjani008/SS/Meridian</string>
    </dict>
</dict>
</plist>
```

### S1 Evening Pipeline (5:15 PM ET — after Meridian cache warm)
File: ~/Library/LaunchAgents/com.signalstack.s1.evening.plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.signalstack.s1.evening</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/sjani008/SS/Advance/s1_orchestrator_v2.py</string>
        <string>--stage</string>
        <string>evening</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/sjani008/SS/Advance</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>17</integer>
        <key>Minute</key><integer>15</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/sjani008/SS/Advance/logs/s1_evening.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/sjani008/SS/Advance/logs/s1_evening_err.log</string>
</dict>
</plist>
```

### S1 Morning Report (6:30 AM ET)
File: ~/Library/LaunchAgents/com.signalstack.s1.morning.plist
(Already created by Claude Code — just load it)

### Cloudflare Tunnel (starts with API server)
File: ~/Library/LaunchAgents/com.signalstack.cloudflare.plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.signalstack.cloudflare</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/cloudflared</string>
        <string>tunnel</string>
        <string>run</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>6</integer>
        <key>Minute</key><integer>30</integer>
    </dict>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/Users/sjani008/SS/logs/cloudflare.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/sjani008/SS/logs/cloudflare_err.log</string>
</dict>
</plist>
```

## Step 3: Master Boot Script

Instead of managing 5 plists, create ONE master script that starts everything:

File: ~/SS/boot_signalstack.sh

```bash
#!/bin/bash
# SignalStack Master Boot — starts all services
# Called by a single launchd plist at 6:30 AM

echo "$(date) — SignalStack booting..."

# Create log dirs
mkdir -p ~/SS/Meridian/logs ~/SS/Advance/logs ~/SS/logs

# Start Meridian API server (if not already running)
if ! lsof -ti:8080 > /dev/null 2>&1; then
    echo "Starting Meridian API server..."
    cd ~/SS/Meridian
    nohup python3 stages/v2_api_server.py >> logs/api_server.log 2>&1 &
    echo "  PID: $!"
fi

# Start Cloudflare tunnel (if not already running)
if ! pgrep -f "cloudflared tunnel" > /dev/null 2>&1; then
    echo "Starting Cloudflare tunnel..."
    nohup cloudflared tunnel run >> ~/SS/logs/cloudflare.log 2>&1 &
    echo "  PID: $!"
fi

# Start S1 API server (if applicable)
if ! lsof -ti:5005 > /dev/null 2>&1; then
    echo "Starting S1 API server..."
    cd ~/SS/Advance
    nohup python3 agent_server.py >> logs/s1_server.log 2>&1 &
    echo "  PID: $!"
fi

echo "$(date) — SignalStack boot complete"
```

## Step 4: Activation Commands

Run these ONCE to set everything up:

```bash
# Create log directories
mkdir -p ~/SS/Meridian/logs ~/SS/Advance/logs ~/SS/logs

# Make boot script executable
chmod +x ~/SS/boot_signalstack.sh

# Copy plists (Claude Code should create these)
# Then load them:
launchctl load ~/Library/LaunchAgents/com.signalstack.meridian.evening.plist
launchctl load ~/Library/LaunchAgents/com.signalstack.s1.evening.plist
launchctl load ~/Library/LaunchAgents/com.signalstack.s1.morning.plist

# Schedule Mac wake/sleep
sudo pmset repeat wakeorpoweron MTWRF 06:15:00
sudo pmset repeat sleep MTWRF 23:00:00

# Verify
launchctl list | grep signalstack
pmset -g sched
```

## Step 5: Health Check Script

File: ~/SS/health_check.sh

```bash
#!/bin/bash
# Quick health check for all SignalStack services

echo "=== SignalStack Health Check ==="
echo "Time: $(date)"

# Meridian API
if curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "✅ Meridian API: RUNNING (port 8080)"
else
    echo "❌ Meridian API: DOWN"
fi

# S1 API
if curl -s http://localhost:5005/health > /dev/null 2>&1; then
    echo "✅ S1 API: RUNNING (port 5005)"
else
    echo "❌ S1 API: DOWN"
fi

# Cloudflare tunnel
if pgrep -f "cloudflared tunnel" > /dev/null 2>&1; then
    echo "✅ Cloudflare tunnel: RUNNING"
else
    echo "❌ Cloudflare tunnel: DOWN"
fi

# Latest Meridian run
python3 -c "
import sqlite3
con = sqlite3.connect('/Users/sjani008/SS/Meridian/data/v2_universe.db')
d = con.execute('SELECT MAX(date) FROM shortlist_daily').fetchone()[0]
print(f'📊 Meridian latest shortlist: {d}')
con.close()
" 2>/dev/null

# Latest S1 run  
python3 -c "
import sqlite3
con = sqlite3.connect('/Users/sjani008/SS/Advance/signalstack_metrics.db')
d = con.execute('SELECT MAX(date) FROM gate_decisions').fetchone()[0]
print(f'📊 S1 latest gate decisions: {d}')
con.close()
" 2>/dev/null

echo "=== Done ==="
```

## Futures & Options Expansion (Phase 2)

Adding new instrument classes requires:
1. Data source: Alpaca supports crypto. For futures/forex, need a different 
   data provider (Interactive Brokers API, or Polygon.io for historical)
2. Factor calibration: TBM thresholds change per instrument
   - Stocks: +2%/-1% (5-day)
   - Indices: +0.5%/-0.25% (5-day) — less volatile
   - Forex: +1%/-0.5% (5-day) — depends on pair
   - Crypto: +3%/-1.5% (5-day) — more volatile
3. Model retraining: TCN needs instrument-specific training data
4. Universe: Goes from 8K stocks to ~50 instruments (much faster)

Timeline: After intraday system is built and TTP eval is running.
