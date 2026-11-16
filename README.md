# piyasa-veri
Günlük masa raporu için kamuya açık piyasa verisi. GitHub Actions hafta içi 4 kez çalışır (`.github/workflows/veri.yml`), `data/` klasörüne yazar.
- `data/m5/`: NQ, NDX, GC, ES ve (bulunursa) spot altın 5 dk barları, birikimli
- `data/d1/`: cross-asset günlük barlar
- `data/son_guncelleme.json`: son çalışma zamanı, her kaynağın durumu
Elle çalıştırma: Actions → piyasa-verisi → Run workflow.
