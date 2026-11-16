# piyasa-veri
Günlük masa raporu için kamuya açık piyasa verisi. GitHub Actions hafta içi 4 kez çalışır (`.github/workflows/veri.yml`), `data/` klasörüne yazar.
- `data/m5/`: NQ, NDX, GC, ES ve (bulunursa) spot altın 5 dk barları, birikimli
- `data/d1/`: cross-asset günlük barlar
- `data/son_guncelleme.json`: son çalışma zamanı, her kaynağın durumu
Elle çalıştırma: Actions → piyasa-verisi → Run workflow.

## stats/ (geçmiş istatistik katmanı)
`scripts/istatistik_kur.py` FTM MT5 M5 verisinden (US100 2017-04 →, XAUUSD 2016-01 →, 30 Eki 2026'ya kadar) bir kez üretildi; Actions'ta çalışmaz (FTM verisi gerekir). Yenilemek için PC'de: `python scripts/istatistik_kur.py C:\ftm_quant\ftm_data stats`.
- `stats/ozet.json`: modeller (aralık, gün tipi), doğrulama skorları, `rapora_al` bayrakları
- `stats/<SEMBOL>/`: olay tepkileri, seviye kırılma, gap, saatlik high/low, seans devri, gece aralığı, haftanın günü, seri (yön), spread profili, günlük özellikler (benzer gün için)
