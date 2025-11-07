```markdown
# Hope — Minimal Gemini Trader

Bu minimal proje, piyasa verisini çekip Google Gemini'ye göndererek basit `BUY`/`SELL`/`HOLD` kararları alan ve (opsiyonel) exchange'e emir gönderen bir örnektir.

## Nasıl çalıştırılır

1. `.env` dosyasını oluştur: `cp .env.example .env` ve anahtarları doldur.
2. Sanal ortam oluşturup bağımlılıkları yükle:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```