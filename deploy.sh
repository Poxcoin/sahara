#!/bin/bash
# Запускати на новому VPS від root: bash deploy.sh

set -e

APP_DIR=/opt/sahara
REPO=https://github.com/Poxcoin/sahara.git   # замінити на реальний repo

echo "=== SAHARA Deploy ==="

# 1. Системні пакети
apt-get update -q
apt-get install -y python3 python3-venv python3-pip nginx git libgl1

# 2. Клонуємо код
if [ -d "$APP_DIR" ]; then
    cd $APP_DIR && git pull
else
    git clone $REPO $APP_DIR
fi
cd $APP_DIR

# 3. Venv + залежності
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

# 4. Директорії для медіа і БД
mkdir -p media/originals media/generated media/models data

# 5. .env — якщо ще немає
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "!!! Заповни /opt/sahara/.env і запусти знову: bash deploy.sh restart"
    exit 0
fi

# 6. systemd сервіси
cp sahara-web.service /etc/systemd/system/
cp sahara-tg.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sahara-web sahara-tg
systemctl restart sahara-web sahara-tg

# 7. nginx (замінити YOUR_DOMAIN)
DOMAIN=${1:-"_"}
cat > /etc/nginx/sites-available/sahara << EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 20M;

    location /media/ {
        alias /opt/sahara/media/;
    }

    location /static/ {
        alias /opt/sahara/app/static/;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

ln -sf /etc/nginx/sites-available/sahara /etc/nginx/sites-enabled/sahara
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo ""
echo "=== Done ==="
echo "Web: http://$DOMAIN"
echo "Logs: tail -f /opt/sahara/web.log"
echo ""
echo "Для SSL (після налаштування DNS):"
echo "  apt install certbot python3-certbot-nginx"
echo "  certbot --nginx -d $DOMAIN"
