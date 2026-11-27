"""
Günlük masa notu — hesap katmanı (PC gerekmez; yalnız repodaki data/ ve stats/ okunur).
Çıktı: rapor/veri.json  (rapor_html.py bunu sayfaya çevirir)

FTM fiyat tahmini
- US100 ≈ NQ=F + ofset.  ofset(t) = [son tamamlanan RTH'de medyan(NDX − NQ)] × kalan_gün(t)/kalan_gün(o RTH) + C
  C = −1.9 (FTM − NDX medyanı, kalibrasyon v2). Vadeli primi vadeye doğru doğrusal erir.
- XAUUSD ≈ GC=F + son ölçülen ofset (stats/ofset_altin.json; PC ile ölçülür, yaşı raporda yazılır).
Zaman: tüm seanslar ET; FTM günü = 17:00 ET → 17:00 ET (etiket = bitiş günü).
"""
import json, math, os, sys
from datetime import date, timedelta
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M5, D1, ST = [os.path.join(ROOT, *p) for p in (("data", "m5"), ("data", "d1"), ("stats",))]
C_NDX = -1.9
FEATS = ["l_atr", "l_prev", "l_on", "l_gap", "prev_cl_loc", "ev_major", "ev_fomc", "ev_cpi", "ev_nfp", "dow_0", "dow_4"]
SPEC = {"US100": {"src": "NQ_F", "bin": 10.0, "usd_per_pt_001": 0.20, "comm_001": 0.0, "iv": "IDX_VXN", "dec": 1},
        "XAUUSD": {"src": "GC_F", "bin": 1.0, "usd_per_pt_001": 1.0, "comm_001": 0.07, "iv": "IDX_GVZ", "dec": 2}}


def safe(n):
    return n.replace("^", "IDX_").replace("=", "_").replace(".", "_").replace("-", "_")


def m5(name):
    d = pd.read_csv(os.path.join(M5, name + ".csv"), index_col=0, parse_dates=True)
    d.index = pd.to_datetime(d.index, utc=True)
    d = d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["close"])
    d, nbad = clean(d)
    d.attrs["temizlenen"] = nbad
    d["et"] = d.index.tz_convert("America/New_York").tz_localize(None)
    d["fday"] = (d.et + pd.Timedelta(hours=7)).dt.normalize()
    d["mod"] = d.et.dt.hour * 60 + d.et.dt.minute
    return d


def clean(d):
    """Yahoo hatalı tick temizliği: open/high/low, önceki ve bu kapanıştan 10×medyan bar aralığından fazla taşıyorsa kırpılır.
    (Örnek: NQ=F 30 Eki 2026 15:00 ET barında açılış 29562, komşu kapanışlar 28234/28308.)"""
    d = d.copy()
    med = (d.high - d.low).rolling(288, min_periods=30).median().bfill()
    pc = d.close.shift(1).fillna(d.close)
    cap_hi = pd.concat([pc, d.close], axis=1).max(axis=1) + 10 * med
    cap_lo = pd.concat([pc, d.close], axis=1).min(axis=1) - 10 * med
    bad = (d.high > cap_hi) | (d.low < cap_lo) | (d.open > cap_hi) | (d.open < cap_lo)
    hi_ok = pd.concat([pc, d.close], axis=1).max(axis=1); lo_ok = pd.concat([pc, d.close], axis=1).min(axis=1)
    d.loc[d.open > cap_hi, "open"] = pc; d.loc[d.open < cap_lo, "open"] = pc
    d.loc[d.high > cap_hi, "high"] = hi_ok; d.loc[d.low < cap_lo, "low"] = lo_ok
    d["high"] = d[["open", "high", "close"]].max(axis=1); d["low"] = d[["open", "low", "close"]].min(axis=1)
    return d, int(bad.sum())


def d1(name):
    p = os.path.join(D1, safe(name) + ".csv")
    if not os.path.exists(p):
        return None
    x = pd.read_csv(p, index_col=0, parse_dates=True)
    x.index = pd.to_datetime(x.index, utc=True).tz_localize(None).normalize()
    return x[~x.index.duplicated(keep="last")].dropna(subset=["close"])


# ------------------------------------------------------------------ ofset
def third_friday(y, m):
    d = date(y, m, 15)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def nq_expiry(day):
    """Yahoo NQ=F'nin izlediği kontratın vadesi; vadeden 8 gün önce sonraki çeyreğe geçer."""
    y, m = day.year, day.month
    for _ in range(6):
        qm = ((m - 1) // 3 + 1) * 3
        e = third_friday(y, qm)
        if day <= e - timedelta(days=8):
            return e
        m = qm + 1
        if m > 12:
            y, m = y + 1, 1
    raise ValueError


def us100_offset(nq, ndx):
    j = pd.concat([ndx.close.rename("ndx"), nq.close.rename("nq")], axis=1, join="inner").dropna()
    et = j.index.tz_convert("America/New_York")
    mod = et.hour * 60 + et.minute
    j = j[(mod >= 600) & (mod < 960)]
    basis = (j.ndx - j.nq).groupby(j.index.tz_convert("America/New_York").tz_localize(None).normalize()).median()
    n = (j.ndx - j.nq).groupby(j.index.tz_convert("America/New_York").tz_localize(None).normalize()).size()
    basis = basis[n >= 40]
    # her bar için: 16:00 ET'si geçmiş son RTH günü
    ref_time = pd.Series(basis.index + pd.Timedelta(hours=16), index=basis.index)
    refs = pd.merge_asof(pd.DataFrame({"et": nq.et.values, "fday": nq.fday.values}, index=nq.index).sort_values("et"),
                         pd.DataFrame({"rt": ref_time.values, "d0": basis.index, "b0": basis.values}).sort_values("rt"),
                         left_on="et", right_on="rt", direction="backward")
    off, rel = [], []
    for fd, d0, b0 in zip(refs.fday, refs.d0, refs.b0):
        if pd.isna(d0):
            off.append(np.nan); rel.append(False); continue
        e_t, e_0 = nq_expiry(fd.date()), nq_expiry(d0.date())
        if e_t != e_0:
            off.append(np.nan); rel.append(False); continue
        off.append(b0 * (e_t - fd.date()).days / max((e_0 - d0.date()).days, 1) + C_NDX); rel.append(True)
    s = pd.Series(off, index=refs.et.values)
    s.index = nq.sort_values("et").index
    return s.reindex(nq.index), basis


def gold_offset(gc):
    p = os.path.join(ST, "ofset_altin.json")
    o = json.load(open(p))
    tab = pd.Series({pd.Timestamp(k): v for k, v in o["gunluk_medyan"].items()}).sort_index()
    s = tab.reindex(pd.DatetimeIndex(sorted(set(gc.fday))), method="ffill")
    return gc.fday.map(s), o


# ------------------------------------------------------------------ günlük tablo
def daily(d):
    g = d.groupby("fday")
    t = g.agg(f_open=("open", "first"), f_high=("high", "max"), f_low=("low", "min"), f_close=("close", "last"))
    rth = d[(d["mod"] >= 570) & (d["mod"] < 960)]
    r = rth.groupby("fday").agg(r_open=("open", "first"), r_high=("high", "max"), r_low=("low", "min"),
                                r_close=("close", "last"), r_n=("close", "size"))
    on = d[(d["mod"] >= 1080) | (d["mod"] < 570)].groupby("fday").agg(on_high=("high", "max"), on_low=("low", "min"))
    t = t.join([r, on])
    t["r_range"], t["f_range"], t["on_range"] = t.r_high - t.r_low, t.f_high - t.f_low, t.on_high - t.on_low
    return t


def vprofile(d, binsz):
    """Hacim profili: bar hacmi [low, high] aralığındaki kutulara eşit dağıtılır. POC, VAH, VAL (%70)."""
    if d.empty or d.volume.sum() <= 0:
        return None
    lo, hi = math.floor(d.low.min() / binsz) * binsz, math.ceil(d.high.max() / binsz) * binsz
    edges = np.arange(lo, hi + binsz, binsz)
    vol = np.zeros(len(edges) - 1)
    for l, h, v in zip(d.low.values, d.high.values, d.volume.values):
        a, b = int((l - lo) // binsz), int(min((h - lo) // binsz, len(vol) - 1))
        vol[a:b + 1] += v / (b - a + 1)
    i = int(vol.argmax()); a = b = i; tot = vol.sum(); acc = vol[i]
    while acc < 0.7 * tot and (a > 0 or b < len(vol) - 1):
        up = vol[b + 1] if b < len(vol) - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1; acc += vol[b]
        else:
            a -= 1; acc += vol[a]
    mid = edges[:-1] + binsz / 2
    return {"poc": float(mid[i]), "vah": float(edges[b + 1]), "val": float(edges[a]),
            "bins": [[float(m), float(v)] for m, v in zip(mid, vol)]}


def vwap(d):
    if d.empty or d.volume.sum() <= 0:
        return None
    tp = (d.high + d.low + d.close) / 3
    return float((tp * d.volume).sum() / d.volume.sum())


# ------------------------------------------------------------------ enstrüman paneli
def panel(sym, d, S, news_flags, now_utc):
    sp = SPEC[sym]
    t = daily(d)
    today = d.fday.iloc[-1]
    done = t[(t.index < today) & (t.r_n >= 70)]
    prev = done.iloc[-1]; pday = done.index[-1]
    px = float(d.close.iloc[-1])
    atr = float(done.r_range.tail(14).mean()); fatr = float(done.f_range.tail(14).mean())
    cur = d[d.fday == today]
    rth_today = cur[(cur["mod"] >= 570) & (cur["mod"] < 960)]
    on_cur = cur[(cur["mod"] >= 1080) | (cur["mod"] < 570)]
    wk = done[done.index.to_period("W") == (pday.to_period("W"))]
    mo = t[(t.index.to_period("M") == today.to_period("M")) & (t.index < today)]
    last20 = done.tail(20)
    dprev = d[d.fday == pday]
    d5 = d[d.fday.isin(done.index[-5:])]
    vp1, vp5 = vprofile(dprev, sp["bin"]), vprofile(d5, sp["bin"])
    dwk = d[d.fday.isin(wk.index)]
    out = {"sembol": sym, "fiyat": px, "fiyat_zamani_utc": str(d.index[-1]), "bugun": str(today.date()), "onceki_gun": str(pday.date()),
           "atr14_rth": atr, "atr14_tam_gun": fatr,
           "degisim_onceki_rth_kapanis": px - float(prev.r_close), "degisim_yuzde": (px / float(prev.r_close) - 1) * 100,
           "degisim_onceki_17": px - float(prev.f_close),
           "gece": {"high": float(on_cur.high.max()) if len(on_cur) else None, "low": float(on_cur.low.min()) if len(on_cur) else None,
                    "aralik": float(on_cur.high.max() - on_cur.low.min()) if len(on_cur) else None,
                    "tamam": bool(len(rth_today) > 0), "bar": int(len(on_cur))},
           "onceki": {k: float(prev[k]) for k in ["f_high", "f_low", "f_close", "r_open", "r_high", "r_low", "r_close", "r_range", "on_range"]}}
    out["onceki"]["kapanis_konumu"] = float((prev.r_close - prev.r_low) / prev.r_range)
    out["onceki"]["aralik_atr"] = float(prev.r_range / done.r_range.iloc[-15:-1].mean())
    # seviyeler
    L = []
    def add(name, v, grp, note=""):
        if v is not None and np.isfinite(v):
            L.append({"ad": name, "fiyat": float(v), "grup": grp, "not": note})
    add("Önceki gün high (FTM günü)", prev.f_high, "gün"); add("Önceki gün low (FTM günü)", prev.f_low, "gün")
    add("Önceki RTH high", prev.r_high, "gün"); add("Önceki RTH low", prev.r_low, "gün")
    add("Önceki RTH kapanış", prev.r_close, "gün", "gap referansı")
    add("Önceki gün 17:00 kapanış", prev.f_close, "gün")
    if len(on_cur):
        add("Gece high (şimdiye kadar)", on_cur.high.max(), "gece"); add("Gece low (şimdiye kadar)", on_cur.low.min(), "gece")
        add("Hafta açılışı" if today.dayofweek == 0 else "Gün açılışı (18:00 ET)", cur.open.iloc[0], "gece")
        vw = vwap(cur); add("Seans VWAP (şimdi)", vw, "vwap", "gerçek hacim")
    add("Geçen hafta high", wk.f_high.max(), "hafta"); add("Geçen hafta low", wk.f_low.min(), "hafta")
    add("Geçen hafta VWAP", vwap(dwk), "vwap", "gerçek hacim")
    add("Önceki gün VWAP", vwap(dprev), "vwap", "gerçek hacim")
    if len(mo):
        add("Ay high", mo.f_high.max(), "ay"); add("Ay low", mo.f_low.min(), "ay")
    add("20 gün high", last20.f_high.max(), "ay"); add("20 gün low", last20.f_low.min(), "ay")
    if vp1:
        add("Önceki gün POC", vp1["poc"], "profil"); add("Önceki gün VAH", vp1["vah"], "profil"); add("Önceki gün VAL", vp1["val"], "profil")
    if vp5:
        add("5 gün POC", vp5["poc"], "profil"); add("5 gün VAH", vp5["vah"], "profil"); add("5 gün VAL", vp5["val"], "profil")
    step = 500 if sym == "US100" else 50
    for k in (math.floor(px / step) * step, math.ceil(px / step) * step):
        add(f"Yuvarlak {k:g}", k, "yuvarlak")
    for x in L:
        x["uzaklik"] = x["fiyat"] - px; x["uzaklik_atr"] = (x["fiyat"] - px) / atr
    out["seviyeler"] = sorted(L, key=lambda x: -x["fiyat"])
    out["profil"] = {"onceki": {k: vp1[k] for k in ("poc", "vah", "val")} if vp1 else None,
                     "bes_gun": {k: vp5[k] for k in ("poc", "vah", "val")} if vp5 else None,
                     "bes_gun_bins": vp5["bins"] if vp5 else None}
    # aralık modeli (ima edilen vol'lü)
    M = S["v2"][sym]["ima_edilen_vol_modeli"]; co = M["katsayilar"]; q = M["artik_kantiller_IS"]
    feat_hist = pd.read_csv(os.path.join(ST, sym, "gunluk_ozellikler.csv"), index_col=0, parse_dates=True)
    lon_q = feat_hist.l_on.quantile([0.1, 0.5, 0.9]).to_dict()
    iv = d1(sp["iv"].replace("IDX_", "^"))
    iv_last = float(iv.close[iv.index < today].iloc[-1]); iv_date = iv.index[iv.index < today][-1]
    imp_move = iv_last / 100 / math.sqrt(252) * px
    on_done = out["gece"]["tamam"]
    on_now = out["gece"]["aralik"]
    gap = px - float(prev.r_close) if not on_done else float(rth_today.open.iloc[0] - prev.r_close)
    f = {"l_atr": math.log(atr), "l_prev": math.log(prev.r_range / atr), "l_gap": math.log1p(abs(gap) / atr),
         "prev_cl_loc": out["onceki"]["kapanis_konumu"],
         "ev_major": int(news_flags.get("ev_major", 0)), "ev_fomc": int(news_flags.get("ev_fomc", 0)),
         "ev_cpi": int(news_flags.get("ev_cpi", 0)), "ev_nfp": int(news_flags.get("ev_nfp", 0)),
         "dow_0": int(today.dayofweek == 0), "dow_4": int(today.dayofweek == 4),
         "har_1": math.log(prev.r_range / atr), "har_5": math.log(done.r_range.tail(5).mean() / atr),
         "har_22": math.log(done.r_range.tail(22).mean() / atr), "l_imp": math.log(imp_move / atr)}
    def band(l_on):
        ff = dict(f, l_on=l_on)
        p = co["sabit"] + sum(co[k] * ff[k] for k in co if k != "sabit")
        return {k: math.exp(p + v) for k, v in q.items()}
    if on_done and not np.isfinite(t.loc[today, "on_range"]):
        on_done = False  # gece barları eksik (veri boşluğu): kesin bant hesaplanamaz
    if on_done:
        l_on = math.log(max(float(t.loc[today, "on_range"]) / atr, 0.05)); senaryo = "kesin (gece aralığı tamam)"
        out["aralik"] = {"durum": senaryo, "ana": band(l_on)}
    else:
        out["aralik"] = {"durum": ("ön tahmin — gece seansı sürüyor; ana senaryo medyan gece aralığı" if not out["gece"]["tamam"]
                                   else "ön tahmin — gece barları eksik (veri boşluğu); ana senaryo medyan gece aralığı"),
                         "ana": band(lon_q[0.5]), "dar_gece": band(lon_q[0.1]), "genis_gece": band(lon_q[0.9]),
                         "gece_aralik_varsayim_atr": {k: math.exp(v) for k, v in zip(("dar", "medyan", "genis"), (lon_q[0.1], lon_q[0.5], lon_q[0.9]))},
                         "gece_simdiye_kadar_atr": (on_now / atr) if on_now else None}
        l_on = lon_q[0.5]
    out["aralik"].update({"model_R2_OOS": M["R2_OOS"], "kapsama_80_OOS": M["band80_OOS_kapsama"], "ozellikler": f})
    out["ima"] = {"endeks": sp["iv"].replace("IDX_", ""), "deger": iv_last, "tarih": str(iv_date.date()),
                  "gunluk_1sigma": imp_move, "gunluk_1sigma_atr": imp_move / atr}
    # vol rejimi
    vr = pd.read_csv(os.path.join(ST, sym, "vol_rejimi_gecmis.csv"), index_col=0, parse_dates=True).atr14.dropna()
    hist = pd.concat([vr, done.r_range.rolling(14).mean().dropna()[lambda x: x.index > vr.index.max()]]).tail(504)
    pct = float((hist <= atr).mean())
    out["vol_rejimi"] = {"atr_persentil_2y": pct, "etiket": "düşük" if pct < .25 else "normal" if pct < .75 else "yüksek" if pct < .9 else "aşırı",
                         "atr_5g_once": float(done.r_range.iloc[-19:-5].mean()), "atr_20g_once": float(done.r_range.iloc[-34:-20].mean())}
    # gün tipi
    G = S[sym]["gun_tipi_modeli"]
    out["gun_tipi"] = {"taban": G["taban_oran_OOS"], "tanimlar": G["tanimlar"]}
    x = {k: f.get(k, l_on) for k in FEATS}; x["l_on"] = l_on
    z = {k: (x[k] - G["olcekleyici_ortalama"][k]) / G["olcekleyici_std"][k] for k in FEATS}
    sc = {c: G["sabitler"][c] + sum(G["katsayilar"][c][k] * z[k] for k in FEATS) for c in G["katsayilar"]}
    mx = max(sc.values()); ex = {c: math.exp(v - mx) for c, v in sc.items()}; tot = sum(ex.values())
    out["gun_tipi"]["model_olasilik"] = {c: ex[c] / tot for c in ex}
    out["gun_tipi"]["model_gecerli_siniflar"] = [c for c, v in G["sinif_bazinda_OOS"].items() if v["rapora_al"]]
    # benzer günler (kNN 40; gece aralığı bilinmiyorsa ağırlığı 0)
    H = feat_hist.dropna(subset=FEATS + ["rel_range"])
    is_ = H[H.index <= "2022-12-31"]
    w = np.array([S[sym]["benzer_gun_agirliklar"][k] for k in FEATS])
    if not on_done:
        w[FEATS.index("l_on")] = 0.0
    Z = (H[FEATS] - is_[FEATS].mean()) / is_[FEATS].std()
    z0 = (pd.Series(x)[FEATS] - is_[FEATS].mean()) / is_[FEATS].std()
    dist = (((Z - z0) ** 2) * w).sum(axis=1)
    nn = H.loc[dist.nsmallest(40).index]
    out["benzer"] = {"n": 40, "rth_aralik_atr_p25_p50_p75": [float(v) for v in nn.rel_range.quantile([.25, .5, .75])],
                     "trend": float((nn.gun_tipi == "trend").mean()), "denge": float((nn.gun_tipi == "denge").mean()),
                     "donus": float((nn.gun_tipi == "donus").mean()), "yukari_kapanis": float((nn.r_close > nn.r_open).mean()),
                     "tum_ornek_yukari": float((H.r_close > H.r_open).mean()),
                     "en_yakin": [str(i.date()) for i in dist.nsmallest(5).index], "gece_dahil": bool(on_done)}
    # açılış konumu, gap
    loc = "ustte" if px > prev.f_high else "altta" if px < prev.f_low else "icinde"
    sk = pd.read_csv(os.path.join(ST, sym, "seviye_kirilma_olasiliklari.csv"), index_col=0)
    out["acilis"] = {"konum": loc, **{k: float(sk.loc[loc, k]) for k in sk.columns}}
    gp = pd.read_csv(os.path.join(ST, sym, "gap_istatistikleri.csv"), index_col=0)
    ga = abs(gap) / atr
    for lab in gp.index:
        lo_, hi_ = [float(v) for v in lab.strip("[)").split(",")]
        if lo_ <= ga < hi_:
            out["gap"] = {"puan": gap, "atr": gap / atr, "dilim": lab, "n": int(gp.loc[lab, "n"]),
                          "kapanma": float(gp.loc[lab, "RTH_icinde_kapanir"]), "gap_yonunde_kapanis": float(gp.loc[lab, "RTH_gap_yonunde_kapanir"])}
    out["or15"] = {k: S[sym][k] for k in ("OR15_aralik_ATR_medyan", "OR15_yukari_kirilir", "OR15_asagi_kirilir", "OR15_iki_yon_kirilir",
                                          "rth_ilk30dk_high_veya_low_olusturma")}
    # lot tablosu
    rows = []
    for mult in (0.15, 0.25, 0.35, 0.5):
        stop = mult * atr
        r = {"stop_atr": mult, "stop": stop}
        for risk in (25, 50):
            per001 = stop * sp["usd_per_pt_001"] + sp["comm_001"]
            lot = math.floor(risk / per001) * 0.01
            r[f"lot_{risk}"] = lot; r[f"gercek_{risk}"] = lot / 0.01 * per001
        r["min_lot_risk"] = stop * sp["usd_per_pt_001"] + sp["comm_001"]
        rows.append(r)
    out["lot"] = rows
    # grafik: son 5 FTM günü + bugün
    days = list(done.index[-4:]) + [today]
    c = d[d.fday.isin(days)]
    out["grafik"] = {"t": [x.strftime("%m-%d %H:%M") for x in c.et], "c": [round(float(v), sp["dec"]) for v in c.close],
                     "gun": [str(x.date()) for x in c.fday]}
    out["_t"] = t
    return out


# ------------------------------------------------------------------ cross-asset
PANO = [("Endeks", [("^NDX", "Nasdaq 100"), ("^SPX", "S&P 500"), ("RTY=F", "Russell 2000 (vadeli)"), ("^GDAXI", "DAX"), ("^N225", "Nikkei 225"), ("^HSI", "Hang Seng")]),
        ("Faiz / FX", [("^TNX", "ABD 10Y (%)"), ("^FVX", "ABD 5Y (%)"), ("^TYX", "ABD 30Y (%)"), ("DX-Y.NYB", "DXY"), ("EURUSD=X", "EURUSD"), ("JPY=X", "USDJPY")]),
        ("Emtia / Kripto", [("GC=F", "Altın (vadeli)"), ("SI=F", "Gümüş"), ("CL=F", "WTI"), ("BZ=F", "Brent"), ("HG=F", "Bakır"), ("BTC-USD", "Bitcoin")]),
        ("Vol / Kredi", [("^VIX", "VIX"), ("^VXN", "VXN"), ("^GVZ", "GVZ (altın vol)"), ("^MOVE", "MOVE (tahvil vol)"), ("HYG", "HYG (yüksek getirili)"), ("SMH", "SMH (yarı iletken)")]),
        ("Mega-cap", [("NVDA", "Nvidia"), ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("AMZN", "Amazon"), ("META", "Meta"), ("GOOGL", "Alphabet"), ("AVGO", "Broadcom"), ("TSLA", "Tesla")])]
YIELD = {"^TNX", "^FVX", "^TYX"}


def pano(ref):
    out = []
    for grp, items in PANO:
        rows = []
        for tk, lab in items:
            x = d1(tk)
            if x is None or len(x) < 70:
                continue
            c = x.close[x.index <= ref]
            if tk in YIELD:
                ch = c.diff() * 100; one, five, unit = ch.iloc[-1], (c.iloc[-1] - c.iloc[-6]) * 100, "bp"
            else:
                ch = c.pct_change() * 100; one, five, unit = ch.iloc[-1], (c.iloc[-1] / c.iloc[-6] - 1) * 100, "%"
            sd = ch.iloc[-61:-1].std()
            rows.append({"ad": lab, "kod": tk, "son": float(c.iloc[-1]), "tarih": str(c.index[-1].date()), "d1": float(one), "birim": unit,
                         "sigma": float(one / sd) if sd > 0 else None, "d5": float(five),
                         "y20": float((c.iloc[-1] - c.iloc[-21]) * 100) if tk in YIELD else float((c.iloc[-1] / c.iloc[-21] - 1) * 100)})
        out.append({"grup": grp, "satirlar": rows})
    return out


def vol_block(panels):
    g = lambda k: d1(k).close
    vix, v3, vxn, gvz, mv, ndx, gc = g("^VIX"), g("^VIX3M"), g("^VXN"), g("^GVZ"), g("^MOVE"), g("^NDX"), g("GC=F")
    def rv(c, n):
        return float(np.log(c).diff().tail(n).std() * math.sqrt(252) * 100)
    def pct(s, n=504):
        return float((s.tail(n) <= s.iloc[-1]).mean())
    return {"tarih": str(vix.index[-1].date()),
            "vix": float(vix.iloc[-1]), "vix_p": pct(vix), "vix3m": float(v3.iloc[-1]), "vix_vix3m": float(vix.iloc[-1] / v3.iloc[-1]),
            "vxn": float(vxn.iloc[-1]), "vxn_p": pct(vxn), "gvz": float(gvz.iloc[-1]), "gvz_p": pct(gvz), "move": float(mv.iloc[-1]), "move_p": pct(mv),
            "ndx_rv10": rv(ndx, 10), "ndx_rv20": rv(ndx, 20), "altin_rv10": rv(gc, 10), "altin_rv20": rv(gc, 20),
            "vxn_eksi_rv20": float(vxn.iloc[-1]) - rv(ndx, 20), "gvz_eksi_rv20": float(gvz.iloc[-1]) - rv(gc, 20)}


def corr_block(S):
    r = lambda k, y=False: (d1(k).close.diff() if y else np.log(d1(k).close).diff())
    pairs = [("XAU–DXY", "GC=F", "DX-Y.NYB", False, ("XAU", "DXY")), ("XAU–ABD 10Y", "GC=F", "^TNX", True, ("XAU", "ABD10Y")),
             ("XAU–S&P 500", "GC=F", "^SPX", False, ("XAU", "SPX")), ("US100–VIX", "^NDX", "^VIX", False, ("US100", "VIX")),
             ("US100–ABD 10Y", "^NDX", "^TNX", True, ("US100", "ABD10Y")), ("US100–DXY", "^NDX", "DX-Y.NYB", False, ("US100", "DXY")),
             ("US100–XAU", "^NDX", "GC=F", False, None)]
    out = []
    for lab, a, b, yb, key in pairs:
        j = pd.concat([r(a), r(b, yb)], axis=1, join="inner").dropna()
        c60, c20 = j.tail(60).corr().iloc[0, 1], j.tail(20).corr().iloc[0, 1]
        ref = S["v2"]["cross_asset_korelasyon"][key[0]][key[1]] if key else None
        out.append({"cift": lab, "g60": float(c60), "g20": float(c20), "tum": ref["tum"] if ref else S["v2"]["korelasyon_US100_XAU"]["RTH_getiri_korelasyonu_tumu"],
                    "p10_p90": ref["p10_p90_60g"] if ref else S["v2"]["korelasyon_US100_XAU"]["rolling60_p10_p50_p90"][::2]})
    return {"ciftler": out, "birlesik_std_orani": S["v2"]["korelasyon_US100_XAU"]["birlesik_std_orani"],
            "ikisi_birden_kotu": S["v2"]["korelasyon_US100_XAU"]["ikisi_birden_-0.5ATR_gunu"]}


def main():
    S = json.load(open(os.path.join(ST, "ozet.json"), encoding="utf-8"))
    news_p = os.path.join(ROOT, "rapor", "haber.json")
    news = json.load(open(news_p, encoding="utf-8")) if os.path.exists(news_p) else {}
    flags = news.get("bugun_bayraklar", {})
    nq, ndx, gc = m5("NQ_F"), m5("IDX_NDX"), m5("GC_F")
    off, basis = us100_offset(nq, ndx)
    U = nq.copy()
    for c in ("open", "high", "low", "close"):
        U[c] = nq[c] + off
    U = U.dropna(subset=["close"])
    goff, gmeta = gold_offset(gc)
    G = gc.copy()
    for c in ("open", "high", "low", "close"):
        G[c] = gc[c] + goff
    G = G.dropna(subset=["close"])
    now = nq.index[-1]
    pu, pg = panel("US100", U, S, flags, now), panel("XAUUSD", G, S, flags, now)
    last_rth = basis.index[-1]
    e = nq_expiry(U.fday.iloc[-1].date())
    pu["ofset"] = {"deger": float(off.dropna().iloc[-1]), "yontem": "NDX−NQ bazı (son RTH) × kalan gün oranı − 1.9",
                   "baz_son_rth": float(basis.iloc[-1]), "baz_tarihi": str(last_rth.date()), "kaynak_fiyat": float(nq.close.iloc[-1]),
                   "vade": str(e), "vadeye_gun": (e - U.fday.iloc[-1].date()).days,
                   "rollover_yakin": bool((e - timedelta(days=8) - U.fday.iloc[-1].date()).days <= 5),
                   "hata_butcesi": "aynı gün ~5 puan (p90), 1 gün eski ~14 puan (p90)"}
    age = (U.fday.iloc[-1] - pd.Timestamp(gmeta["son_olcum"])).days
    pg["ofset"] = {"deger": float(goff.dropna().iloc[-1]), "yontem": "GC=F + FTM ile son ölçülen ofset", "son_olcum": gmeta["son_olcum"],
                   "yas_gun": int(age), "kaynak_fiyat": float(gc.close.iloc[-1]), "hata_butcesi": gmeta["hata_butcesi"],
                   "uyari": "yaklaşık" if age > 1 else "güncel ölçüm"}
    tu, tg = pu.pop("_t"), pg.pop("_t")
    out = {"uretim_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="minutes"), "veri_son_bar_utc": str(now),
           "temizlenen_bar": {"NQ": nq.attrs.get("temizlenen", 0), "GC": gc.attrs.get("temizlenen", 0), "NDX": ndx.attrs.get("temizlenen", 0)},
           "US100": pu, "XAUUSD": pg, "pano": pano(d1("^VIX").index[-1]), "pano_tarih": str(d1("^VIX").index[-1].date()), "vol": vol_block((pu, pg)), "korelasyon": corr_block(S),
           "model": {"aralik_R2": {s: S["v2"][s]["ima_edilen_vol_modeli"]["R2_OOS"] for s in ("US100", "XAUUSD")}}}
    os.makedirs(os.path.join(ROOT, "rapor"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "rapor", "veri.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=float)
    return out, U, G, off, basis


if __name__ == "__main__":
    o, U, G, off, basis = main()
    for s in ("US100", "XAUUSD"):
        p = o[s]
        print(s, "fiyat", round(p["fiyat"], 2), "ATR", round(p["atr14_rth"], 1), "ofset", round(p["ofset"]["deger"], 2),
              "aralık %80", [round(p["aralik"]["ana"][k]) for k in ("q10", "q50", "q90")], p["vol_rejimi"]["etiket"])
