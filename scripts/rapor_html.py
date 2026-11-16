"""Günlük masa notu — HTML üretici. Girdi: rapor/veri.json, rapor/haber.json, stats/, rapor/logo.png → rapor/index.html"""
import base64, html, json, os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R, ST = os.path.join(ROOT, "rapor"), os.path.join(ROOT, "stats")
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
e = html.escape


def fp(v, dec=1):
    return "—" if v is None else f"{v:.{dec}f}"


def fs(v, dec=1, unit=""):
    if v is None:
        return "—"
    cls = "up" if v > 0 else "dn" if v < 0 else ""
    return f'<span class="{cls}">{v:+.{dec}f}{unit}</span>'


def pc(v, dec=0):
    return "—" if v is None else f"%{v * 100:.{dec}f}"


def tag(kind):
    lab = {"model": "Model", "bilgi": "Bilgi", "zayif": "Zayıf model", "yon": "Yön bilgisi yok", "on": "Ön tahmin", "risk": "Risk"}[kind]
    return f'<span class="tag tag-{kind}">{lab}</span>'


def table(head, rows, cls="", foot=None):
    h = "".join(f"<th{' class=num' if a else ''}>{t}</th>" for t, a in head)
    b = ""
    for r in rows:
        rc = ""
        if isinstance(r, dict):
            rc, r = f' class="{r["cls"]}"', r["cells"]
        b += f"<tr{rc}>" + "".join(f"<td{' class=num' if head[i][1] else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
    f = f"<caption>{foot}</caption>" if foot else ""
    return f'<div class="tw"><table class="{cls}">{f}<thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def range_bar(a, atr, imp, dec):
    """%80 / %50 bant çubuğu: q10–q90 ince, q25–q75 kalın, medyan çentik; ATR ve ima edilen 1σ işaretleri."""
    hi = max(a["q90"], atr, imp) * 1.08
    X = lambda v: 8 + v / hi * 584
    s = f'<svg class="rb" viewBox="0 0 600 64" role="img" aria-label="Beklenen RTH aralığı: yüzde 80 bant {a["q10"]:.{dec}f} ile {a["q90"]:.{dec}f} arası, medyan {a["q50"]:.{dec}f}">'
    s += f'<line x1="8" x2="592" y1="30" y2="30" class="rb-axis"/>'
    s += f'<rect x="{X(a["q10"]):.1f}" y="27" width="{X(a["q90"]) - X(a["q10"]):.1f}" height="6" class="rb-80"/>'
    s += f'<rect x="{X(a["q25"]):.1f}" y="22" width="{X(a["q75"]) - X(a["q25"]):.1f}" height="16" class="rb-50"/>'
    s += f'<line x1="{X(a["q50"]):.1f}" x2="{X(a["q50"]):.1f}" y1="18" y2="42" class="rb-med"/>'
    for k, anchor in (("q10", "middle"), ("q50", "middle"), ("q90", "middle")):
        s += f'<text x="{X(a[k]):.1f}" y="13" text-anchor="{anchor}" class="rb-t">{a[k]:.{dec}f}</text>'
    mk = sorted(((atr, "ATR14"), (imp, "ima 1σ")))
    close = X(mk[1][0]) - X(mk[0][0]) < 110
    for j, (v, lab) in enumerate(mk):
        anc, dx = (("end", -4) if j == 0 else ("start", 4)) if close else ("middle", 0)
        s += f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="38" y2="50" class="rb-mk"/><text x="{X(v) + dx:.1f}" y="60" text-anchor="{anc}" class="rb-s">{lab} {v:.{dec}f}</text>'
    return s + "</svg>"


def chart(p, dec):
    g = p["grafik"]; c = g["c"]; n = len(c); atr = p["atr14_rth"]
    W, H, ml, mr, mt, mb = 600, 310, 6, 156, 12, 24
    lo, hi = min(c), max(c); pad = (hi - lo) * 0.06
    order = ["Önceki gün high (FTM günü)", "Önceki gün low (FTM günü)", "Önceki RTH kapanış", "Gece high (şimdiye kadar)",
             "Gece low (şimdiye kadar)", "5 gün POC", "Geçen hafta high", "Geçen hafta low"]
    by = {l["ad"]: l for l in p["seviyeler"]}
    lv = []
    for nm in order:
        l = by.get(nm)
        if l and lo - pad * 3 <= l["fiyat"] <= hi + pad * 3 and all(abs(l["fiyat"] - m["fiyat"]) > 0.05 * atr for m in lv):
            lv.append(l)
    lv = lv[:6]
    lo, hi = min([lo] + [l["fiyat"] for l in lv]) - pad, max([hi] + [l["fiyat"] for l in lv]) + pad
    X = lambda i: ml + i / (n - 1) * (W - ml - mr)
    Y = lambda v: mt + (hi - v) / (hi - lo) * (H - mt - mb)
    s = f'<svg class="ch" viewBox="0 0 {W} {H}" role="img" aria-label="{p["sembol"]} son beş gün 5 dakikalık kapanış ve seviyeler" data-c=\'{json.dumps(c)}\' data-t=\'{json.dumps(g["t"])}\' data-g="{ml},{W - mr},{mt},{H - mb},{lo},{hi}">'
    prev = None
    for i, d in enumerate(g["gun"]):
        if d != prev:
            x = X(i)
            if prev is not None:
                s += f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{mt}" y2="{H - mb}" class="ch-day"/>'
            s += f'<text x="{x + 3:.1f}" y="{H - 8}" class="ch-s">{d[8:10]}.{d[5:7]}</text>'
            prev = d
    labs = sorted(lv, key=lambda l: -l["fiyat"])
    ys = [Y(l["fiyat"]) + 4 for l in labs]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + 13)
    if ys and ys[-1] > H - mb:
        ys[-1] = H - mb
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - 13)
    for l, ty in zip(labs, ys):
        y = Y(l["fiyat"])
        s += f'<line x1="{ml}" x2="{W - mr}" y1="{y:.1f}" y2="{y:.1f}" class="ch-lv"/><line x1="{W - mr}" x2="{W - mr + 6}" y1="{y:.1f}" y2="{ty - 4:.1f}" class="ch-lv"/>'
        short = (l["ad"].replace("Önceki gün", "Ö. gün").replace("Önceki RTH", "Ö. RTH").replace("Geçen hafta", "G. hafta")
                 .replace(" (FTM günü)", "").replace(" (şimdiye kadar)", ""))
        s += f'<text x="{W - mr + 9}" y="{ty:.1f}" class="ch-s"><tspan class="ch-b">{l["fiyat"]:.{dec}f}</tspan> {e(short)}</text>'
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(c))
    s += f'<polyline points="{pts}" class="ch-line"/>'
    s += f'<circle cx="{X(n - 1):.1f}" cy="{Y(c[-1]):.1f}" r="3.5" class="ch-dot"/>'
    s += '<line class="ch-x" x1="0" x2="0" y1="0" y2="0" visibility="hidden"/><circle class="ch-h" r="3" visibility="hidden"/>'
    return f'<figure class="fig">{s}</svg><div class="ch-tip" hidden></div><figcaption>Son 4 FTM günü ve bugün, 5 dk kapanış (FTM tahmini). Dikey çizgiler 18:00 ET gün başlangıcı. Üzerinde gezdirince saat (ET) ve fiyat.</figcaption></figure>'


def panel(p, V, S):
    sym = p["sembol"]; dec = 1 if sym == "US100" else 2; u = "puan" if sym == "US100" else "$"
    a = p["aralik"]; A = a["ana"]; atr = p["atr14_rth"]; of = p["ofset"]; g = p["gece"]; im = p["ima"]; vr = p["vol_rejimi"]
    on_tag = tag("on") if "dar_gece" in a else tag("model")
    kp = [("FTM tahmini fiyat", fp(p["fiyat"], dec), f'kaynak {fp(of["kaynak_fiyat"], dec)} {fs(of["deger"], dec)} ofset'),
          ("Önceki RTH kapanışına göre", fs(p["degisim_onceki_rth_kapanis"], dec) + f' <small>({fs(p["degisim_yuzde"], 2, "%")})</small>', f'kapanış {fp(p["onceki"]["r_close"], dec)}'),
          ("Gece aralığı (şimdiye kadar)", fp(g["aralik"], dec), f'{g["aralik"] / atr:.2f} ATR · {fp(g["low"], dec)} – {fp(g["high"], dec)}'),
          ("ATR14 (RTH)", fp(atr, dec), f'rejim: <b>{vr["etiket"]}</b> · 2 yıllık persentil {pc(vr["atr_persentil_2y"])}'),
          ("Beklenen RTH aralığı, %50", f'{fp(A["q25"], 0 if sym == "US100" else 1)} – {fp(A["q75"], 0 if sym == "US100" else 1)}', f'medyan {fp(A["q50"], 0 if sym == "US100" else 1)} {u}'),
          (f'İma edilen günlük 1σ ({im["endeks"]} {im["deger"]:.1f})', fp(im["gunluk_1sigma"], 0 if sym == "US100" else 1), f'{im["gunluk_1sigma_atr"]:.2f} ATR')]
    k = "".join(f'<div class="kpi"><div class="kl">{l}</div><div class="kv">{v}</div><div class="ks">{s}</div></div>' for l, v, s in kp)
    # seviyeler
    rows, placed = [], False
    for l in p["seviyeler"]:
        if not placed and l["fiyat"] < p["fiyat"]:
            rows.append({"cls": "now", "cells": ["Fiyat (FTM tahmini)", fp(p["fiyat"], dec), "", ""]}); placed = True
        if abs(l["uzaklik_atr"]) > 2.2:
            continue
        rows.append([e(l["ad"]) + (f' <small>{e(l["not"])}</small>' if l["not"] else ""), fp(l["fiyat"], dec), fs(l["uzaklik"], dec), f'{l["uzaklik_atr"]:+.2f}'])
    lev = table([("Seviye", 0), ("FTM tahmini", 1), (f"Uzaklık ({u})", 1), ("ATR", 1)], rows, "lev",
                "Seviyeler ±2.2 ATR içinde. POC / VAH / VAL vadeli kontratın gerçek hacminden; VWAP gerçek hacimli.")
    # aralık senaryoları
    d0 = 0 if sym == "US100" else 1
    if "dar_gece" in a:
        gv = a["gece_aralik_varsayim_atr"]
        sc = table([("Gece aralığı senaryosu", 0), ("%80 bant", 1), ("%50 bant", 1), ("Medyan", 1)],
                   [[f'Dar ({gv["dar"]:.2f} ATR)', f'{fp(a["dar_gece"]["q10"], d0)} – {fp(a["dar_gece"]["q90"], d0)}', f'{fp(a["dar_gece"]["q25"], d0)} – {fp(a["dar_gece"]["q75"], d0)}', fp(a["dar_gece"]["q50"], d0)],
                    {"cls": "now", "cells": [f'Medyan ({gv["medyan"]:.2f} ATR)', f'{fp(A["q10"], d0)} – {fp(A["q90"], d0)}', f'{fp(A["q25"], d0)} – {fp(A["q75"], d0)}', fp(A["q50"], d0)]},
                    [f'Geniş ({gv["genis"]:.2f} ATR)', f'{fp(a["genis_gece"]["q10"], d0)} – {fp(a["genis_gece"]["q90"], d0)}', f'{fp(a["genis_gece"]["q25"], d0)} – {fp(a["genis_gece"]["q75"], d0)}', fp(a["genis_gece"]["q50"], d0)]],
                   foot=f'Gece seansı sürüyor (şimdiye kadar {a["gece_simdiye_kadar_atr"]:.2f} ATR). NY öncesi baskıda tek satıra iner.')
    else:
        sc = ""
    gt = p["gun_tipi"]; b = gt["taban"]; bz = p["benzer"]; ac = p["acilis"]; gp = p.get("gap"); o = p["or15"]
    konum = {"icinde": "önceki günün aralığı içinde", "ustte": "önceki gün high'ının üstünde", "altta": "önceki gün low'unun altında"}[ac["konum"]]
    st = [f'<li>{tag("bilgi")} <b>Gün tipi taban oranları:</b> trend {pc(b["trend"])}, denge {pc(b["denge"])}, dönüş {pc(b["donus"])}. Trend günü olasılığı taban orandan iyi tahmin edilemiyor; günlük olasılık verilmez.</li>']
    if "denge" in gt["model_gecerli_siniflar"]:
        st.append(f'<li>{tag("on") if "dar_gece" in a else tag("model")} <b>Denge günü olasılığı:</b> {pc(gt["model_olasilik"]["denge"])} (taban {pc(b["denge"])}). Bu enstrümanda testten geçen tek gün tipi modeli.</li>')
    st.append(f'<li>{tag("bilgi")} <b>Şu anki konum:</b> fiyat {konum}. Geçmişte bu konumda RTH: önceki gün high kırılır {pc(ac["PDH_RTH_kirilir"])}, low kırılır {pc(ac["PDL_RTH_kirilir"])}; gece high {pc(ac["ONH_kirilir"])}, gece low {pc(ac["ONL_kirilir"])} (n={ac["n"]:.0f}).</li>')
    if gp:
        st.append(f'<li>{tag("bilgi")} <b>Gap göstergesi:</b> {fs(gp["puan"], dec)} {u} ({gp["atr"]:+.2f} ATR). Bu büyüklükte gap RTH içinde {pc(gp["kapanma"])} kapanmış; kapanışın gap yönünde olması {pc(gp["gap_yonunde_kapanis"])} (n={gp["n"]}). {tag("yon")}</li>')
    st.append(f'<li>{tag("bilgi")} <b>Açılış aralığı (ilk 15 dk):</b> tipik {o["OR15_aralik_ATR_medyan"] * atr:.{d0}f} {u} ({o["OR15_aralik_ATR_medyan"]:.2f} ATR). Üstü kırılır {pc(o["OR15_yukari_kirilir"])}, altı {pc(o["OR15_asagi_kirilir"])}, ikisi {pc(o["OR15_iki_yon_kirilir"])}. Günün high veya low\'u ilk 30 dk\'da: {pc(o["rth_ilk30dk_high_veya_low_olusturma"])}.</li>')
    q = bz["rth_aralik_atr_p25_p50_p75"]
    st.append(f'<li>{tag("zayif")} <b>Benzer 40 gün</b>{"" if bz["gece_dahil"] else " (gece aralığı hariç eşleşme)"}: RTH aralığı medyan {q[1] * atr:.{d0}f} {u} ({q[0]:.2f}–{q[2]:.2f} ATR çeyrekler arası); trend {pc(bz["trend"])}, denge {pc(bz["denge"])}. En yakın: {", ".join(bz["en_yakin"][:3])}.</li>')
    lot = table([("Stop", 0), (f"Mesafe ({u})", 1), ("25 $ risk: lot", 1), ("gerçek $", 1), ("50 $ risk: lot", 1), ("gerçek $", 1)],
                [[f'{r["stop_atr"]:.2f} ATR', fp(r["stop"], dec),
                  f'{r["lot_25"]:.2f}' if r["lot_25"] > 0 else '<span class="flag">sığmaz</span>', fp(r["gercek_25"], 1) if r["lot_25"] > 0 else f'min {fp(r["min_lot_risk"], 1)}',
                  f'{r["lot_50"]:.2f}' if r["lot_50"] > 0 else '<span class="flag">sığmaz</span>', fp(r["gercek_50"], 1) if r["lot_50"] > 0 else f'min {fp(r["min_lot_risk"], 1)}'] for r in p["lot"]], "lot",
                foot=("0.01 lot = 0.20 $/puan, komisyon yok." if sym == "US100" else "0.01 lot = 1 $ / 1 $ hareket, komisyon 7 $/lot dahil.") + " Lot aşağı yuvarlanır. FTM günlük limit 200 $.")
    if sym == "US100":
        ofn = (f'<b>Ofset {of["deger"]:+.1f} puan.</b> Yöntem: {e(of["yontem"])}; son RTH bazı {of["baz_son_rth"]:+.1f} ({of["baz_tarihi"]}), vadeye {of["vadeye_gun"]} gün ({of["vade"]}). '
               f'Hata bütçesi: {e(of["hata_butcesi"])}.' + (' <span class="flag">Rollover haftası: seviyeleri MT5\'te teyit et.</span>' if of["rollover_yakin"] else ""))
    else:
        ofn = (f'<b>Ofset {of["deger"]:+.2f} $ ({e(of["uyari"])}).</b> Yöntem: {e(of["yontem"])}; son ölçüm {of["son_olcum"]} (yaş {of["yas_gun"]} gün). Hata bütçesi: {e(of["hata_butcesi"])}. Spot kaynak henüz yok.')
    return f'''
<section class="panel" id="{sym.lower()}">
 <div class="ph"><h3>{sym}</h3><span class="pm">FTM tahmini · son bar {pd.Timestamp(p["fiyat_zamani_utc"]).tz_convert("Europe/Istanbul"):%H:%M} TR · önceki gün {p["onceki_gun"]}</span></div>
 <div class="kpis">{k}</div>
 <div class="two">
  <div>
   <h4>Beklenen RTH aralığı (09:30–16:00 ET) {on_tag}</h4>
   {range_bar(A, atr, im["gunluk_1sigma"], d0)}
   <p class="note">İnce çubuk %80, kalın çubuk %50 bant, çentik medyan ({u}). Model test döneminde R² {a["model_R2_OOS"]:.2f}; %80 bant günlerin {pc(a["kapsama_80_OOS"])}'ini kapsadı. Yön içermez.</p>
   {sc}
   {chart(p, dec)}
   <h4>Bugünün istatistikleri</h4><ul class="stats">{"".join(st)}</ul>
  </div>
  <div>
   <h4>Seviyeler</h4>
   {lev}
   <h4>Lot tablosu</h4>{lot}<p class="note">{ofn}</p>
  </div>
 </div>
</section>'''


def main():
    V = json.load(open(os.path.join(R, "veri.json"), encoding="utf-8"))
    N = json.load(open(os.path.join(R, "haber.json"), encoding="utf-8"))
    S = json.load(open(os.path.join(ST, "ozet.json"), encoding="utf-8"))
    logo = base64.b64encode(open(os.path.join(R, "logo.png"), "rb").read()).decode()
    now = pd.Timestamp(V["uretim_utc"]).tz_convert("Europe/Istanbul")
    bar = pd.Timestamp(V["veri_son_bar_utc"]).tz_convert("Europe/Istanbul")
    U, G = V["US100"], V["XAUUSD"]
    day = pd.Timestamp(U["bugun"])
    title = f"Masa Notu {day.day} {AY[day.month - 1]} {day.year}"
    # ---------- I. Bugün
    oz = "".join(f"<li>{e(x)}</li>" for x in N["ozet"])
    auto = (f'<li>US100 vol rejimi <b>{U["vol_rejimi"]["etiket"]}</b>: ATR14 {U["atr14_rth"]:.0f} puan (20 gün önce {U["vol_rejimi"]["atr_20g_once"]:.0f}). '
            f'Beklenen RTH aralığı %80 olasılıkla {U["aralik"]["ana"]["q10"]:.0f}–{U["aralik"]["ana"]["q90"]:.0f} puan. Stop mesafeleri ve lot buna göre küçülür.</li>')
    cal = table([("TR", 0), ("ET", 0), ("Olay", 0), ("Beklenti", 1), ("Önceki", 1), ("Önem", 0), ("Kaynak", 0)],
                [{"cls": "hi" if x["onem"] == "yüksek" else "", "cells": [x["tr"], x["et"], e(x["olay"]) + (f' <small>{e(x["not"])}</small>' if x["not"] else ""), x["beklenti"], x["onceki"],
                  f'<span class="imp imp-{ {"yüksek": "h", "orta": "m", "düşük": "l"}[x["onem"]] }">{x["onem"]}</span>', f'<a href="{x["url"]}">{e(x["kaynak"])}</a>']} for x in N["takvim_bugun"]], "cal")
    wk = table([("Gün", 0), ("Durum", 0), ("Olaylar (saatler TR)", 0)],
               [{"cls": "now" if i == 0 else "", "cells": [x["gun"], f'<span class="pill pill-{ {"Normal": "n", "Veri günü": "d", "Olay riski": "r", "OPEX": "o"}[x["etiket"]] }">{x["etiket"]}</span>', e(x["olaylar"])]} for i, x in enumerate(N["takvim_hafta"])], "wk",
               e(N["takvim_notu"]))
    hl = "".join(f'<article class="hl"><div class="hl-h"><span class="hl-e">{e(x["etki"])}</span><h4>{e(x["baslik"])}</h4></div><p>{e(x["ozet"])} <a href="{x["url"]}">{e(x["kaynak"])}</a></p></article>' for x in N["basliklar"])
    # pano (iki sütun)
    def pano_tab(groups, foot=None):
        prow = []
        for grp in groups:
            prow.append({"cls": "grp", "cells": [grp["grup"], "", "", "", "", ""]})
            for r in grp["satirlar"]:
                sg = r["sigma"]; big = sg is not None and abs(sg) >= 2
                dec = 4 if r["kod"] == "EURUSD=X" else 2 if r["son"] < 1000 else 0
                bp = r["birim"] == "bp"
                prow.append({"cls": "big" if big else "", "cells": [e(r["ad"]), fp(r["son"], dec), fs(r["d1"], 1 if bp else 2, " bp" if bp else "%"),
                             (f'<b>{sg:+.1f}</b>' if big else f'{sg:+.1f}') if sg is not None else "—",
                             fs(r["d5"], 1 if bp else 2, " bp" if bp else "%"), fs(r["y20"], 0 if bp else 1, " bp" if bp else "%")]})
        return table([("Varlık", 0), ("Son", 1), ("1 gün", 1), ("Sigma", 1), ("5 gün", 1), ("20 gün", 1)], prow, "pano", foot)
    pano = (f'<div class="two"><div>{pano_tab(V["pano"][:3])}</div><div>{pano_tab(V["pano"][3:])}</div></div>'
            f'<p class="note">Günlük kapanışlar, {V["pano_tarih"]}. Sigma: 1 günlük değişim ÷ önceki 60 günün standart sapması; |sigma| ≥ 2 koyu. '
            f'Vadelilerin şu anki durumu için enstrüman panellerine bak.</p>')
    # ---------- II. Bağlam
    v = V["vol"]
    volt = table([("Gösterge", 0), ("Değer", 1), ("2 yıllık persentil", 1), ("Okuma", 0)],
                 [["VIX", fp(v["vix"], 1), pc(v["vix_p"]), f'VIX / VIX3M {v["vix_vix3m"]:.2f}: {"contango (normal yapı)" if v["vix_vix3m"] < 1 else "backwardation (stres)"}'],
                  ["VXN (Nasdaq vol)", fp(v["vxn"], 1), pc(v["vxn_p"]), f'günlük 1σ ≈ {U["ima"]["gunluk_1sigma"]:.0f} puan'],
                  ["NDX gerçekleşen vol, 10 / 20 gün", f'{v["ndx_rv10"]:.1f} / {v["ndx_rv20"]:.1f}', "", f'VXN − RV20 = {v["vxn_eksi_rv20"]:+.1f}: {"opsiyonlar gerçekleşenden düşük vol fiyatlıyor" if v["vxn_eksi_rv20"] < 0 else "opsiyon primi gerçekleşenin üstünde"}'],
                  ["GVZ (altın vol)", fp(v["gvz"], 1), pc(v["gvz_p"]), f'günlük 1σ ≈ {G["ima"]["gunluk_1sigma"]:.0f} $'],
                  ["Altın gerçekleşen vol, 10 / 20 gün", f'{v["altin_rv10"]:.1f} / {v["altin_rv20"]:.1f}', "", f'GVZ − RV20 = {v["gvz_eksi_rv20"]:+.1f}'],
                  ["MOVE (tahvil vol)", fp(v["move"], 1), pc(v["move_p"]), "faiz oynaklığı"]],
                 foot=f'Kapanış {v["tarih"]}. Gerçekleşen vol: günlük log getiri, yıllıklandırılmış. Dealer gamma ve 0DTE verisi bu baskıda yok.')
    c = V["korelasyon"]
    cort = table([("Çift", 0), ("20 gün", 1), ("60 gün", 1), ("Tüm dönem", 1), ("60g tarihî %10–%90", 1)],
                 [[x["cift"], f'{x["g20"]:+.2f}', f'{x["g60"]:+.2f}', f'{x["tum"]:+.2f}', f'{x["p10_p90"][0]:+.2f} … {x["p10_p90"][1]:+.2f}'] for x in c["ciftler"]],
                 foot=f'Günlük getiri korelasyonu. {tag("risk")} US100 ve XAU aynı gün eşit riskle: birleşik risk tek işlemin ~{2 * c["birlesik_std_orani"]:.1f} katı; ikisinin aynı gün −0.5 ATR\'den kötü kapanması {pc(c["ikisi_birden_kotu"], 1)}.')
    post = table([("Gösterge", 0), ("Değer", 1), ("Değişim", 0), ("Tarih", 0), ("Kaynak", 0)],
                 [[e(x["ad"]), e(x["deger"]), e(x["degisim"]), e(x["tarih"]), f'<a href="{x["url"]}">{e(x["kaynak"])}</a>'] for x in N["pozisyon"]], foot=e(N["pozisyon_notu"]))
    # ---------- III. Referans
    def rd(sym, f, **k):
        return pd.read_csv(os.path.join(ST, sym, f), **k)
    hl_u, hl_g = rd("US100", "rth_high_low_olusma_olasiligi.csv"), rd("XAUUSD", "rth_high_low_olusma_olasiligi.csv")
    tr_of = lambda s: f'{(int(s[:2]) + 8) % 24:02d}:{s[3:]}'
    hlt = table([("ET", 0), ("TR", 0), ("US100 high", 1), ("low", 1), ("ikisi", 1), ("XAU high", 1), ("low", 1), ("ikisi", 1)],
                [[a.saat_ET, tr_of(a.saat_ET), pc(a.high_olusmus), pc(a.low_olusmus), pc(a.ikisi_olusmus), pc(b.high_olusmus), pc(b.low_olusmus), pc(b.ikisi_olusmus)]
                 for a, b in zip(hl_u.itertuples(), hl_g.itertuples()) if a.saat_ET != "16:00"],
                foot="RTH high / low'unun o saate kadar oluşmuş olma olasılığı (2017–2026).")
    kh = rd("US100", "kalan_hareket.csv"); kh = kh[(kh.donem == "OOS") & kh.saat_ET.isin(["10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]) & (kh.n >= 30)]
    atr = U["atr14_rth"]
    kht = table([("ET", 0), ("TR", 0), ("Aralık şimdiye kadar", 0), ("n", 1), ("Kalan ek aralık, medyan", 1), ("%80'e kadar", 1), ("Yeni high/low", 1)],
                [[r.saat_ET, tr_of(r.saat_ET), (r.aralik_simdiye_ATR.replace("[", "").replace(")", "").replace(", ", "–") + " ATR").replace("1.2–10.0", "1.2+"), r.n,
                  f'{r.kalan_ek_aralik_ATR_medyan:.2f} ATR ≈ {r.kalan_ek_aralik_ATR_medyan * atr:.0f}', f'{r.kalan_ek_p80:.2f} ATR ≈ {r.kalan_ek_p80 * atr:.0f}', pc(r.yeni_high_veya_low)] for r in kh.itertuples()],
                foot=f'{tag("model")} US100, test dönemi 2023+. Puan karşılığı bugünkü ATR ({atr:.0f}) ile. Gün içinde "daha ne kadar hareket kalır" sorusu için.')
    gd = rd("US100", "gece_araligi_dilimleri.csv")
    gdt = table([("Gece aralığı dilimi", 0), ("n", 1), ("RTH aralığı / ATR", 1), ("Trend", 1), ("Denge", 1), ("Dönüş", 1)],
                [[r.on_dilim, r.n, f"{r.rth_aralik_ATR_medyan:.2f}", pc(r.trend), pc(r.denge), pc(r.donus)] for r in gd.itertuples()],
                foot=f'{tag("bilgi")} US100. Gece (18:00–09:29 ET) aralığının ATR\'ye oranına göre beşte birlik dilimler.')
    sp = rd("US100", "spread_saatlik_US100_tickspread_M1.csv")
    spt = table([("Saat ET", 0), ("TR", 0), ("Spread medyan (puan)", 1), ("Maks", 1)],
                [[f"{int(r.saat_ET):02d}:00", f"{(int(r.saat_ET) + 8) % 24:02d}:00", f"{r.spread_medyan:.1f}", f"{r.spread_max:.1f}"] for r in sp.itertuples() if int(r.saat_ET) in (2, 8, 9, 10, 12, 15, 16, 18, 20)],
                foot="US100, FTM tick verisi, Ekim 2026 (22 gün). Canlı spread değil, profil.")
    sh = rd("US100", "stop_hedef_izgarasi.csv"); sh = sh[(sh.donem == "OOS") & (sh.giris == "09:30 açılış") & (sh.yon == "long") & sh.hedef_ATR.isin([0.25, 0.5]) ]
    sht = table([("Hedef", 0), ("Stop", 0), ("Hedef önce", 1), ("Stop önce", 1), ("Başabaş isabet", 1)],
                [[f"{r.hedef_ATR:.2f} ATR ≈ {r.hedef_ATR * atr:.0f}", f"{r.stop_ATR:.2f} ATR ≈ {r.stop_ATR * atr:.0f}", pc(r.hedef_once), pc(r.stop_once), pc(r.basabas_isabet)] for r in sh.itertuples()],
                foot=f'{tag("yon")} US100, açılıştan long, test dönemi. İsabet her satırda başabaşa eşit veya altında: tablo yalnız mesafenin vurulma sıklığını gösterir.')
    src = "".join(f'<li><a href="{u}">{e(n)}</a></li>' for n, u in dict.fromkeys([(x["kaynak"], x["url"]) for x in N["basliklar"] + N["takvim_bugun"] + N["pozisyon"]]))
    css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapor.css"), encoding="utf-8").read()
    js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapor.js"), encoding="utf-8").read()
    out = f'''<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Günlük Masa Notu</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{css}</style></head>
<body><div class="page">
<header class="mast">
 <div class="mast-l">
  <div class="eyebrow">Günlük Masa Notu · US100 / XAUUSD</div>
  <h1>{day.day} {AY[day.month - 1]} {day.year}, {GUN[day.dayofweek]}</h1>
  <div class="edition">{e(N["baski"])}</div>
 </div>
 <img class="logo" alt="Aegean Capital" src="data:image/png;base64,{logo}">
</header>
<div class="meta">
 <span>Üretim {now:%d.%m.%Y %H:%M} TR</span><span>Piyasa verisi son bar {bar:%H:%M} TR ({["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"][bar.tz_convert("America/New_York").dayofweek]} {bar.tz_convert("America/New_York"):%H:%M} ET)</span>
 <span>NY açılışı 17:30 TR</span><span>Kişisel kullanım; yatırım tavsiyesi değildir</span>
</div>
<nav class="toc"><a href="#bugun">I. Bugün</a><a href="#us100">US100</a><a href="#xauusd">XAUUSD</a><a href="#pano">Pano</a><a href="#baglam">II. Bağlam</a><a href="#referans">III. Referans</a></nav>

<section id="bugun"><h2><span>I</span>Bugün</h2>
 <div class="two lead">
  <div><h3 class="sub">Özet</h3><ol class="sum">{oz}{auto}</ol>
   <p class="rule-note">Kural: bu not yön önermez. Seviyeler FTM tahminidir; emir öncesi MT5'te canlı fiyat teyit edilir.</p></div>
  <div><h3 class="sub">Bugünün takvimi</h3>{cal}</div>
 </div>
 <h3 class="sub">Hafta</h3>{wk}
 <h3 class="sub">Başlıklar</h3><div class="hls">{hl}</div><p class="note">{e(N["derleme_notu"])}</p>
</section>
{panel(U, V, S)}
{panel(G, V, S)}
<section id="pano"><h2>Cross-asset pano <small>son tam seans</small></h2>{pano}</section>

<section id="baglam"><h2><span>II</span>Bağlam <small>haftalık ölçekte değişir</small></h2>
 <div class="two"><div><h3 class="sub">Volatilite</h3>{volt}</div><div><h3 class="sub">Korelasyon rejimi</h3>{cort}</div></div>
 <h3 class="sub">Pozisyonlanma ve duyarlılık</h3>{post}
</section>

<section id="referans"><h2><span>III</span>Referans <small>10 yıllık taban oranlar; ayda bir yenilenir</small></h2>
 <div class="two"><div><h3 class="sub">RTH high / low ne zaman oluşur</h3>{hlt}</div><div><h3 class="sub">Gece aralığına göre NY seansı</h3>{gdt}<h3 class="sub">Spread profili</h3>{spt}</div></div>
 <h3 class="sub">Gün içi kalan hareket</h3>{kht}
 <div class="two"><div><h3 class="sub">Stop / hedef vurulma sıklığı</h3>{sht}</div>
 <div><h3 class="sub">İşlem yok pencereleri ve FTM limitleri</h3>
  <ul class="plain"><li>Rollover: 23:55–01:05 TR (16:55–17:05 ET). Gap trading yasağı bu pencerede.</li><li>Planlı veri ve konuşmalar: takvimdeki saatin 5 dk öncesi ve sonrası.</li>
  <li>Günlük limit 200 $ (17:00 ET'de bakiye ve equity'nin yükseği referans). Trailing limit 300 $ (bakiye zirvesinden; 5,300 $'da 5,000'e kilitlenir).</li>
  <li>Tutarlılık: tek günün kârı 250 $'ı geçmemeli. 1 dakikadan kısa işlemlerin kârı sayılmaz.</li></ul></div></div>
 <h3 class="sub">Yöntem ve veri</h3>
 <ul class="plain">
  <li><b>Etiketler.</b> {tag("model")} test döneminde (2023+) taban orandan iyi tahmin etti. {tag("bilgi")} tanımlayıcı istatistik. {tag("zayif")} küçük iyileşme. {tag("yon")} yön içeren ve anlamlı çıkmayan. {tag("on")} veri tamamlanınca değişir.</li>
  <li><b>Fiyat.</b> US100 = Yahoo NQ=F + ofset; XAUUSD = Yahoo GC=F + ofset. Kaynak ~10–15 dk gecikmeli. US100 ofset modeli 2 aylık FTM verisiyle sınandı: fiyat hatası medyan 2.7, %90 8.7 puan; RTH high / low hatası medyan ~3, %90 ~10 puan.</li>
  <li><b>Temizlik.</b> Komşu kapanışlardan 10× medyan bar aralığından fazla taşan tick'ler kırpılır. Bu veri setinde NQ {V["temizlenen_bar"]["NQ"]}, GC {V["temizlenen_bar"]["GC"]} bar düzeltildi.</li>
  <li><b>Tanımlar.</b> FTM günü 17:00 ET → 17:00 ET. RTH 09:30–16:00 ET (17:30–00:00 TR). Gece 18:00–09:29 ET. ATR14: son 14 tam RTH aralığının ortalaması.</li>
  <li><b>Eksikler.</b> Spot altın kaynağı, dealer gamma / 0DTE, gerçek zamanlı opsiyon akışı, FTM hesap durumu bu baskıda yok.</li>
 </ul>
 <h3 class="sub">Haber kaynakları</h3><ul class="src">{src}</ul>
</section>
<footer>Aegean Capital · Günlük Masa Notu · {now:%d.%m.%Y %H:%M} TR · Veri: Yahoo Finance (GitHub Actions), FTM MT5 geçmişi (istatistik katmanı), web taraması.</footer>
</div><script>{js}</script></body></html>'''
    import re
    fix = lambda m: m.group(0).replace("high", '<span lang="en">high</span>').replace("High", '<span lang="en">High</span>')
    out = re.sub(r"<th[^>]*>.*?</th>|<h3 class=\"sub\">.*?</h3>|<h4>.*?</h4>", fix, out, flags=re.S)
    open(os.path.join(R, "index.html"), "w", encoding="utf-8").write(out)
    print("yazıldı", len(out) // 1024, "KB")


if __name__ == "__main__":
    main()
