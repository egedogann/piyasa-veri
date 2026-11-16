"""
İstatistik katmanı v2 (istatistik_kur.py çıktısının üstüne).
 A. Gün içi vol profili ve 'kalan hareket' tabloları
 B. Vol rejimi + HAR terimleri ile aralık modeli v2
 C. Stop/hedef (MAE/MFE) olasılık ızgarası — RTH açılışı ve 10:00 ET girişleri
 D. Takvim etkileri: OPEX günü/haftası, ay sonu/ay başı, FOMC öncesi gün, tatil öncesi gün
 E. US100–XAU korelasyonu ve birleşik risk
 F. İma edilen vol (VXN / GVZ) ve cross-asset korelasyon rejimi (data/d1 gerekir)
Kurallar istatistik_kur.py ile aynı: sunucu−7 = ET, IS ≤ 2022, OOS ≥ 2023, look-ahead yok.
Kullanım: python scripts/istatistik_v2.py <ftm_data_klasoru> [repo_koku]
"""
import json, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import istatistik_kur as K  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else K.DATA
ROOT = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K.DATA = DATA
OUT = K.OUT = os.path.join(ROOT, "stats")
D1 = os.path.join(ROOT, "data", "d1")
IS_END = K.IS_END
rng = np.random.default_rng(11)
res = {}


def save(df, sym, name):
    K.save(df, sym, name)


def r2(y, p):
    return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum())


# ------------------------------------------------------------------ A. gün içi profil
def intraday(d, t, sym):
    rth = d[(d["mod"] >= 570) & (d["mod"] < 960)].copy()
    rth = rth[rth.fday.isin(t.index)]
    rth["atr"] = rth.fday.map(t.atr14)
    rth["ret_atr"] = (rth.close - rth.open).abs() / rth.atr
    rth["b30"] = (rth["mod"] // 30) * 30
    prof = rth.groupby("b30").ret_atr.mean()
    prof = (prof / prof.sum()).rename("gun_ici_hareket_payi")
    prof.index = [f"{m//60:02d}:{m%60:02d}" for m in prof.index]
    save(prof.to_frame(), sym, "gun_ici_vol_profili.csv")
    # kalan hareket: kontrol saatinde aralık/ATR dilimi → günün kalanı
    rows = []
    for cp in range(600, 931, 30):
        before = rth[rth["mod"] < cp].groupby("fday").agg(h=("high", "max"), l=("low", "min"))
        full = t.loc[before.index, ["r_high", "r_low", "atr14"]]
        so_far = (before.h - before.l) / full.atr14
        final = (full.r_high - full.r_low) / full.atr14
        new_ext = (full.r_high > before.h) | (full.r_low < before.l)
        ext_add = final - so_far
        b = pd.cut(so_far, [0, 0.3, 0.5, 0.7, 0.9, 1.2, 10], right=False)
        df = pd.DataFrame({"cp": f"{cp//60:02d}:{cp%60:02d}", "dilim": b.astype(str), "ek": ext_add, "yeni_uc": new_ext,
                           "IS": before.index <= IS_END})
        for (dl, isf), g in df.groupby(["dilim", "IS"]):
            rows.append({"saat_ET": df.cp.iloc[0], "aralik_simdiye_ATR": dl, "donem": "IS" if isf else "OOS", "n": len(g),
                         "kalan_ek_aralik_ATR_medyan": g.ek.median(), "kalan_ek_p80": g.ek.quantile(0.8),
                         "yeni_high_veya_low": g.yeni_uc.mean()})
    tab = pd.DataFrame(rows)
    save(tab.set_index(["saat_ET", "aralik_simdiye_ATR", "donem"]), sym, "kalan_hareket.csv")
    # doğrulama: IS medyanı ile OOS tahmini vs naif (max(0, 1 − şimdiye kadar))
    piv = tab.pivot_table(index=["saat_ET", "aralik_simdiye_ATR"], columns="donem", values="kalan_ek_aralik_ATR_medyan")
    return {"kalan_hareket_IS_OOS_medyan_korelasyonu": round(float(piv.dropna().corr().iloc[0, 1]), 3)}


# ------------------------------------------------------------------ B. vol rejimi + HAR
def har(t, sym, extra=None):
    X = K.feats(t).copy()
    lr = np.log(t.r_range)
    X["har_1"] = lr.shift(1) - np.log(t.atr14)
    X["har_5"] = np.log(t.r_range.shift(1).rolling(5).mean() / t.atr14)
    X["har_22"] = np.log(t.r_range.shift(1).rolling(22).mean() / t.atr14)
    if extra is not None:
        X = X.join(extra)
    y = lr
    ok = X.notna().all(axis=1) & np.isfinite(y)
    X, y = X[ok], y[ok]
    isx = X.index <= IS_END
    A = np.c_[np.ones(len(X)), X.values]
    beta, *_ = np.linalg.lstsq(A[isx], y[isx].values, rcond=None)
    p = A @ beta
    resid = y.values - p
    q = np.quantile(resid[isx], [0.1, 0.25, 0.5, 0.75, 0.9])
    # karşılaştırma: v1 özellikleri, aynı örneklem
    cols1 = K.FEATS
    A1 = np.c_[np.ones(len(X)), X[cols1].values]
    b1, *_ = np.linalg.lstsq(A1[isx], y[isx].values, rcond=None)
    oos = ~isx
    cov80 = float(((resid[oos] >= q[0]) & (resid[oos] <= q[4])).mean())
    return {"ozellikler": ["sabit"] + list(X.columns), "katsayilar": dict(zip(["sabit"] + list(X.columns), np.round(beta, 5).tolist())),
            "artik_kantiller_IS": dict(zip(["q10", "q25", "q50", "q75", "q90"], np.round(q, 4).tolist())),
            "R2_OOS": round(r2(y.values[oos], p[oos]), 3), "R2_OOS_v1_ayni_ornek": round(r2(y.values[oos], (A1 @ b1)[oos]), 3),
            "band80_OOS_kapsama": round(cov80, 3), "n_OOS": int(oos.sum()), "baslangic": str(X.index.min().date())}


def vol_regime(t, sym):
    pct = t.atr14.rolling(504, min_periods=250).apply(lambda x: (x[-1] >= x).mean(), raw=True)
    lab = pd.cut(pct, [0, 0.25, 0.75, 0.9, 1.01], labels=["dusuk", "normal", "yuksek", "asiri"], right=False)
    tab = t.assign(rejim=lab).groupby("rejim", observed=True).agg(
        n=("rel_range", "size"), rth_aralik_ATR=("rel_range", "median"),
        trend=("gun_tipi", lambda x: (x == "trend").mean()), denge=("gun_tipi", lambda x: (x == "denge").mean()),
        yukari=("r_close", lambda x: np.nan))
    tab["yukari"] = t.assign(rejim=lab).groupby("rejim", observed=True).apply(lambda x: (x.r_close > x.r_open).mean())
    save(tab, sym, "vol_rejimi.csv")
    pd.DataFrame({"atr14": t.atr14, "atr_persentil_2y": pct, "rejim": lab}).to_csv(os.path.join(OUT, sym, "vol_rejimi_gecmis.csv"), float_format="%.4f")
    return {"rejim_tanimi": "ATR14'ün son 2 yıldaki persentili: <25 düşük, 25–75 normal, 75–90 yüksek, >90 aşırı"}


# ------------------------------------------------------------------ C. MAE/MFE ızgarası
def first_touch(path_h, path_l, entry, up, dn):
    """Long için: +up önce mi −dn önce mi? Aynı barda ikisi → stop (kötü senaryo). 0=hiçbiri."""
    for h, l in zip(path_h, path_l):
        hit_dn = l <= entry - dn
        hit_up = h >= entry + up
        if hit_dn:
            return -1
        if hit_up:
            return 1
    return 0


def mae_mfe(d, t, sym):
    rth = d[(d["mod"] >= 570) & (d["mod"] < 960)]
    grid_tp = [0.25, 0.5, 0.75, 1.0]
    grid_sl = [0.15, 0.25, 0.35, 0.5]
    rows = []
    for start, lbl in [(570, "09:30 açılış"), (600, "10:00")]:
        for day, g in rth[rth["mod"] >= start].groupby("fday"):
            if day not in t.index:
                continue
            a = t.at[day, "atr14"]; e = g.open.iloc[0]
            H, L = g.high.values, g.low.values
            mfe_l, mae_l = (H.max() - e) / a, (e - L.min()) / a
            r = {"gun": day, "giris": lbl, "mfe_long": mfe_l, "mae_long": mae_l}
            for tp in grid_tp:
                for sl in grid_sl:
                    r[f"L_{tp}_{sl}"] = first_touch(H, L, e, tp * a, sl * a)
                    # short: aynasını al
                    r[f"S_{tp}_{sl}"] = first_touch(-L, -H, -e, tp * a, sl * a)
            rows.append(r)
    M = pd.DataFrame(rows).set_index("gun")
    M.to_csv(os.path.join(OUT, sym, "mae_mfe_ham.csv"), float_format="%.3f")
    out = []
    for lbl, g in M.groupby("giris"):
        for side in ("L", "S"):
            for tp in grid_tp:
                for sl in grid_sl:
                    c = g[f"{side}_{tp}_{sl}"]
                    for per, msk in [("tumu", slice(None)), ("OOS", g.index > IS_END)]:
                        cc = c[msk]
                        out.append({"giris": lbl, "yon": "long" if side == "L" else "short", "hedef_ATR": tp, "stop_ATR": sl,
                                    "donem": per, "n": len(cc), "hedef_once": (cc == 1).mean(), "stop_once": (cc == -1).mean(),
                                    "ikisi_de_yok": (cc == 0).mean(),
                                    "basabas_isabet": sl / (tp + sl),
                                    "beklenen_R_brut": ((cc == 1) * tp / sl - (cc == -1)).mean()})
    G = pd.DataFrame(out)
    save(G.set_index(["giris", "yon", "hedef_ATR", "stop_ATR", "donem"]), sym, "stop_hedef_izgarasi.csv")
    q = M.groupby("giris")[["mfe_long", "mae_long"]].quantile([0.25, 0.5, 0.75, 0.9]).unstack()
    save(q, sym, "mfe_mae_dagilimi.csv")
    return {"stop_hedef_not": "Rastgele yönlü giriş; yön bilgisi yok. 'hedef_once' − 'basabas_isabet' farkı ≈ 0 ise o ızgara noktasında edge yok, tablo yalnız stop/hedef mesafesinin vurulma sıklığını gösterir."}


# ------------------------------------------------------------------ D. takvim etkileri
def calendar(t, ev, sym):
    from scipy.stats import ttest_ind
    days = t.index
    cal = pd.DataFrame(index=days)
    # OPEX: ayın 3. cuması (tatilse önceki işlem günü)
    opex = []
    for m in pd.period_range(days.min(), days.max(), freq="M"):
        fr = pd.date_range(m.start_time, m.end_time, freq="W-FRI")
        if len(fr) >= 3:
            f = fr[2]
            while f not in days and f > m.start_time:
                f -= pd.Timedelta(days=1)
            opex.append(f)
    cal["opex_gunu"] = days.isin(opex)
    wk = days.to_period("W")
    cal["opex_haftasi"] = pd.Series(wk, index=days).isin(pd.DatetimeIndex(opex).to_period("W")).values
    s = pd.Series(days, index=days)
    cal["ay_son_gunu"] = s.dt.month != s.shift(-1).dt.month
    cal["ay_ilk_gunu"] = s.dt.month != s.shift(1).dt.month
    fomc_days = set(ev.loc[ev.key == "fomc", "et"].dt.normalize())
    cal["fomc_oncesi_gun"] = pd.Series(days, index=days).shift(-1).isin(fomc_days).values
    gapdays = (s.shift(-1) - s).dt.days
    cal["tatil_oncesi"] = (gapdays > 1) & (s.dt.dayofweek < 4) | ((gapdays > 3) & (s.dt.dayofweek == 4))
    ret_atr = (t.r_close - t.r_open) / t.atr14
    rows = []
    for c in cal.columns:
        m = cal[c].values.astype(bool)
        for per, pm in [("IS", days <= IS_END), ("OOS", days > IS_END)]:
            a, b = t.rel_range[m & pm], t.rel_range[~m & pm & (t.ev_major == 0)]
            ra, rb = ret_atr[m & pm], ret_atr[~m & pm]
            if len(a) < 10:
                continue
            rows.append({"etki": c, "donem": per, "n": len(a), "aralik_ATR_medyan": a.median(), "olaysiz_diger_medyan": b.median(),
                         "aralik_p": ttest_ind(np.log(a), np.log(b), equal_var=False).pvalue,
                         "getiri_ATR_ort": ra.mean(), "diger_getiri_ATR_ort": rb.mean(),
                         "getiri_p": ttest_ind(ra, rb, equal_var=False).pvalue})
    tab = pd.DataFrame(rows)
    save(tab.set_index(["etki", "donem"]), sym, "takvim_etkileri.csv")
    # her iki dönemde aynı işaretli ve p<0.1 olanlar
    keep = []
    for c, g in tab.groupby("etki"):
        if len(g) == 2 and (g.aralik_p < 0.1).all() and np.sign(g.aralik_ATR_medyan - g.olaysiz_diger_medyan).nunique() == 1:
            keep.append(c)
    cal.astype(int).to_csv(os.path.join(OUT, sym, "takvim_bayraklari.csv"))
    return {"takvim_aralik_etkisi_IS_ve_OOS_tutarli": keep}, cal


# ------------------------------------------------------------------ E. korelasyon / birleşik risk
def correlation(tabs, dmap):
    a, b = tabs["US100"], tabs["XAUUSD"]
    ra = ((a.r_close - a.r_open) / a.atr14).rename("US100")
    rb = ((b.r_close - b.r_open) / b.atr14).rename("XAU")
    j = pd.concat([ra, rb], axis=1).dropna()
    roll = j.US100.rolling(60).corr(j.XAU)
    reg = pd.read_csv(os.path.join(OUT, "US100", "vol_rejimi_gecmis.csv"), index_col=0, parse_dates=True).rejim
    jr = j.join(reg)
    by = jr.groupby("rejim").apply(lambda x: x.US100.corr(x.XAU))
    # 1R + 1R (stop = 0.25 ATR varsayımı yerine getiri/ATR ile ölçek): birleşik günlük std / tekil toplam
    comb = (j.US100 + j.XAU).std() / (j.US100.std() + j.XAU.std())
    same_bad = ((j.US100 < -0.5) & (j.XAU < -0.5)).mean()
    # 5 dk RTH getirileri
    da, db = dmap["US100"], dmap["XAUUSD"]
    ma = da[(da["mod"] >= 570) & (da["mod"] < 960)].close.pct_change()
    mb = db[(db["mod"] >= 570) & (db["mod"] < 960)].close.pct_change()
    m5 = pd.concat([ma, mb], axis=1, join="inner").dropna()
    out = {"RTH_getiri_korelasyonu_tumu": round(float(j.US100.corr(j.XAU)), 3),
           "IS": round(float(j[j.index <= IS_END].corr().iloc[0, 1]), 3), "OOS": round(float(j[j.index > IS_END].corr().iloc[0, 1]), 3),
           "rolling60_p10_p50_p90": [round(float(x), 3) for x in roll.quantile([0.1, 0.5, 0.9])],
           "rolling60_son": round(float(roll.iloc[-1]), 3),
           "vol_rejimine_gore": {str(k): round(float(v), 3) for k, v in by.items()},
           "M5_RTH_korelasyon": round(float(m5.corr().iloc[0, 1]), 3),
           "birlesik_std_orani": round(float(comb), 3),
           "ikisi_birden_-0.5ATR_gunu": round(float(same_bad), 4),
           "yorum": "birlesik_std_orani ≈ 0.71 → bağımsız; 1.0 → tam korelasyon. Aynı gün iki enstrümanda eşit risk ≈ tek işlemin bu oranla çarpılmış 2 katı risk."}
    pd.DataFrame({"rolling60_korelasyon": roll}).to_csv(os.path.join(OUT, "korelasyon_US100_XAU.csv"), float_format="%.4f")
    return out


# ------------------------------------------------------------------ F. ima edilen vol + cross-asset
def d1(name):
    p = os.path.join(D1, K_safe(name) + ".csv")
    if not os.path.exists(p):
        return None
    x = pd.read_csv(p, index_col=0, parse_dates=True)
    # Yahoo günlük bar etiketi = seans tarihi (UTC 00:00 olarak saklanıyor); saat dilimi çevrilmez
    x.index = pd.to_datetime(x.index, utc=True).tz_localize(None).normalize()
    return x[~x.index.duplicated(keep="last")]


def K_safe(name):
    return name.replace("^", "IDX_").replace("=", "_").replace(".", "_").replace("-", "_")


def implied(t, sym, idx_name):
    v = d1(idx_name)
    if v is None or len(v) < 500:
        return {"durum": f"{idx_name} verisi yok/yetersiz"}
    iv = v.close.shift(0)  # endeks kapanışı t günü 16:15 ET; bir sonraki RTH için kullanılır
    # t günü için bilinen: önceki işlem gününün kapanışı
    iv_prev = iv.reindex(t.index, method="ffill").shift(1)
    imp_move = iv_prev / 100 / np.sqrt(252) * t.r_open.shift(0)  # beklenen günlük 1σ hareket (puan)
    extra = pd.DataFrame({"l_imp": np.log(imp_move / t.atr14)}, index=t.index)
    m = har(t, sym, extra)
    m["kaynak"] = idx_name
    m["kullanim"] = "l_imp = log((önceki kapanış endeks/100/√252 × fiyat) / ATR14)"
    m["ilk_tarih"] = str(v.index.min().date())
    return m


def cross_asset(tabs):
    out = {}
    pairs = {"XAU": [("DX-Y.NYB", "DXY"), ("^TNX", "ABD10Y"), ("TIP", "TIPS_ETF"), ("^SPX", "SPX")],
             "US100": [("^TNX", "ABD10Y"), ("DX-Y.NYB", "DXY"), ("^VIX", "VIX")]}
    for sym, lst in pairs.items():
        t = tabs["XAUUSD" if sym == "XAU" else "US100"]
        r = np.log(t.f_close).diff()
        rows = {}
        for nm, lab in lst:
            x = d1(nm)
            if x is None:
                continue
            xr = (x.close.diff() if nm == "^TNX" else np.log(x.close).diff()).rename(lab)
            j = pd.concat([r.rename(sym), xr], axis=1, join="inner").dropna()
            roll = j[sym].rolling(60).corr(j[lab])
            rows[lab] = {"tum": round(float(j.corr().iloc[0, 1]), 3), "son60": round(float(roll.iloc[-1]), 3) if len(roll.dropna()) else None,
                         "p10_p90_60g": [round(float(q), 3) for q in roll.quantile([0.1, 0.9])], "n": len(j)}
        out[sym] = rows
    return out


def main():
    ev = K.load_events()
    tabs, dmap = {}, {}
    for sym in ["US100", "XAUUSD"]:
        d = K.load(sym); t = K.daily_table(d, ev)
        tabs[sym], dmap[sym] = t, d
        S = {}
        S.update(intraday(d, t, sym))
        S["aralik_modeli_v2_HAR"] = har(t, sym)
        S.update(vol_regime(t, sym))
        S.update(mae_mfe(d, t, sym))
        c, _ = calendar(t, ev, sym)
        S.update(c)
        S["ima_edilen_vol_modeli"] = implied(t, sym, "^VXN" if sym == "US100" else "^GVZ")
        res[sym] = S
        print(sym, json.dumps({k: v for k, v in S.items() if k != "aralik_modeli_v2_HAR"}, ensure_ascii=False, default=str)[:1500])
    res["korelasyon_US100_XAU"] = correlation(tabs, dmap)
    res["cross_asset_korelasyon"] = cross_asset(tabs)
    p = os.path.join(OUT, "ozet.json")
    S0 = json.load(open(p, encoding="utf-8"))
    S0["v2"] = res
    S0["v2_olusturma"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    json.dump(S0, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
    print(json.dumps({k: res[k] for k in ["korelasyon_US100_XAU", "cross_asset_korelasyon"]}, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
