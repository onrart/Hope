# Hope

**Kısa:** Bu döküman repodaki temel bileşenleri ve en güvenli şekilde nasıl çalıştırılacağını açıklar. Özellikle borsa/otomatik işlem (Binance) içeren scriptler *riskli* olabilir — gerçek API anahtarlarıyla çalıştırmadan **önce** `DRY_RUN`/test modunu kullanın.

---

## Ön gereksinimler
- Python **3.11** (veya 3.10+ uyumlu) — önerilen sürüm: **3.11**
- `git`, `zip` (opsiyonel)
- (İsteğe bağlı) Docker & docker-compose — container ile izole çalışma

---

## Hızlı kurulum (local)
Aşağıdaki adımlar Unix/macOS/WSL için verilmiştir. Windows PowerShell için yanına PowerShell karşılıklarını ekledim.

### 1) Repo klonlama / zip açma
```bash
# git ile
git clone https://github.com/onrart/Hope.git
cd Hope

# veya eğer ZIP yüklüyse
# unzip Hope.zip -d Hope_repo && cd Hope_repo
```

### 2) Sanal ortam oluşturma
Linux/macOS/WSL:
```bash
python -m venv .venv
source .venv/bin/activate
```
PowerShell (Windows):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3) Bağımlılıkları yükleme
```bash
pip install --upgrade pip
pip install -r requirements.txt
# tavsiye: dev bağımlılıkları için requirements-dev.txt varsa ekleyin
# pip install -r requirements-dev.txt
```

> Eğer requirements-dev.txt yoksa `pytest`, `ruff`, `black` gibi paketleri elle yükleyin: `pip install pytest ruff black isort`

---

## Ortam değişkenleri (.env)
Repo `.env.example` içeriyorsa onu kopyalayın ve kendi `.env` dosyanızı oluşturun.

**Örnek:**
```
cp .env.example .env
# veya Windows PowerShell
Copy-Item .env.example .env
```

`.env` içine gerçek API anahtarları koymayın public repoya push etmeyin. Aşağıdaki değişkenler yaygın olarak kullanılır (repo özelinde isimler farklı olabilir):
```
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
DRY_RUN=1
SYMBOL=BTCUSDT
LOG_LEVEL=INFO
```
- `DRY_RUN=1` veya `TRUE` ayarlanırsa trading scriptleri **gerçek emir** göndermez; önce kodda `DRY_RUN` kontrolü olduğundan emin olun.

---

## Hangi scriptler güvenlidir / hangileri tehlikeli?
- **Güvenli (genelde):** `bootstrap/reconcile.py` — genelde örnek / test çıktısı üretir.
- **Riskli / Gerçek işlem yapabilir:** `futures/*`, `spot/*`, `runners/run_spot.py`, `runners/run_futures.py` — bunlar borsa API çağrısı yapar ve yanlış anahtarla gerçek emir gönderebilir.

**ÖNEMLİ:** Riskli scriptleri çalıştırmadan önce: `.env` dosyanızda `DRY_RUN=1` veya `TESTNET=1` ayarlayın; kodun `DRY_RUN` veya `testnet` kontrolü yaptığını manuel olarak doğrulayın.

---

## Nasıl çalıştırırım? (örnekler)
Aşağıda birkaç yaygın senaryo için örnek komutlar var.

### 1) Örnek / güvenli script çalıştırma (reconcile)
```bash
# environment aktifken
export DRY_RUN=1
python -m bootstrap.reconcile
# veya doğrudan dosya
python bootstrap/reconcile.py
```

Windows PowerShell:
```powershell
$env:DRY_RUN = "1"
python bootstrap\reconcile.py
```

### 2) Spot runner (DİKKAT: riskli)
```bash
# gerçek işlem göndermeden önce mutlaka DRY_RUN=1 ayarlayın
export DRY_RUN=1
python runners/run_spot.py --config config/spot.yaml
```
> *Not:* `run_spot.py` scripti farklı argümanlar bekleyebilir; `--help` ile ne beklediğini kontrol edin:
```
python runners/run_spot.py --help
```

### 3) Testleri çalıştırma
```bash
pytest -q
```
Eğer pytest yüklü değilse önce `pip install pytest`.

### 4) Linter & format
```bash
# ruff
ruff check .
# black
black .
# isort
isort .
```
(Öneri: `pre-commit` kullanın; `.pre-commit-config.yaml` eklenecek.)

---

## Docker (opsiyonel)
Eğer `Dockerfile` veya `docker-compose.yml` varsa container içinde çalıştırmak daha izole olur.
Örnek (varsayım):
```bash
docker build -t hope-app .
docker run --env-file .env hope-app
```

---

## Hata ayıklama ve loglar
- `LOG_LEVEL` veya benzeri env değişkeni ile log seviyesini arttırın.
- Uzun çalışan batch'ler için kodda checkpoint/partial save kontrolü var mı kontrol edin.

---

## Güvenlik & iyi uygulamalar
- **API anahtarlarını** public repoya kesinlikle koymayın.
- Eğer anahtar repoya kazara eklendiyse: **derhal rotate** (yenile) ve `git filter-repo`/BFG ile geçmişten silin.
- `__pycache__`, `*.pyc`, `.env`, `history.jsonl` gibi dosyaları `.gitignore`'a ekleyin.

---

## Hızlı sorun giderme
- `ModuleNotFoundError` alırsanız: `pip install -r requirements.txt` çalıştırın.
- `Permission denied` veya `port in use` gibi hatalarda ilgili port/izinleri kontrol edin.

---

## Daha fazlası — geliştirme önerileri
- CI/CD: GitHub Actions ile `pytest` ve `ruff` çalıştırın. (Ben yardımcı olabilirim)
- pre-commit: commit öncesi linter/format çalışsın.
- tests: kritik fonksiyonlar için unit test ekleyin (decider, risk guard vb.).

---