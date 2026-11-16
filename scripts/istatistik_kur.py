"""
Günlük rapor için geçmiş istatistik katmanı (FTM MT5 M5 verisinden; bir kez / ayda bir çalıştırılır).
Girdi: F_<SEMBOL>_M5.csv.gz (dt_server = ET+7), usd_calendar.csv (MT5 takvim, UTC+3), spread dosyaları.
Çıktı: stats/<SEMBOL>/*.csv|json + stats/ozet.json

Kurallar
- Zaman: sunucu − 7 saat = ET (FTM sunucusu NY-hizalı). FTM günü = sunucu tarihi (17:00 ET → 17:00 ET).
- Seanslar (ET): ON (overnight) 18:00 → 09:29 · Asya 18:00–01:59 · Londra 02:00–08:29 · RTH 09:30–15:59.
- Look-ahead yok: her günün özellikleri yalnız 09:30 ET'den önce bilinen verilerden.
- IS ≤ 2022-12-31, OOS ≥ 2023-01-01. Olasılık modelleri OOS'ta taban orana karşı Brier skill ile değerlendirilir;
  skill ≤ 0 olan model 'rapora_al = False' işaretlenir.
"""
import json, os, sys
import numpy as np
import pandas as pd

SEED = 7
rng = np.random.default_rng(SEED)
DATA = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/ftm_quant/ftm_data"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stats")
IS_END = pd.Timestamp("2022-12-31")
START = {"US100": "2017-04-04", "XAUUSD": "2016-01-04"}
CAL_IDS = {
    "fomc": {840050014, 840050002}, "fomc_minutes": {840050004}, "cpi": {840030005, 840030006, 840030007, 840030034, 840030035},
    "pce": {840010001, 840010002}, "nfp": {840030016, 840030015, 840030018}, "gdp": {840010007},
    "retail": {840020010, 840020011}, "ism": {840040001, 840040003, 840040002, 840040008}, "jolts": {840030021},
    "ppi": {840030001}, "sentiment": {840210001, 840180002}, "fed_chair": {840050022, 840050006, 840050021, 840050005},
}
PRIORITY = ["fomc", "cpi", "nfp", "pce", "ppi", "retail", "gdp", "ism", "jolts", "fomc_minutes", "sentiment", "fed_chair"]
summary = {"olusturma": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "IS_bitis": str(IS_END.date()),
           "kurallar": __doc__.strip().splitlines()[3:9]}


def save(df, sym, name):
    p = os.path.join(OUT, sym); os.makedirs(p, exist_ok=True)
    df.to_csv(os.path.join(p, name), float_format="%.4f")


# ------------------------------------------------------------------ veri
def load(sym):
    d = pd.read_csv(os.path.join(DATA, f"F_{sym}_M5.csv.gz"), parse_dates=["dt_server"])
    d = d[d.dt_server >= START[sym]]
    d["et"] = d.dt_server - pd.Timedelta(hours=7)
    d["fday"] = d.dt_server.dt.normalize()
    d["mod"] = d.et.dt.hour * 60 + d.et.dt.minute  # ET dakika
    return d.set_index("et").sort_index()


def load_events():
    ev = pd.read_csv(os.path.join(DATA, "usd_calendar.csv"), encoding="cp1254")
    ev["srv"] = pd.to_datetime(ev.time_calendar, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    ev = ev.dropna(subset=["srv"])
    ev["et"] = (ev.srv - pd.Timedelta(hours=3)).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
    ev["key"] = None
    for k in reversed(PRIORITY):
        ev.loc[ev.event_id.isin(CAL_IDS[k]), "key"] = k
    ev = ev.dropna(subset=["key"])
    # aynı dakikadaki olaylar: en öncelikli anahtar kalır
    ev["rank"] = ev.key.map({k: i for i, k in enumerate(PRIORITY)})
    ev = ev.sort_values("rank").drop_duplicates("et").sort_values("et")
    nfp = ev[ev.key == "nfp"].et.dt.strftime("%H:%M").value_counts(normalize=True)
    summary["takvim_saat_kontrolu_NFP_0830_payi"] = round(float(nfp.get("08:30", 0)), 3)
    return ev[["et", "key", "name", "actual", "forecast", "previous"]]


def sess(d, a, b, wrap=False):
    m = d["mod"]
    return d[(m >= a) | (m < b)] if wrap else d[(m >= a) & (m < b)]


def daily_table(d, ev):
    """Her FTM günü için özellikler (09:30 öncesi) ve sonuçlar (RTH)."""
    g = d.groupby("fday")
    full = g.agg(f_open=("open", "first"), f_high=("high", "max"), f_low=("low", "min"), f_close=("close", "last"), f_n=("close", "size"))
    rth = sess(d, 570, 960)
    r = rth.groupby("fday").agg(r_open=("open", "first"), r_high=("high", "max"), r_low=("low", "min"),
                                r_close=("close", "last"), r_n=("close", "size"))
    on = d[(d["mod"] >= 1080) | (d["mod"] < 570)]
    o = on.groupby("fday").agg(on_high=("high", "max"), on_low=("low", "min"), on_n=("close", "size"))
    asia = d[(d["mod"] >= 1080) | (d["mod"] < 120)].groupby("fday").agg(as_high=("high", "max"), as_low=("low", "min"))
    lon = sess(d, 120, 510).groupby("fday").agg(lo_high=("high", "max"), lo_low=("low", "min"))
    pre = d[d["mod"] < 570].groupby("fday")["close"].last().rename("pre_close")
    # RTH high/low zamanları
    def hl_time(x):
        return pd.Series({"t_high": x["mod"].iloc[x.high.values.argmax()], "t_low": x["mod"].iloc[x.low.values.argmin()]})
    hlt = rth.groupby("fday")[["mod", "high", "low"]].apply(hl_time)
    # açılış aralığı (ilk 15 / 30 dk)
    or15 = sess(d, 570, 585).groupby("fday").agg(or15_h=("high", "max"), or15_l=("low", "min"))
    or30 = sess(d, 570, 600).groupby("fday").agg(or30_h=("high", "max"), or30_l=("low", "min"))
    t = full.join([r, o, asia, lon, pre, hlt, or15, or30], how="left")
    t = t[(t.r_n >= 70)]  # tam RTH günleri (yarım gün / tatil hariç)
    t["r_range"] = t.r_high - t.r_low
    t["f_range"] = t.f_high - t.f_low
    t["atr14"] = t.r_range.shift(1).rolling(14).mean()               # dünkü dahil, bugün hariç
    t["f_atr14"] = t.f_range.shift(1).rolling(14).mean()
    t["prev_range"] = t.r_range.shift(1)
    t["prev_close"] = t.r_close.shift(1)
    t["prev_f_high"], t["prev_f_low"] = t.f_high.shift(1), t.f_low.shift(1)
    t["prev_r_high"], t["prev_r_low"] = t.r_high.shift(1), t.r_low.shift(1)
    t["on_range"] = t.on_high - t.on_low
    t["as_range"], t["lo_range"] = t.as_high - t.as_low, t.lo_high - t.lo_low
    t["gap"] = t.r_open - t.prev_close
    t["prev_cl_loc"] = ((t.r_close - t.r_low) / t.r_range).shift(1)
    t["ret5"] = (t.r_close.shift(1) - t.r_close.shift(6))
    t["dow"] = t.index.dayofweek
    # olay bayrakları (RTH günü ET tarihi = FTM günü)
    evd = ev.copy(); evd["d"] = evd.et.dt.normalize()
    for k in PRIORITY:
        days = set(evd.loc[evd.key == k, "d"])
        t[f"ev_{k}"] = t.index.isin(days).astype(int)
    t["ev_major"] = t[[f"ev_{k}" for k in ["fomc", "cpi", "nfp", "pce", "ppi", "retail", "gdp"]]].max(axis=1)
    # gün tipi (RTH, ATR'ye göre)
    body = (t.r_close - t.r_open).abs()
    rel = t.r_range / t.atr14
    cl_loc = (t.r_close - t.r_low) / t.r_range
    early = 570 + 120
    first_ext = np.where(t.t_high < t.t_low, "high", "low")
    rev = ((rel >= 0.9) & (body <= 0.35 * t.r_range) &
           (((first_ext == "high") & (t.t_high < early) & (cl_loc <= 0.3)) |
            ((first_ext == "low") & (t.t_low < early) & (cl_loc >= 0.7))))
    trend = (rel >= 0.9) & (body >= 0.6 * t.r_range) & ((cl_loc >= 0.8) | (cl_loc <= 0.2))
    bal = (rel <= 0.75) & (body <= 0.35 * t.r_range)
    t["gun_tipi"] = np.select([trend, rev, bal], ["trend", "donus", "denge"], "normal")
    t["rel_range"] = rel
    return t.dropna(subset=["atr14", "prev_close", "on_range"])


# ------------------------------------------------------------------ modeller
FEATS = ["l_atr", "l_prev", "l_on", "l_gap", "prev_cl_loc", "ev_major", "ev_fomc", "ev_cpi", "ev_nfp", "dow_0", "dow_4"]


def feats(t):
    X = pd.DataFrame(index=t.index)
    X["l_atr"] = np.log(t.atr14)
    X["l_prev"] = np.log(t.prev_range / t.atr14)
    X["l_on"] = np.log((t.on_range / t.atr14).clip(lower=0.05))
    X["l_gap"] = np.log1p((t.gap.abs() / t.atr14))
    X["prev_cl_loc"] = t.prev_cl_loc
    for k in ["ev_major", "ev_fomc", "ev_cpi", "ev_nfp"]:
        X[k] = t[k]
    X["dow_0"], X["dow_4"] = (t.dow == 0).astype(int), (t.dow == 4).astype(int)
    return X


def range_model(t, sym):
    X, y = feats(t), np.log(t.r_range)
    ok = X.notna().all(axis=1) & np.isfinite(y)
    X, y = X[ok], y[ok]
    isx = X.index <= IS_END
    A = np.c_[np.ones(isx.sum()), X[isx].values]
    beta, *_ = np.linalg.lstsq(A, y[isx].values, rcond=None)
    pred = np.c_[np.ones(len(X)), X.values] @ beta
    res = y.values - pred
    q = np.quantile(res[isx], [0.1, 0.25, 0.5, 0.75, 0.9])
    oos = ~isx
    naive = np.log(t.loc[X.index, "atr14"]).values
    def r2(p, m):
        e = y.values[m] - p[m]; return 1 - (e ** 2).sum() / ((y.values[m] - y.values[m].mean()) ** 2).sum()
    # naif: ATR + IS ortalama log farkı
    nb = (y.values[isx] - naive[isx]).mean()
    cov = {}
    for lo, hi, name in [(0, 4, "80"), (1, 3, "50")]:
        inside = (res[oos] >= q[lo]) & (res[oos] <= q[hi])
        cov[f"band_{name}_OOS_kapsama"] = round(float(inside.mean()), 3)
    out = {"katsayilar": dict(zip(["sabit"] + FEATS, np.round(beta, 5).tolist())),
           "artik_kantiller_IS": dict(zip(["q10", "q25", "q50", "q75", "q90"], np.round(q, 4).tolist())),
           "R2_log_IS": round(r2(pred, isx), 3), "R2_log_OOS": round(r2(pred, oos), 3),
           "R2_log_OOS_naif_ATR": round(r2(naive + nb, oos), 3), **cov,
           "n_IS": int(isx.sum()), "n_OOS": int(oos.sum()),
           "kullanim": "log(aralik) = sabit + Σ katsayı·özellik; bant = exp(tahmin + artık kantili)",
           "rapora_al": bool(r2(pred, oos) > r2(naive + nb, oos))}
    return out


def brier_skill(p, yb, base):
    bs = ((p - yb) ** 2).sum(axis=1).mean()
    b0 = ((base[None, :] - yb) ** 2).sum(axis=1).mean()
    return 1 - bs / b0


def daytype_model(t, sym):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    X = feats(t); ok = X.notna().all(axis=1)
    X, lab = X[ok], t.loc[ok, "gun_tipi"]
    classes = ["trend", "donus", "denge", "normal"]
    Y = np.stack([(lab == c).values.astype(float) for c in classes], 1)
    isx = X.index <= IS_END; oos = ~isx
    sc = StandardScaler().fit(X[isx])
    m = LogisticRegression(max_iter=2000, C=0.5).fit(sc.transform(X[isx]), lab[isx])
    P = m.predict_proba(sc.transform(X))
    P = P[:, [list(m.classes_).index(c) for c in classes]]
    base = Y[isx].mean(0)
    bss = brier_skill(P[oos], Y[oos], base)
    # gün bloklu bootstrap (20 gün) CI
    idx = np.where(oos)[0]; nb = len(idx) // 20; boots = []
    for _ in range(500):
        st = rng.integers(0, len(idx) - 20, nb)
        sel = np.concatenate([idx[s:s + 20] for s in st])
        boots.append(brier_skill(P[sel], Y[sel], base))
    lo, hi = np.percentile(boots, [5, 95])
    # sınıf bazında ikili Brier skill (OOS) + bootstrap CI
    per = {}
    for j, c in enumerate(classes):
        def b1(sel):
            p, yy = P[sel, j], Y[sel, j]
            return 1 - ((p - yy) ** 2).mean() / ((base[j] - yy) ** 2).mean()
        bb = []
        for _ in range(500):
            st = rng.integers(0, len(idx) - 20, nb)
            bb.append(b1(np.concatenate([idx[s:s + 20] for s in st])))
        l1, h1 = np.percentile(bb, [5, 95])
        per[c] = {"bss": round(float(b1(idx)), 4), "ci90": [round(float(l1), 4), round(float(h1), 4)], "rapora_al": bool(l1 > 0)}
    # kalibrasyon (OOS, en olası sınıfın olasılık dilimleri)
    cal = []
    for j, c in enumerate(classes):
        pj, yj = P[oos, j], Y[oos, j]
        bins = pd.qcut(pj, 5, duplicates="drop")
        cal.append(pd.DataFrame({"sinif": c, "p": pj, "y": yj, "dilim": bins.astype(str)})
                   .groupby(["sinif", "dilim"], observed=True).agg(tahmin=("p", "mean"), gercek=("y", "mean"), n=("y", "size")))
    save(pd.concat(cal), sym, "gun_tipi_kalibrasyon_OOS.csv")
    pd.DataFrame(P, index=X.index, columns=[f"p_{c}" for c in classes]).join(lab).to_csv(
        os.path.join(OUT, sym, "gun_tipi_tahminleri.csv"), float_format="%.3f")
    return {"tanimlar": {
                "trend": "RTH aralık ≥ 0.9×ATR14, |kapanış−açılış| ≥ 0.6×aralık, kapanış aralığın uç %20'sinde",
                "donus": "aralık ≥ 0.9×ATR, gövde ≤ 0.35×aralık, ilk uç ilk 2 saatte, kapanış karşı %30'da",
                "denge": "aralık ≤ 0.75×ATR ve gövde ≤ 0.35×aralık (akümülasyon/denge)",
                "normal": "diğer"},
            "taban_oran_IS": dict(zip(classes, np.round(base, 3).tolist())),
            "taban_oran_OOS": dict(zip(classes, np.round(Y[oos].mean(0), 3).tolist())),
            "brier_skill_OOS": round(float(bss), 4), "sinif_bazinda_OOS": per, "bss_90CI": [round(float(lo), 4), round(float(hi), 4)],
            "olcekleyici_ortalama": dict(zip(FEATS, np.round(sc.mean_, 5).tolist())),
            "olcekleyici_std": dict(zip(FEATS, np.round(sc.scale_, 5).tolist())),
            "katsayilar": {c: dict(zip(FEATS, np.round(m.coef_[list(m.classes_).index(c)], 4).tolist())) for c in classes},
            "sabitler": {c: round(float(m.intercept_[list(m.classes_).index(c)]), 4) for c in classes},
            "rapora_al": bool(lo > 0), "not": "rapora_al: OOS Brier skill %90 CI alt sınırı > 0"}


# ------------------------------------------------------------------ tanımlayıcı istatistikler
def event_reactions(d, ev, t, sym):
    c = d["close"]; o = d["open"]; h = d["high"]; l = d["low"]
    rows = []
    atr = t["atr14"]
    for _, e in ev.iterrows():
        t0 = e.et
        if t0 not in d.index:
            continue
        day = d.loc[t0, "fday"]
        if isinstance(day, pd.Series):
            day = day.iloc[0]
        if day not in atr.index:
            continue
        a = atr.loc[day]
        p0 = o.loc[t0] if not isinstance(o.loc[t0], pd.Series) else o.loc[t0].iloc[0]
        r = {"et": t0, "key": e.key, "atr14": a}
        for mins in (5, 15, 60):
            w = d.loc[t0: t0 + pd.Timedelta(minutes=mins - 5)]
            if len(w) == 0:
                continue
            r[f"hareket_{mins}"] = w.close.iloc[-1] - p0
            r[f"aralik_{mins}"] = w.high.max() - w.low.min()
        rows.append(r)
    R = pd.DataFrame(rows).dropna()
    if R.empty:
        return {}
    for m in (5, 15, 60):
        R[f"abs_{m}_atr"] = R[f"hareket_{m}"].abs() / R.atr14
    save(R.set_index("et"), sym, "olay_tepkileri_ham.csv")
    g = R.groupby("key")
    tab = pd.DataFrame({
        "n": g.size(),
        "abs15_medyan_puan": g["hareket_15"].apply(lambda x: x.abs().median()),
        "abs15_p90_puan": g["hareket_15"].apply(lambda x: x.abs().quantile(0.9)),
        "aralik15_medyan_puan": g["aralik_15"].median(),
        "aralik60_medyan_puan": g["aralik_60"].median(),
        "abs15_medyan_ATR": g["abs_15_atr"].median(),
        "abs60_medyan_ATR": g["abs_60_atr"].median(),
        "son2y_abs15_medyan_puan": R[R.et >= R.et.max() - pd.Timedelta(days=730)].groupby("key")["hareket_15"].apply(lambda x: x.abs().median()),
    }).sort_values("abs15_medyan_ATR", ascending=False)
    save(tab, sym, "olay_tepkileri_ozet.csv")
    # olay günü RTH aralığı / ATR
    gm = {k: float(t.loc[t[f"ev_{k}"] == 1, "rel_range"].median()) for k in PRIORITY if t[f"ev_{k}"].sum() > 20}
    gm["olaysiz"] = float(t.loc[t.ev_major == 0, "rel_range"].median())
    return {"olay_gunu_RTH_aralik_ATR_medyan": {k: round(v, 3) for k, v in gm.items()}}


def time_of_day(t, sym):
    bins = list(range(570, 961, 30))
    lab = [f"{b//60:02d}:{b%60:02d}" for b in bins[:-1]]
    hi = pd.cut(t.t_high, bins, right=False, labels=lab).value_counts(normalize=True).sort_index()
    lo = pd.cut(t.t_low, bins, right=False, labels=lab).value_counts(normalize=True).sort_index()
    cum = pd.DataFrame({"high_bu_dilimde": hi, "low_bu_dilimde": lo})
    marks = list(range(600, 961, 30))
    cum2 = pd.DataFrame({
        "saat_ET": [f"{m//60:02d}:{m%60:02d}" for m in marks],
        "high_olusmus": [(t.t_high < m).mean() for m in marks],
        "low_olusmus": [(t.t_low < m).mean() for m in marks],
        "ikisi_olusmus": [((t.t_high < m) & (t.t_low < m)).mean() for m in marks]}).set_index("saat_ET")
    save(cum, sym, "rth_high_low_saat_dagilimi.csv")
    save(cum2, sym, "rth_high_low_olusma_olasiligi.csv")
    ev = t[t.ev_major == 1]
    cum3 = pd.DataFrame({"saat_ET": [f"{m//60:02d}:{m%60:02d}" for m in marks],
                         "olay_gunu_ikisi_olusmus": [((ev.t_high < m) & (ev.t_low < m)).mean() for m in marks]}).set_index("saat_ET")
    save(cum3, sym, "rth_high_low_olusma_olay_gunu.csv")
    return {"rth_ilk30dk_high_veya_low_olusturma": round(float(((t.t_high < 600) | (t.t_low < 600)).mean()), 3)}


def levels(t, sym):
    out = {}
    loc = np.select([t.r_open > t.prev_f_high, t.r_open < t.prev_f_low], ["ustte", "altta"], "icinde")
    t = t.assign(acilis_konumu=loc)
    t["pdh_alindi"] = t.r_high > t.prev_f_high
    t["pdl_alindi"] = t.r_low < t.prev_f_low
    t["onh_alindi"] = t.r_high > t.on_high
    t["onl_alindi"] = t.r_low < t.on_low
    t["on_ikisi"] = t.onh_alindi & t.onl_alindi
    tab = t.groupby("acilis_konumu").agg(n=("pdh_alindi", "size"), PDH_RTH_kirilir=("pdh_alindi", "mean"),
                                       PDL_RTH_kirilir=("pdl_alindi", "mean"), ONH_kirilir=("onh_alindi", "mean"),
                                       ONL_kirilir=("onl_alindi", "mean"))
    tab.loc["tumu"] = [len(t), t.pdh_alindi.mean(), t.pdl_alindi.mean(), t.onh_alindi.mean(), t.onl_alindi.mean()]
    save(tab, sym, "seviye_kirilma_olasiliklari.csv")
    # açılış aralığı
    orr = (t.or15_h - t.or15_l) / t.atr14
    t["or15_up"] = t.r_high > t.or15_h
    t["or15_dn"] = t.r_low < t.or15_l
    out["OR15_aralik_ATR_medyan"] = round(float(orr.median()), 3)
    out["OR15_yukari_kirilir"] = round(float(t.or15_up.mean()), 3)
    out["OR15_asagi_kirilir"] = round(float(t.or15_dn.mean()), 3)
    out["OR15_iki_yon_kirilir"] = round(float((t.or15_up & t.or15_dn).mean()), 3)
    # gap
    g = t.gap / t.atr14
    filled = np.where(t.gap > 0, t.r_low <= t.prev_close, t.r_high >= t.prev_close)
    gb = pd.cut(g.abs(), [0, 0.1, 0.25, 0.5, 1, 10], right=False)
    gtab = pd.DataFrame({"kapandi": filled, "dilim": gb, "yon": np.sign(t.gap),
                         "devam": np.sign(t.r_close - t.r_open) == np.sign(t.gap)}).groupby("dilim", observed=True).agg(
        n=("kapandi", "size"), RTH_icinde_kapanir=("kapandi", "mean"), RTH_gap_yonunde_kapanir=("devam", "mean"))
    gtab.index = gtab.index.astype(str); gtab.index.name = "gap_ATR"
    save(gtab, sym, "gap_istatistikleri.csv")
    return out


def sessions(t, sym):
    a = t.as_range / t.atr14
    q = pd.qcut(a, 5, labels=["Q1 dar", "Q2", "Q3", "Q4", "Q5 genis"])
    tab = pd.DataFrame({"asya_dilim": q, "londra_ATR": t.lo_range / t.atr14, "rth_ATR": t.rel_range,
                        "rth_asya_ustu_kirar": t.r_high > t.as_high, "rth_asya_alti_kirar": t.r_low < t.as_low,
                        "trend": t.gun_tipi == "trend"}).groupby("asya_dilim", observed=True).agg(
        n=("rth_ATR", "size"), londra_aralik_ATR_medyan=("londra_ATR", "median"), rth_aralik_ATR_medyan=("rth_ATR", "median"),
        rth_asya_high_kirar=("rth_asya_ustu_kirar", "mean"), rth_asya_low_kirar=("rth_asya_alti_kirar", "mean"),
        trend_gunu_orani=("trend", "mean"))
    save(tab, sym, "seans_devri_asya_dilimleri.csv")
    oq = pd.qcut(t.on_range / t.atr14, 5, labels=["Q1 dar", "Q2", "Q3", "Q4", "Q5 genis"])
    tab2 = t.assign(on_dilim=oq).groupby("on_dilim", observed=True).agg(
        n=("rel_range", "size"), rth_aralik_ATR_medyan=("rel_range", "median"),
        trend=("gun_tipi", lambda x: (x == "trend").mean()), denge=("gun_tipi", lambda x: (x == "denge").mean()),
        donus=("gun_tipi", lambda x: (x == "donus").mean()))
    save(tab2, sym, "gece_araligi_dilimleri.csv")
    dow = t.groupby("dow").agg(n=("rel_range", "size"), rth_aralik_ATR_medyan=("rel_range", "median"),
                               trend=("gun_tipi", lambda x: (x == "trend").mean()),
                               denge=("gun_tipi", lambda x: (x == "denge").mean()),
                               yukari_kapanis=("r_close", lambda x: np.nan))
    dow["yukari_kapanis"] = t.groupby("dow").apply(lambda x: (x.r_close > x.r_open).mean())
    dow.index = ["Pzt", "Sal", "Çar", "Per", "Cum"][: len(dow)]
    save(dow, sym, "haftanin_gunu.csv")
    nr = t.prev_range <= t.r_range.shift(1).rolling(7).min()
    return {"NR7_sonrasi_rth_aralik_ATR_medyan": round(float(t.loc[nr, "rel_range"].median()), 3),
            "diger_gunler_rth_aralik_ATR_medyan": round(float(t.loc[~nr, "rel_range"].median()), 3), "NR7_n": int(nr.sum())}


def streaks(t, sym):
    """Yön istatistiği — yalnız bilgi; IS ve OOS ayrı, binom testi."""
    from scipy.stats import binomtest
    up = (t.r_close > t.r_open).astype(int)
    rows = []
    for n in (2, 3, 4):
        for side in ("dusus", "yukselis"):
            s = (up == (0 if side == "dusus" else 1)).astype(int)
            run = s.rolling(n).sum().shift(1) == n
            for per, msk in [("IS", t.index <= IS_END), ("OOS", t.index > IS_END)]:
                nxt = up[run & msk]; base = up[msk].mean()
                if len(nxt) < 20:
                    continue
                p = binomtest(int(nxt.sum()), len(nxt), base).pvalue
                rows.append({"kosul": f"{n} gün {side} sonrası", "donem": per, "n": len(nxt),
                             "ertesi_gun_yukari": nxt.mean(), "taban": base, "p_deger": p})
    tab = pd.DataFrame(rows)
    save(tab.set_index(["kosul", "donem"]), sym, "seri_istatistikleri_YON.csv")
    return {}


def analog_features(t, sym):
    X = feats(t)
    cols = ["r_open", "r_high", "r_low", "r_close", "r_range", "atr14", "rel_range", "gun_tipi", "on_range", "gap", "t_high", "t_low"]
    X.join(t[cols]).to_csv(os.path.join(OUT, sym, "gunluk_ozellikler.csv"), float_format="%.4f")
    # kNN doğrulaması: OOS'ta k=40 benzer günün aralık medyanı vs ATR naif
    Z = X.dropna(); Zs = (Z - Z[Z.index <= IS_END].mean()) / Z[Z.index <= IS_END].std()
    w = np.array([1, 1, 1.5, 1, 0.5, 1.5, 1, 1, 1, 0.3, 0.3])
    y = t.loc[Z.index, "rel_range"].values
    is_idx = np.where(Z.index <= IS_END)[0]; oos_idx = np.where(Z.index > IS_END)[0]
    errs_k, errs_n = [], []
    for i in oos_idx:
        past = np.arange(i)  # yalnız geçmiş günler
        dd = (((Zs.values[past] - Zs.values[i]) ** 2) * w).sum(1)
        nn = past[np.argsort(dd)[:40]]
        errs_k.append(abs(np.log(np.median(y[nn])) - np.log(y[i])))
        errs_n.append(abs(np.log(np.median(y[past])) - np.log(y[i])))
    return {"benzer_gun_kNN40_OOS_log_hata": round(float(np.mean(errs_k)), 4),
            "benzer_gun_naif_OOS_log_hata": round(float(np.mean(errs_n)), 4),
            "benzer_gun_rapora_al": bool(np.mean(errs_k) < np.mean(errs_n)),
            "benzer_gun_agirliklar": dict(zip(FEATS, w.tolist()))}


def spread_profile(sym):
    out = {}
    for fn in [f"F_{sym}_spread_M1.csv.gz", f"{sym}_tickspread_M1.csv.gz"]:
        p = os.path.join(DATA, fn)
        if not os.path.exists(p):
            continue
        s = pd.read_csv(p, parse_dates=["minute_server"])
        s["et"] = s.minute_server - pd.Timedelta(hours=7)
        s["saat_ET"] = s.et.dt.hour
        tab = s.groupby("saat_ET").agg(n=("spr_med", "size"), spread_medyan=("spr_med", "median"),
                                       spread_p90=("spr_q90" if "spr_q90" in s else "spr_p90", "median"),
                                       spread_max=("spr_max", "max"))
        save(tab, sym, f"spread_saatlik_{fn.split('.')[0]}.csv")
        out[fn] = {"gun_sayisi": int(s.minute_server.dt.date.nunique()), "baslangic": str(s.minute_server.min().date()),
                   "bitis": str(s.minute_server.max().date())}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    ev = load_events()
    ev.to_csv(os.path.join(OUT, "olay_takvimi_tarihsel.csv"), index=False)
    for sym in ["US100", "XAUUSD"]:
        d = load(sym)
        t = daily_table(d, ev)
        S = {"veri": {"baslangic": str(t.index.min().date()), "bitis": str(t.index.max().date()), "gun": len(t),
                      "IS_gun": int((t.index <= IS_END).sum()), "OOS_gun": int((t.index > IS_END).sum())},
             "ATR14_RTH_son": round(float(t.r_range.tail(14).mean()), 2),
             "ATR14_tam_gun_son": round(float(t.f_range.tail(14).mean()), 2)}
        S["aralik_modeli"] = range_model(t, sym)
        S["gun_tipi_modeli"] = daytype_model(t, sym)
        S.update(event_reactions(d, ev, t, sym))
        S.update(time_of_day(t, sym))
        S.update(levels(t, sym))
        S.update(sessions(t, sym))
        streaks(t, sym)
        S.update(analog_features(t, sym))
        S["spread_profili"] = spread_profile(sym)
        summary[sym] = S
        print(sym, "tamam", S["veri"])
    summary["lot_formulu"] = {"US100": "lot = risk$ / (stop_puan × 20); 0.01 lot = 0.20$/puan; aşağı yuvarla, min 0.01",
                              "XAUUSD": "lot = risk$ / (stop$ × 100 + 7$ komisyon/lot); 0.01 lot = 1$ / 1$ hareket"}
    with open(os.path.join(OUT, "ozet.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False, default=str)
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str)[:6000])


if __name__ == "__main__":
    main()
