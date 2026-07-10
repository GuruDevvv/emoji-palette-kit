# 🎨 Emoji Palette Kit

Дай своему **ИИ-агенту** курируемую палитру кастомных эмодзи Telegram.

Ты в удобном интерфейсе выбираешь, какие эмодзи из твоих наборов агент может использовать, —
а **смыслы к каждому эмодзи генерируются автоматически** (vision-AI смотрит на картинку).
На выходе — `agent-palette.json`, который агент вставляет в посты через плейсхолдеры `:key:`.

> Зачем: у кастом-эмодзи нет текстового имени, только ID — их нельзя «набрать» в тексте.
> Плюс встроенный alias часто врёт (под 🙏 может быть сидящий Будда). Кит решает и то, и другое:
> курируешь визуально, смыслы описывает ИИ, агент подставляет по ID.

Весь инструмент — **один файл** `emoji_palette_kit.py` (self-contained, HTML-интерфейс вшит внутрь).

---

## Быстрый старт

```bash
# 1. забрать один файл (или скачай кнопкой Code -> Download)
curl -O https://raw.githubusercontent.com/GuruDevvv/emoji-palette-kit/main/emoji_palette_kit.py

pip install telethon

python emoji_palette_kit.py init        # создаст .env — впиши туда ключи
python emoji_palette_kit.py fetch        # вход в Telegram + скачает твои наборы -> index.html
#   -> открой index.html, включи тумблером нужные эмодзи, «Скачать palette.json»,
#      положи скачанный файл рядом (заменив palette.json)
python emoji_palette_kit.py describe     # vision-AI опишет смысл каждого включённого эмодзи
python emoji_palette_kit.py export       # соберёт agent-palette.json
python emoji_palette_kit.py snippet      # выгрузит код вставки (agent_emoji.py) для агента
```

## Что нужно

- **Python 3.9+**, `pip install telethon`
- **Telegram API id/hash** — бесплатно на https://my.telegram.org → *API development tools*
- **Ключ vision-AI** — https://openrouter.ai/keys (для авто-описаний; модель со зрением)
- **Telegram Premium** — только у аккаунта, от которого агент будет *постить* эмодзи
  (у получателей не нужен; сам кит fetch/describe/export работает без Premium)

---

## Шаги подробно

### `init`
Создаёт `.env` (шаблон ключей) и `.gitignore`. Открой `.env`, впиши `TG_API_ID`, `TG_API_HASH`,
`OPENROUTER_API_KEY` (и при желании `VISION_MODEL`, `LANG_OUT`).

### `fetch`
```bash
python emoji_palette_kit.py fetch          # все установленные наборы
python emoji_palette_kit.py fetch set1 set2 # только конкретные (short_name из t.me/addemoji/<name>)
```
При первом запуске Telethon попросит телефон и код из Telegram. Скрипт скачает эмодзи и соберёт `index.html`.

### Выбрать эмодзи (браузер)
Открой **`index.html`** двойным кликом. Слева — меню наборов с иконками, по центру — эмодзи набора.
**Включай тумблером** нужные. Смыслы писать НЕ нужно — их сгенерит `describe`. Нажми
**«⬇ Скачать palette.json»**.

> ⚠️ Браузер сохранит в **Downloads** (иногда `palette (1).json`). Перенеси файл в папку кита и
> замени `palette.json` (точное имя). Не открывай `index.html` из Downloads — там нет папки `img/`.

### `describe` → `export`
```bash
python emoji_palette_kit.py describe    # --all чтобы переописать даже готовые
python emoji_palette_kit.py export
```
`describe` смотрит на картинки включённых эмодзи и заполняет «смысл» (после — обнови вкладку браузера).
`export` собирает **`agent-palette.json`** с уникальными ключами `:key:`.

> 💸 `describe` — 1 запрос к vision-модели на эмодзи (платный OpenRouter, порядок цены — центы за
> сотню). Анимированные эмодзи описываются по статичному превью — смысл движения может потеряться,
> проверь такие вручную. Ключи `:key:` фиксируются при первом `export` и дальше не меняются.

---

## Как агент это использует

`python emoji_palette_kit.py snippet` создаст **`agent_emoji.py`** с функциями `resolve_emoji()` и
`emoji_menu()` — скопируй их в свой агент. Агент пишет текст с `:key:` (напр. `Путь :dharma:`), а перед
отправкой через Telethon подставляет кастом-эмодзи по ID (UTF-16 offsets, мягкая деградация уже внутри).

**Правила для агента** (впиши в его промпт): ставить эмодзи **редко** (0–2 на сообщение), по смыслу
фразы, не гроздьями; неизвестный `:key:` оставлять текстом.

---

## Приватность и безопасность
Всё работает **локально**. Наружу уходят только запросы к Telegram (твой обычный аккаунт) и картинки
включённых эмодзи в vision-AI на шаге `describe`.

> 🔒 **ГЛАВНОЕ:** после `fetch` появляется **`tg_session.session`** — это ключ от твоего
> Telegram-аккаунта (опаснее api_hash). **Никогда не пересылай папку целиком и не коммить сессию/`.env`.**
> `.gitignore` (создаётся `init`) уже защищает от случайного `git add .`.
