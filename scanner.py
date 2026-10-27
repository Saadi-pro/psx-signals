"""PSX day-trading signal scanner. Runs on GitHub Actions every 5 minutes.
Rule-based screening tool, not financial advice. Signals can and will be wrong."""
import argparse, base64, json, math, os, smtplib, sys, time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import numpy as np
import pandas as pd
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from watchlist import KMI, WATCHLIST

PKT = timezone(timedelta(hours=5))
CAPITAL = float(os.getenv("CAPITAL") or 100000)   # set the CAPITAL variable in GitHub
RISK_PCT = float(os.getenv("RISK_PCT") or 2)      # % of capital risked per trade
MAX_POS_PCT = 35         # max % of capital in any one trade
MAX_SIGNALS = 3          # per day
MIN_SCORE = 65           # 0-100 quality bar
GAP_SECONDS = 1800       # at least 30 min between new signals
OUT = "docs/signals.enc.json"
BASE = "https://dps.psx.com.pk"
HDR = {"User-Agent": "Mozilla/5.0 (compatible; psx-signals)"}
ERRORS = []


# ---------- market clock (verify hours with PSX; edit here if they change) ----------
def mins(now): return now.hour * 60 + now.minute
def market_open(now):
    wd, t = now.weekday(), mins(now)
    if wd > 4: return False
    if wd == 4: return 555 <= t <= 720 or 870 <= t <= 990     # Fri 09:15-12:00, 14:30-16:30
    return 572 <= t <= 930                                      # Mon-Thu 09:32-15:30
def signal_window(now):
    wd, t = now.weekday(), mins(now)
    if wd > 4: return False
    if wd == 4: return 570 <= t <= 660 or 885 <= t <= 930
    return 585 <= t <= 855                                      # 09:45-14:15, skips open/close chop


# ---------- data ----------
def get(url, **kw):
    err = None
    for _ in range(3):
        try:
            r = requests.get(url, headers=HDR, timeout=20, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            err = e
            time.sleep(2)
    raise err

def frame(rows, cols):
    df = pd.DataFrame(rows).iloc[:, :3]
    df.columns = cols
    ts = df["ts"].astype("float64")
    df["ts"] = np.where(ts > 1e11, ts / 1000, ts)
    df["day"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(PKT).dt.date
    return df.sort_values("ts").reset_index(drop=True)

def eod(sym): return frame(get(f"{BASE}/timeseries/eod/{sym}").json()["data"], ["ts", "close", "vol"])
def intraday(sym): return frame(get(f"{BASE}/timeseries/int/{sym}").json()["data"], ["ts", "price", "vol"])


# ---------- analysis ----------
def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def analyze(sym, now):
    today = now.date()
    d = eod(sym)
    d = d[d["day"] < today].tail(120)
    if len(d) < 55: return None
    c = d["close"].astype(float).reset_index(drop=True)
    v = d["vol"].astype(float).reset_index(drop=True)
    i = intraday(sym)
    i = i[i["day"] == today]
    if i.empty: return None
    px, hi, lo = float(i["price"].iloc[-1]), float(i["price"].max()), float(i["price"].min())
    day_vol = float(i["vol"].sum())
    vwap = float((i["price"] * i["vol"]).sum() / max(day_vol, 1))
    prev = float(c.iloc[-1])
    chg = (px / prev - 1) * 100
    avgv = float(v.tail(20).mean())
    if avgv < 200_000 or px < 5: return None                      # too illiquid to day trade
    frac = min(max((mins(now) - 572) / 358, 0.1), 1.0)
    pace = day_vol / (avgv * frac)                                # today's volume vs normal for this time
    sma20, sma50 = float(c.tail(20).mean()), float(c.tail(50).mean())
    r = float(rsi(c).iloc[-1])
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    atr = float(c.diff().abs().tail(14).mean() * 1.25)            # close-to-close proxy (no daily highs/lows in feed)
    support, resist = float(min(c.tail(20).min(), lo)), float(max(c.tail(20).max(), hi))

    if chg >= 6 or px < vwap * 0.99: return None                  # chasing the limit / weak intraday

    sc, why = 0, []
    if px > sma20: sc += 10; why.append("Price above 20-day average")
    if sma20 > sma50: sc += 10; why.append("20-day above 50-day average (uptrend)")
    if 45 <= r <= 68: sc += 15; why.append(f"RSI {r:.0f}: momentum with room to run")
    elif r > 75: sc -= 10; why.append(f"RSI {r:.0f}: overbought risk")
    if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]: sc += 12; why.append("MACD momentum rising")
    if pace >= 1.5: sc += 18; why.append(f"Volume {pace:.1f}x normal for this time")
    elif pace >= 1.0: sc += 10; why.append(f"Volume {pace:.1f}x normal for this time")
    if px > vwap: sc += 10; why.append("Trading above today's VWAP")
    if 0.5 <= chg <= 4: sc += 10; why.append(f"Up {chg:.1f}% today, not stretched")
    elif chg < -1: sc -= 10
    if px >= resist * 0.998: sc += 10; why.append("Breaking the 20-day high")
    elif (resist / px - 1) * 100 >= 3: sc += 6; why.append("Room to the next resistance")

    risk = min(max(1.3 * atr, 0.012 * px), 0.035 * px)
    stop, t1, t2 = round(px - risk, 2), round(px + 1.5 * risk, 2), round(min(px + 2.5 * risk, px * 1.07), 2)
    risk_amt = CAPITAL * RISK_PCT / 100
    shares = min(int(risk_amt // max(px - stop, 0.01)), int(CAPITAL * MAX_POS_PCT / 100 // px))
    return dict(symbol=sym, shariah=sym in KMI, price=round(px, 2), change=round(chg, 2), score=sc,
                entry=round(px, 2), stop=stop, t1=t1, t2=t2, shares=shares, cost=round(shares * px),
                risk_amount=round(shares * (px - stop)), support=round(support, 2), resistance=round(resist, 2),
                rsi=round(r, 1), volume_ratio=round(pace, 2), vwap=round(vwap, 2), reasons=why, news=[], news_score=0)

def safe_analyze(args):
    try: return analyze(*args)
    except Exception as e:
        ERRORS.append(f"{args[0]}: {e}")
        return None

POS = ("profit", "surge", "record", "dividend", "growth", "gain", "upgrade", "approval", "bullish", "jump")
NEG = ("loss", "fall", "decline", "default", "probe", "fraud", "downgrade", "strike", "ban", "bearish", "penalty", "plunge")
def news(sym):
    try:
        r = get("https://news.google.com/rss/search",
                params={"q": f"{sym} PSX Pakistan stock", "hl": "en-PK", "gl": "PK", "ceid": "PK:en"})
        heads = [(it.findtext("title") or "") for it in ET.fromstring(r.content).findall(".//item")[:4]]
    except Exception:
        return [], 0
    s = sum(any(w in h.lower() for w in POS) - any(w in h.lower() for w in NEG) for h in heads)
    return heads[:3], s


# ---------- encryption (AES-256-GCM, key from your password via PBKDF2) ----------
def b64(b): return base64.b64encode(b).decode()
def key(pw, salt): return PBKDF2HMAC(hashes.SHA256(), 32, salt, 200_000).derive(pw.encode())
def encrypt(obj, pw):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(key(pw, salt)).encrypt(iv, json.dumps(obj).encode(), None)
    return {"v": 1, "salt": b64(salt), "iv": b64(iv), "data": b64(ct)}
def decrypt(blob, pw):
    raw = AESGCM(key(pw, base64.b64decode(blob["salt"]))).decrypt(
        base64.b64decode(blob["iv"]), base64.b64decode(blob["data"]), None)
    return json.loads(raw)
def load_prev(pw):
    try:
        with open(OUT) as f: return decrypt(json.load(f), pw)
    except Exception: return {}


# ---------- alerts ----------
def notify(title, msg, prio="high"):
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=msg.encode("utf-8"), timeout=15,
                          headers={"Title": title, "Priority": prio, "Tags": "chart_with_upwards_trend"})
        except Exception as e: print("ntfy failed:", e)
    user, pw = os.getenv("EMAIL_USER"), os.getenv("EMAIL_APP_PASSWORD")
    if user and pw:
        try:
            m = EmailMessage()
            m["Subject"], m["From"], m["To"] = title, user, os.getenv("EMAIL_TO") or user
            m.set_content(msg)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
                s.login(user, pw); s.send_message(m)
        except Exception as e: print("email failed:", e)

def tag(s): return " (Shariah)" if s["shariah"] else ""
def alert_new(s):
    notify(f"PSX signal: {s['symbol']}{tag(s)}",
           f"{s['symbol']}{tag(s)} at {s['issued_at']} PKT\nBUY around {s['entry']}\nSTOP LOSS {s['stop']}\n"
           f"SELL range {s['t1']} to {s['t2']}\nQty for {RISK_PCT:g}% risk: {s['shares']} shares (about Rs {s['cost']:,})\n"
           f"Why: {'; '.join(s['reasons'][:4])}\nIntraday only. Exit by close. Not financial advice.")


# ---------- main ----------
def run():
    now, force = datetime.now(PKT), bool(os.getenv("FORCE"))
    if not (market_open(now) or force):
        print("Market closed, nothing to do."); return
    pw = os.environ["DASH_PASSWORD"]
    prev, today = load_prev(pw), str(now.date())
    sigs = [s for s in prev.get("signals", []) if s["date"] == today]
    reminded = prev.get("reminded") == today
    err_sent = prev.get("err_alert") == today

    with ThreadPoolExecutor(6) as ex:
        res = [r for r in ex.map(safe_analyze, [(s, now) for s in WATCHLIST]) if r]
    status = "ok"
    if not res:
        status = "No data: " + (ERRORS[0] if ERRORS else "no stock passed the filters")
        print(status)
        if ERRORS and not err_sent:
            notify("PSX scanner: data problem", f"No data fetched. First error: {ERRORS[0][:200]}", "default"); err_sent = True
    by = {r["symbol"]: r for r in res}

    for s in sigs:                                              # update open signals
        r = by.get(s["symbol"])
        if not r: continue
        s["now"] = r["price"]
        st = "STOP HIT" if s["now"] <= s["stop"] else "TARGET 2 HIT" if s["now"] >= s["t2"] else \
             "TARGET 1 HIT" if s["now"] >= s["t1"] else "OPEN"
        if s["status"] not in ("STOP HIT", "TARGET 2 HIT") and st != s["status"]:
            s["status"] = st
            if st != "OPEN":
                notify(f"PSX update: {s['symbol']} {st}", f"{s['symbol']}{tag(s)} now {s['now']} ({st}). Entry {s['entry']}, stop {s['stop']}.")

    gap_ok = not sigs or time.time() - max(s["epoch"] for s in sigs) >= GAP_SECONDS
    if (signal_window(now) or force) and len(sigs) < MAX_SIGNALS and (gap_ok or force):
        have = {s["symbol"] for s in sigs}
        cands = sorted([r for r in res if r["symbol"] not in have and r["score"] >= MIN_SCORE - 6], key=lambda r: -r["score"])[:6]
        for r in cands:
            r["news"], r["news_score"] = news(r["symbol"])
            r["score"] += max(-6, min(6, 3 * r["news_score"]))
        cands = sorted([r for r in cands if r["score"] >= MIN_SCORE and r["news_score"] > -2], key=lambda r: -r["score"])
        for r in cands[:1]:                                     # one new signal per run, spaced out
            r.update(date=today, issued_at=now.strftime("%H:%M"), epoch=time.time(), status="OPEN", now=r["price"])
            sigs.append(r); alert_new(r)

    if mins(now) >= 900 and now.weekday() < 4 and not reminded and any(s["status"] == "OPEN" for s in sigs):
        notify("PSX reminder: close day trades", "Market closes 15:30. Close any open intraday positions unless you plan to hold.", "default")
        reminded = True

    done = {s["symbol"] for s in sigs}
    radar = [dict(symbol=r["symbol"], shariah=r["shariah"], price=r["price"], change=r["change"], score=r["score"])
             for r in sorted(res, key=lambda r: -r["score"]) if r["symbol"] not in done][:5]
    payload = dict(updated=now.isoformat(timespec="seconds"), date=today, market_open=market_open(now), status=status,
                   scanned=len(res), signals=sigs, radar=radar, capital=CAPITAL, risk_pct=RISK_PCT,
                   reminded=today if reminded else "", err_alert=today if err_sent else "")
    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w") as f: json.dump(encrypt(payload, pw), f)
    print(f"Done: {len(res)} scanned, {len(sigs)} signals today.")


def test():
    now = datetime.now(PKT)
    for sym in ["OGDC", "LUCK", "HUBC"]:
        try:
            e, i = eod(sym), intraday(sym)
            print(sym, "EOD rows:", len(e), "| last EOD:", e.iloc[-1].to_dict(), "| intraday rows:", len(i))
            print("   analysis:", analyze(sym, now))
        except Exception as ex:
            print(sym, "FAILED:", repr(ex))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--test", action="store_true"); a = ap.parse_args()
    test() if a.test else run()
