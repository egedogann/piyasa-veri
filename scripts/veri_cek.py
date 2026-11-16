"""
Günlük rapor için kamuya açık veri toplayıcı (GitHub Actions'ta çalışır, PC gerekmez).
- 5 dk barlar: NQ=F, ^NDX, GC=F, ES=F  -> data/m5/<sembol>.csv  (biriktirir, tekrarları atar)
- Günlük barlar: cross-asset evren       -> data/d1/<sembol>.csv
- Spot altın denemesi (birden çok kaynak) -> data/m5/XAU_SPOT.csv + data/kaynak_durumu.json
Her çalıştırma data/son_guncelleme.json yazar (raporun 'veri yaşı' kontrolü için).
"""
import json, os, io, sys, time
from datetime import datetime, timezone
import pandas as pd
import requests
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M5, D1 = os.path.join(ROOT, "data", "m5"), os.path.join(ROOT, "data", "d1")
os.makedirs(M5, exist_ok=True); os.makedirs(D1, exist_ok=True)

M5_SYMS = ["NQ=F", "^NDX", "GC=F", "ES=F"]
D1_SYMS = [
    "NQ=F", "^NDX", "ES=F", "RTY=F", "GC=F", "SI=F", "CL=F", "BZ=F", "HG=F",
    "^GDAXI", "^N225", "^HSI", "^STOXX50E", "DX-Y.NYB", "EURUSD=X", "JPY=X", "CNY=X",
    "^TNX", "^FVX", "^TYX", "^IRX", "2YY=F", "^VIX", "^VXN", "^GVZ", "^MOVE", "^VIX3M",
    "BTC-USD", "HYG", "LQD", "TLT", "QQQ", "GLD", "SMH", "NVDA", "AAPL", "MSFT", "AMZN",
    "META", "GOOGL", "AVGO", "TSLA", "TIP", "UUP", "^SPX",
]
status = {}


def safe(name):
    return name.replace("^", "IDX_").replace("=", "_").replace(".", "_").replace("-", "_")


def merge_save(df, path):
    if df is None or df.empty:
        return 0
    if os.path.exists(path):
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        df = pd.concat([old, df])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_csv(path)
    return len(df)


def yahoo(sym, interval, period):
    d = yf.download(sym, period=period, interval=interval, auto_adjust=False,
                    progress=False, prepost=True, threads=False)
    if d is None or d.empty:
        return None
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    idx = d.index if d.index.tz is not None else d.index.tz_localize("UTC")
    d.index = idx.tz_convert("UTC")
    d.index.name = "t_utc"
    return d


def spot_gold():
    """Spot altın için ücretsiz kaynak denemeleri; ilk çalışan kullanılır."""
    tries = []
    # 1) stooq intraday (5 dk) CSV
    try:
        r = requests.get("https://stooq.com/q/d/l/?s=xauusd&i=5", timeout=20)
        if r.ok and "Date" in r.text[:200]:
            d = pd.read_csv(io.StringIO(r.text))
            d["t_utc"] = pd.to_datetime(d["Date"] + " " + d["Time"]).dt.tz_localize("Europe/Warsaw").dt.tz_convert("UTC")
            d = d.set_index("t_utc").rename(columns=str.lower)[["open", "high", "low", "close"]]
            tries.append(("stooq_5m", len(d)))
            if len(d) > 50:
                return d, tries
        else:
            tries.append(("stooq_5m", "bos"))
    except Exception as e:
        tries.append(("stooq_5m", f"hata {e.__class__.__name__}"))
    # 2) Yahoo üzerinde olası spot kodları
    for code in ["XAUUSD=X", "XAU=X"]:
        try:
            d = yahoo(code, "5m", "5d")
            tries.append((f"yahoo_{code}", 0 if d is None else len(d)))
            if d is not None and len(d) > 50:
                return d.drop(columns=["volume"]), tries
        except Exception as e:
            tries.append((f"yahoo_{code}", f"hata {e.__class__.__name__}"))
    return None, tries


def m5_only():
    for s in M5_SYMS:
        try:
            status[f"m5:{s}"] = merge_save(yahoo(s, "5m", "5d"), os.path.join(M5, safe(s) + ".csv"))
        except Exception as e:
            status[f"m5:{s}"] = f"hata {e}"


def git_push(msg):
    import subprocess
    subprocess.run(["git", "add", "data"], cwd=ROOT)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        subprocess.run(["git", "commit", "-qm", msg], cwd=ROOT)
        subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT)
        subprocess.run(["git", "push", "-q"], cwd=ROOT)


def ny_window():
    """NY açılışı −15/−5/+5/+15 dk anlık görüntüler. Yanlış DST tetiklemesinde hemen çıkar."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    open_ = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if not (open_ - pd.Timedelta(minutes=50) <= now <= open_ - pd.Timedelta(minutes=10)):
        print(f"Pencere dışı ({now:%H:%M} ET), çıkılıyor"); return
    for off in (-15, -5, 5, 15):
        tgt = open_ + pd.Timedelta(minutes=off, seconds=40)  # barın kapanması için 40 sn pay
        wait = (tgt - datetime.now(et)).total_seconds()
        if wait > 0:
            time.sleep(wait)
        m5_only()
        write_meta(f"ny_acilis{off:+d}")
        git_push(f"ny acilis {off:+d} dk")


def write_meta(mod):
    son = {}
    for f in os.listdir(M5):
        try:
            x = pd.read_csv(os.path.join(M5, f), index_col=0, parse_dates=True)
            son[f] = str(x.index.max())
        except Exception:
            pass
    meta = {"calisma_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mod": mod,
            "son_bar_m5": son, "durum": status}
    with open(os.path.join(ROOT, "data", "son_guncelleme.json"), "w") as fh:
        json.dump(meta, fh, indent=1, default=str)
    print(json.dumps(meta, indent=1, default=str))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "ny_pencere":
        return ny_window()
    for s in M5_SYMS:
        try:
            p = os.path.join(M5, safe(s) + ".csv")
            # ilk çekimde 60 gün (Yahoo 5 dk sınırı), sonra son 5 gün birleştirilir
            per = "5d" if os.path.exists(p) and os.path.getsize(p) > 400_000 else "60d"
            n = merge_save(yahoo(s, "5m", per), p)
            status[f"m5:{s}"] = n
        except Exception as e:
            status[f"m5:{s}"] = f"hata {e}"
        time.sleep(1)
    for s in D1_SYMS:
        try:
            p = os.path.join(D1, safe(s) + ".csv")
            # ilk çekimde tüm geçmiş, sonra son 3 ay (birleştirilir)
            per = "3mo" if os.path.exists(p) and os.path.getsize(p) > 200_000 else "max"
            n = merge_save(yahoo(s, "1d", per), p)
            status[f"d1:{s}"] = n
        except Exception as e:
            status[f"d1:{s}"] = f"hata {e}"
        time.sleep(0.5)
    d, tries = spot_gold()
    status["xau_spot_denemeleri"] = tries
    if d is not None:
        status["m5:XAU_SPOT"] = merge_save(d, os.path.join(M5, "XAU_SPOT.csv"))

    write_meta("tam")
    bad = [k for k, v in status.items() if isinstance(v, str) and v.startswith("hata")]
    if len(bad) > len(status) // 2:
        sys.exit("Kaynakların yarısından fazlası hata verdi")


if __name__ == "__main__":
    main()
