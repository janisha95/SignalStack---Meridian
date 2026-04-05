# SignalStack — Website Deployment & Maintenance Guide

## Architecture Overview

```
┌──────────────────┐     ┌──────────────────┐
│  S1 Dashboard    │     │  Meridian v2 UI   │
│  trading_dash    │     │  signalstack-app  │
│  (HTML file)     │     │  (Next.js React)  │
└────────┬─────────┘     └────────┬──────────┘
         │                        │
         │ ngrok tunnel           │ Vercel hosting
         │                        │
┌────────▼─────────┐     ┌────────▼──────────┐
│  S1 API Server   │     │  Meridian API     │
│  agent_server.py │     │  v2_api_server.py │
│  port 8000       │     │  port 8080        │
│  (local Mac)     │     │  (local Mac)      │
└──────────────────┘     └──────────────────┘
```

---

## S1 Dashboard

### How It Works
- Single HTML file: `~/SS/Advance/trading_dashboard.html`
- Connects to agent_server.py on port 8000
- Accessible via ngrok tunnel for mobile access

### Start S1
```bash
cd ~/SS/Advance
python3 agent_server.py &
# Wait for "Server started on port 8000"
```

### ngrok Tunnel for Mobile Access
```bash
ngrok http 8000
# URL: https://unsublimated-casey-unsurfaced.ngrok-free.dev
```

### If S1 Goes Down
```bash
# Kill and restart
kill $(lsof -ti:8000) 2>/dev/null
sleep 2
cd ~/SS/Advance
python3 agent_server.py &

# Restart ngrok if needed
killall ngrok
ngrok http 8000
```

---

## Meridian v2 Dashboard

### How It Works
- React app (Next.js): `~/SS/Meridian/ui/signalstack-app/`
- Hosted on Vercel: https://signalstack-app.vercel.app
- Connects to v2_api_server.py on port 8080
- Vercel needs API URL to show real data (ngrok or deployed backend)

### Start Meridian Locally
```bash
# Terminal 1: API server
cd ~/SS/Meridian
source .env  # loads ALPACA_KEY and ALPACA_SECRET
python3 stages/v2_api_server.py &

# Terminal 2: React dev server
cd ~/SS/Meridian/ui/signalstack-app
npm run dev
# Dashboard at http://localhost:3000
```

### Deploy UI Changes to Vercel
After making changes with Cursor or any editor:
```bash
cd ~/SS/Meridian/ui/signalstack-app
npx vercel --prod
```

### Connect Vercel to Local API (requires ngrok)
1. Start API: `python3 stages/v2_api_server.py`
2. Start tunnel: `ngrok http 8080`
3. Copy ngrok URL
4. Go to: https://vercel.com/janishantanu-9107s-projects/signalstack-app/settings/environment-variables
5. Set: `NEXT_PUBLIC_API_URL` = your ngrok URL
6. Redeploy: `npx vercel --prod`

### IMPORTANT: ngrok Free Plan Limitation
- Free plan = 1 tunnel at a time
- Can't run S1 (8000) and Meridian (8080) simultaneously
- Options:
  - Upgrade ngrok to Basic ($8/month) for 2 tunnels
  - Deploy Meridian API to Railway/Render
  - Use Meridian locally only (localhost:3000)

---

## Daily Maintenance

### Morning Checklist
```bash
# Check S1 is running
curl -s http://localhost:8000/health || echo "S1 DOWN - restart it"

# Check Meridian API
curl -s http://localhost:8080/health || echo "Meridian DOWN - restart it"

# Check ngrok
curl -s https://unsublimated-casey-unsurfaced.ngrok-free.dev/health || echo "ngrok DOWN"

# Check backfill progress
tail -1 ~/SS/Meridian/data/backfill_extended2.log
```

### Evening: Run Meridian Orchestrator
```bash
cd ~/SS/Meridian
python3 stages/v2_orchestrator.py 2>&1 | tee data/orchestrator_run.log
```

### After UI Changes: Deploy to Vercel
```bash
cd ~/SS/Meridian/ui/signalstack-app
npx vercel --prod
```

---

## Troubleshooting

### "API Offline" on Vercel
- Cause: ngrok tunnel not running or NEXT_PUBLIC_API_URL not set
- Fix: Start ngrok, update Vercel env var, redeploy

### "SPY stale" Error
- Cause: Running orchestrator before 4pm ET or after midnight
- Fix: Cache warm now uses _get_last_trading_day() — should auto-resolve

### ngrok "endpoint already online" Error
```bash
killall ngrok
sleep 2
ngrok http PORT_NUMBER
```

### Port Already in Use
```bash
# Kill process on specific port
kill $(lsof -ti:8000) 2>/dev/null  # S1
kill $(lsof -ti:8080) 2>/dev/null  # Meridian
kill $(lsof -ti:3000) 2>/dev/null  # React dev
```

### Vercel Build Fails
```bash
cd ~/SS/Meridian/ui/signalstack-app
npm run build  # Check for errors locally first
npx vercel --prod  # Then deploy
```

---

## URLs & Accounts

| Service | URL | Notes |
|---|---|---|
| S1 Local | http://localhost:8000 | agent_server.py |
| S1 Mobile | https://unsublimated-casey-unsurfaced.ngrok-free.dev | ngrok tunnel |
| Meridian Local | http://localhost:3000 | React dev server |
| Meridian API | http://localhost:8080 | v2_api_server.py |
| Meridian Vercel | https://signalstack-app.vercel.app | Production |
| Vercel Settings | https://vercel.com/janishantanu-9107s-projects/signalstack-app/settings | Env vars here |
| Colab Pro | https://colab.research.google.com | CA$13.99/month |
| ngrok Dashboard | http://127.0.0.1:4040 | Local tunnel inspector |

---

## Environment Variables

### Meridian (.env)
```
ALPACA_KEY=xxx
ALPACA_SECRET=xxx
```

### Vercel (set in project settings)
```
NEXT_PUBLIC_API_URL=https://your-ngrok-url.ngrok-free.dev
```
