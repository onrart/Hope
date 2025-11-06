Kurulum
-------
1. Python 3.11 kurulu olmalı.
2. Bağımlılıkları yükleyin:

   ```bash
   pip install -r requirements.txt
   ```

.env hazırlığı
--------------
Örnek dosyayı projeye kopyalayın ve gerekirse değerleri güncelleyin:

```bash
cp .env.example .env
```

`BINANCE_TESTNET=true` ile gelen DEMO anahtarları test amaçlı çalışır. Gerçek işlemler için ilgili PROD anahtarlarını `.env` içinde değiştirin.

Çalıştırma
----------
- Karar oluşturma akışı: `python -m runners.run_decide`
- Spot karar → emir (dry-run): `python -m runners.run_spot`
- Futures karar → emir (dry-run): `python -m runners.run_futures`

Monitoring & Dashboard
----------------------
Yeni modern izleme ekranını başlatmak için metrics sunucusunu çalıştırın:

```bash
python -m runners.serve_metrics
```

Sunucu varsayılan olarak `http://localhost:9108` üzerinde ayağa kalkar. Aşağıdaki uç noktalar aktif olur:

- `/dashboard`: Modern kontrol paneli
- `/metrics`: Prometheus uyumlu metrikler
- `/health`: JSON sağlık kontrolü

Farklı bir port kullanmak için `MONITOR_PORT` ortam değişkenini ayarlayabilirsiniz.
