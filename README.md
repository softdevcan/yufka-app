# Yufka Takip

Yufka üretim ve satış takip sistemi.

## Özellikler

- **Dashboard**: Günlük özet, hızlı erişim butonları, son işlemler
- **Üretim Girişi**: Yufka, mantı, kadayıf, sigara böreği üretim kaydı
- **Satış Girişi**: Satış kaydı, otomatik toplam hesaplama
- **Malzeme Yönetimi**: Malzeme listesi ve fiyat güncelleme
- **Raporlar**: Günlük, haftalık, aylık ve özel tarih aralığı raporları
- **Tema Desteği**: Light/Dark tema

## Teknolojiler

- **Backend**: FastAPI (Python)
- **Frontend**: Jinja2 + Pico CSS
- **Veritabanı**: SQLite
- **Deployment**: Docker + Nginx

## Yerel Geliştirme

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# .env dosyası oluştur
cp .env.example .env

# Uygulamayı çalıştır
uvicorn app.main:app --reload --port 8080
```

Tarayıcıda aç: http://localhost:8080

## Docker ile Çalıştırma

```bash
# .env dosyası oluştur
cp .env.example .env
# Şifreyi değiştir
nano .env

# Build ve çalıştır
docker-compose up -d --build

# Logları izle
docker-compose logs -f
```

## Production Deployment

Sunucuda:

```bash
# Repo'yu klonla
git clone https://github.com/softdevcan/yufka-app.git /opt/yufka-app
cd /opt/yufka-app

# Setup script'i çalıştır
chmod +x deploy/setup.sh
sudo ./deploy/setup.sh
```

## Varsayılan Giriş Bilgileri

- **Kullanıcı**: admin
- **Şifre**: changeme

> ⚠️ Production'da şifreyi mutlaka değiştirin!

## Proje Yapısı

```
yufka-app/
├── app/
│   ├── main.py           # FastAPI uygulaması
│   ├── database.py       # SQLite bağlantısı
│   ├── models.py         # Pydantic modeller
│   ├── auth.py           # Authentication
│   ├── templates/        # Jinja2 templates
│   └── static/           # CSS dosyaları
├── data/                 # SQLite veritabanı
├── deploy/               # Nginx ve kurulum scriptleri
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Lisans

MIT
