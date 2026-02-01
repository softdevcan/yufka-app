#!/bin/bash

# Yufka Takip - Otomatik Kurulum Scripti
# Domain: yufka.softdevcan.site

set -e

echo "🫓 Yufka Takip Kurulum Başlıyor..."

# Renk kodları
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonksiyonlar
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Root kontrolü
if [ "$EUID" -ne 0 ]; then
    log_error "Bu script root olarak çalıştırılmalı"
    exit 1
fi

# Sistem güncellemesi
log_info "Sistem güncelleniyor..."
apt-get update -qq
apt-get upgrade -y -qq

# Docker kurulumu
if ! command -v docker &> /dev/null; then
    log_info "Docker kuruluyor..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
else
    log_info "Docker zaten kurulu"
fi

# Docker Compose kurulumu
if ! command -v docker-compose &> /dev/null; then
    log_info "Docker Compose kuruluyor..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
else
    log_info "Docker Compose zaten kurulu"
fi

# Nginx kurulumu
if ! command -v nginx &> /dev/null; then
    log_info "Nginx kuruluyor..."
    apt-get install -y -qq nginx
    systemctl enable nginx
else
    log_info "Nginx zaten kurulu"
fi

# Certbot kurulumu
if ! command -v certbot &> /dev/null; then
    log_info "Certbot kuruluyor..."
    apt-get install -y -qq certbot python3-certbot-nginx
else
    log_info "Certbot zaten kurulu"
fi

# Uygulama dizini
APP_DIR="/opt/yufka-app"
log_info "Uygulama dizini oluşturuluyor: $APP_DIR"
mkdir -p $APP_DIR
cd $APP_DIR

# .env dosyası oluştur (eğer yoksa)
if [ ! -f .env ]; then
    log_info ".env dosyası oluşturuluyor..."

    # Rastgele secret key oluştur
    SECRET_KEY=$(openssl rand -hex 32)

    cat > .env << EOF
AUTH_USERNAME=admin
AUTH_PASSWORD=changeme
AUTH_SECRET_KEY=$SECRET_KEY
EOF

    log_warn "Lütfen .env dosyasındaki şifreyi değiştirin!"
    log_warn "nano $APP_DIR/.env"
fi

# Nginx konfigürasyonu
log_info "Nginx konfigürasyonu ayarlanıyor..."
cp deploy/nginx.conf /etc/nginx/sites-available/yufka
ln -sf /etc/nginx/sites-available/yufka /etc/nginx/sites-enabled/

# Nginx syntax kontrolü
nginx -t

# SSL sertifikası
log_info "SSL sertifikası alınıyor..."
certbot --nginx -d yufka.softdevcan.site --non-interactive --agree-tos --email admin@softdevcan.site || log_warn "SSL sertifikası alınamadı, manuel olarak alınmalı"

# Docker build ve başlat
log_info "Docker container'ı başlatılıyor..."
docker-compose up -d --build

# Nginx yeniden başlat
systemctl restart nginx

# Durum kontrolü
log_info "Servis durumu kontrol ediliyor..."
sleep 5

if docker-compose ps | grep -q "Up"; then
    log_info "✅ Uygulama başarıyla başlatıldı!"
    echo ""
    echo "=========================================="
    echo "🫓 Yufka Takip Kurulum Tamamlandı!"
    echo "=========================================="
    echo ""
    echo "URL: https://yufka.softdevcan.site"
    echo ""
    echo "Varsayılan giriş bilgileri:"
    echo "  Kullanıcı: admin"
    echo "  Şifre: changeme"
    echo ""
    echo "⚠️  ÖNEMLİ: Şifreyi değiştirin!"
    echo "  nano $APP_DIR/.env"
    echo "  docker-compose restart"
    echo ""
else
    log_error "Uygulama başlatılamadı. Logları kontrol edin:"
    echo "docker-compose logs"
fi
