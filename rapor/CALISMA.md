# Günlük Masa Notu — baskı talimatı (zamanlanmış görevler bunu izler)

Üç baskı, hafta içi: **londra** (07:45 Londra = 10:45 TR kış), **ny** (07:45 ET = 15:45 TR kış, ana rapor), **gunsonu** (16:40 ET = 00:40 TR kış).
Dil Türkçe. Rapor yön önermez. Hiçbir rakam uydurulmaz; bulunamayan "—" kalır. Saatler ET ve TR (ABD kış saatinde TR = ET + 8, yaz saatinde ET + 7; `zoneinfo` ile hesapla).

## 1. Repo
- `/home/claude/piyasa-veri` yoksa: `add_repo(owner="egedogann", repo="piyasa-veri", access="push")`, sonra `git clone --depth 5 https://github.com/egedogann/piyasa-veri /home/claude/piyasa-veri`.
- `git -C /home/claude/piyasa-veri pull -q --rebase`. `pip install -q --break-system-packages pandas numpy scipy scikit-learn` gerekirse.

## 2. Veri tazeliği
- `data/son_guncelleme.json` → `calisma_utc` 90 dakikadan eskiyse: `gh api -X POST repos/egedogann/piyasa-veri/actions/workflows/veri.yml/dispatches -f ref=main`, en fazla 6 dk bekle (`gh api repos/egedogann/piyasa-veri/actions/runs --jq '.workflow_runs[0].status'`), sonra `git pull`.
- `gunsonu` baskısında önce eski `rapor/veri.json`'u `/tmp/veri_onceki.json`'a kopyala (karne için).

## 3. Haber ve takvim → `rapor/haber.json`
Web araması (WebSearch / WebFetch) ile, mevcut dosyadaki şemayı koruyarak yeniden yaz. Alanlar:
- `baski`: "Londra öncesi baskı" / "NY öncesi baskı" / "Gün sonu baskısı".
- `derleme_notu`: tarama saati (TR) ve "her satırın kaynağı yanında".
- `bugun_bayraklar`: o gün (ET takvim günü) CPI/NFP/FOMC kararı/PCE/PPI/perakende satış/GDP varsa `ev_major=1`; FOMC kararı `ev_fomc=1`, CPI `ev_cpi=1`, NFP `ev_nfp=1`. Yoksa hepsi 0.
- `ozet`: 3–5 madde, en önemli önce. İşlem için önemli olan: o günün olayları ve saatleri, seansa denk gelen konuşmalar, gece ne değişti. Tahmin/yön yok.
- `takvim_bugun`: bugünün ABD (ve altın için önemli global) olayları: `tr, et, olay, beklenti, onceki, onem (yüksek/orta/düşük), not, kaynak, url`. Beklenti ve önceki değer kaynaktan; kaynaklar çelişiyorsa `not`'a yaz.
- `takvim_hafta`: bugünden itibaren haftanın günleri; `etiket` ∈ {Normal, Veri günü, Olay riski, OPEX}. Ege veri günlerinde işlem yapmıyor; bu yüzden veri günlerini net işaretle.
- `takvim_notu`: tutarsızlık notu (yoksa boş).
- `basliklar`: 5–8 başlık; US100 ve XAU'yu etkileyecekler: Fed konuşmaları, Trump açıklamaları/seyahat/tarife, mega-cap CEO değişikliği veya skandal, bilanço, jeopolitik, petrol, tahvil. `baslik, ozet (kendi cümlelerinle, ≤2 cümle), etki (US100/XAU/İkisi/Bağlam), kaynak, url`.
- `pozisyon`: COT (son rapor), Fear & Greed, AAII, opsiyonların ima ettiği haftalık hareket, Fed fiyatlaması. Bulunamayanı çıkar.
- `pozisyon_notu`.
Telif: alıntı yapma, kendi cümlelerinle yaz.

## 4. Hesap ve sayfa
- `python3 scripts/rapor_hesap.py && python3 scripts/rapor_html.py`
- Sağlama (geçmezse düzelt, düzeltemezsen özetin başına uyarı yaz):
  - `rapor/veri.json` → US100 `fiyat`, Yahoo NQ son kapanış + ofsete eşit olmalı; NDX son günlük kapanışından ±%3 içinde.
  - US100 `atr14_rth`, `data/d1/IDX_NDX.csv` son 14 günün (high−low) ortalamasından ±%10 içinde. Değilse hatalı tick ara.
  - `temizlenen_bar` 5'ten büyükse özette belirt.

## 5. Baskıya özel
- **londra**: Gece / Asya / altın ağırlıklı özet; o günün takvimi; Londra açılışı 08:00 Londra.
- **ny**: Ana rapor. Gece aralığı tamamlandığı için aralık bandı "kesin" olmalı (veri.json `aralik.durum`). Özetin son maddesi: US100 ve XAU için beklenen RTH aralığı (%80) ve 0.25 ATR stopun 25 $ riske 0.01 lotla sığıp sığmadığı.
- **gunsonu**: Özete "Karne" maddeleri ekle: `/tmp/veri_onceki.json`'daki (aynı günün ny baskısı varsa onun) aralık bandı ile bugünün gerçekleşen RTH aralığını (`rapor_hesap.daily` ile, bugünün FTM günü) karşılaştır: %50 ve %80 bandın içinde mi; önceki gün high/low ve gece high/low kırıldı mı. Ardından yarının takvimi.

## 6. Yayın
- Artifact slug `7e749a38-02f0-44c0-a774-8f56f01275b5` ("Günlük Masa Notu"). `get_artifact` ile `version` ve `read` al; `publish_files(slug, base_version=version, files=[{as:"index.html", path:"/home/claude/piyasa-veri/rapor/index.html"}], mode="patch", label="<tarih> <baskı>")`; `read` "owner" değilse `shared_live` ver.
- Artifact araçları yoksa: `SendUserFile` ile `rapor/index.html` gönder.
- Repoya kaydet: `git add rapor/haber.json rapor/veri.json rapor/index.html && git commit -m "<tarih> <baskı>" && git pull --rebase && git push`.

## 7. Bildirim
Son mesaj (SendUserMessage): 3–4 satır. Baskı adı, en önemli 2 madde, bugünün veri/olay saatleri (TR), sayfa linki https://claude.ai/artifact/GcgjuwEoV1oqgQzZUAEbkx. Bir adım başarısız olduysa ne olduğunu açıkça yaz.
