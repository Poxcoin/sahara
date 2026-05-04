# SAHARA — AI каталог одягу

Pipeline: твій Telegram-канал → AI try-on (Replicate) → преміум-каталог.

## Стек

- **FastAPI** + Jinja2 — сайт + адмінка в одному додатку
- **SQLite** (через SQLAlchemy async) — БД товарів
- **aiogram** — Telegram Bot API для парсингу твого каналу
- **Replicate** (модель `cuuupid/idm-vton`) — AI try-on

## Setup

### 1. Залежності

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Створення Telegram бота

1. У Telegram знайди **@BotFather**
2. `/newbot` → дай назву → дай username (закінчується на `_bot`)
3. Збережи токен (формат: `1234567890:ABCdef...`)

### 3. Канал для парсингу

1. Створи приватний канал у Telegram
2. **Додай свого бота адміном** цього каналу (Settings → Administrators → Add)
3. Запиши username каналу (`@your_channel`) або числовий ID

### 4. Replicate

1. https://replicate.com → Sign in with GitHub
2. https://replicate.com/account/api-tokens → Create token

### 5. Налаштування

```bash
cp .env.example .env
nano .env  # заповнити TG_BOT_TOKEN, TG_SOURCE, REPLICATE_API_TOKEN, ADMIN_PASSWORD
```

### 6. Reference-модель

Поклади хоча б одне фото моделі в стилі SAHARA сюди:
```
media/models/sahara_woman_1.jpg
```

Як отримати: згенеруй раз через Flux/Midjourney з промтом нижче.

**Промт для reference-моделі:**
```
elegant fashion model, full body shot, neutral pose facing camera,
plain white tank top and beige trousers, minimalist studio with
warm beige walls and soft natural light from the side,
COS / Zara premium aesthetic, photorealistic, sharp focus,
neutral color palette, 4k editorial fashion photography
```

### 7. Запуск (3 термінали)

**Термінал 1** — парсер Telegram:
```bash
source venv/bin/activate
python -m app.services.tg_parser
```

**Термінал 2** — веб-сервер:
```bash
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Термінал 3** — твоя адмінка:
- Відкрий http://localhost:8000/admin
- Логін: `admin`, пароль з `.env`

## Workflow

1. Кидаєш фото одягу в свій TG-канал з підписом `Назва\nЦіна: 4890`
2. Бот ловить пост, додає в БД як **PENDING**
3. В адмінці бачиш товар → жмеш **Generate AI**
4. Background task запускає Replicate try-on (~30-60 сек)
5. Статус → **READY**, бачиш пару (оригінал + AI)
6. Якщо ОК → **Publish** → товар на сайті
7. Якщо погано → **Re-gen** (інший seed або модель)

## Витрати на Replicate

- IDM-VTON: ~$0.04 за генерацію
- 100 товарів = ~$4
- Free tier на старті: ~$5 кредитів

## Структура

```
sahara/
├── app/
│   ├── main.py              # FastAPI: публічний каталог + адмінка
│   ├── config.py            # налаштування з .env
│   ├── db.py                # async SQLAlchemy
│   ├── models.py            # Product, ProductStatus
│   ├── services/
│   │   ├── tg_parser.py     # aiogram bot listener (окремий процес)
│   │   └── tryon.py         # виклик Replicate
│   └── templates/           # base, index, product, admin, etc.
├── media/
│   ├── originals/           # фото з Telegram
│   ├── generated/           # AI try-on результати
│   └── models/              # твої reference-моделі
├── data/
│   └── sahara.db            # SQLite
├── .env
└── requirements.txt
```
