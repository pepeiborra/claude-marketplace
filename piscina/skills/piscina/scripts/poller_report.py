#!/usr/bin/env python3
"""Daily report from the poller JSONL files on the Pi (/home/pi/poolfast/fast-YYYYMMDD.jsonl, 14 days retained):
pump hours by speed (relay_raw bits), chlorine produced (g), cell producing hours, no-flow minutes with the pump on,
peak-tariff hours and estimated kWh. Usage: poller_report.py [days=15]
Speed decode: (relay_raw >> 8) & 7 -> 1 baja (1500 rpm, 110 W), 3 media (2720 rpm, 470 W), 7 alta (3000 rpm, 626 W); +130 W cell.
Pump relay = bit 1 of relay_raw; acid relay = bit 0. 'Starts' from these files are inflated by sample glitches: use the recorder.
"""
import sys, subprocess, shlex
days = sys.argv[1] if len(sys.argv) > 1 else "15"
REMOTE = r'''
import json, glob, collections, datetime, sys
days=int(sys.argv[1]); P={1:0.240,3:0.600,7:0.756}
files=sorted(glob.glob("/home/pi/poolfast/fast-2026*.jsonl"))[-days:]
print("día        baja  media  alta  total  punta  kWh_est  cloro_g  h_cel  noflow_min")
for f in files:
    day=f[-14:-6]; hrs=collections.Counter(); punta=0.0; kwh=0.0; g=0.0; hcel=0.0; noflow=0.0; prev=None
    for line in open(f):
        try: d=json.loads(line)
        except: continue
        r=d.get("relay_raw"); ts=datetime.datetime.fromisoformat(d["ts"])
        on=bool((r or 0)&2); sp=((r or 0)>>8)&7; gh=d.get("gh") or 0; fl=d.get("status",{}).get("FL1")
        if prev and 0<(ts-prev[0]).total_seconds()<60:
            dt=(ts-prev[0]).total_seconds()/3600
            if prev[1]:
                hrs[prev[2]]+=dt; kwh+=P.get(prev[2],0.6)*dt
                if 10<=prev[0].hour<14 or 18<=prev[0].hour<22: punta+=dt
                if prev[4] is False: noflow+=dt*60
            if prev[3]>0: g+=prev[3]*dt; hcel+=dt
        prev=(ts,on,sp,gh,fl)
    tot=sum(hrs.values())
    print(f"{day}  {hrs[1]:5.1f} {hrs[3]:6.1f} {hrs[7]:5.1f} {tot:6.1f} {punta:6.1f}  {kwh:6.2f}  {g:7.0f}  {hcel:5.1f}  {noflow:6.0f}")
'''
cmd = f"python3 -c {shlex.quote(REMOTE)} {shlex.quote(days)}"
sys.exit(subprocess.call(["ssh", "pi", cmd]))
