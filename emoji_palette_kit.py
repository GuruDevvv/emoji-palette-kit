#!/usr/bin/env python
"""
Emoji Palette Kit — курируемая палитра кастом-эмодзи Telegram для ИИ-агента.

Самодостаточный один файл. Быстрый старт:
  python emoji_palette_kit.py init       # создать .env (+ .gitignore) — впиши в .env ключи
  python emoji_palette_kit.py fetch       # вытянуть УСТАНОВЛЕННЫЕ у тебя наборы эмодзи
                                          #  -> palette.json + img/ + index.html
  # открыть index.html, тумблерами включить нужные эмодзи, «Скачать palette.json»
  python emoji_palette_kit.py describe    # авто-сгенерить смыслы у включённых (vision-AI)
  python emoji_palette_kit.py export      # собрать agent-palette.json для агента
  python emoji_palette_kit.py snippet     # выгрузить код вставки эмодзи для твоего агента

Смыслы к эмодзи ПИСАТЬ РУКАМИ НЕ НУЖНО — их генерирует шаг `describe`.
Нужно: pip install telethon; ключи Telegram (my.telegram.org) и OpenRouter (openrouter.ai/keys).
Отправлять кастом-эмодзи может только аккаунт с Telegram Premium.
"""
import os, sys, json, re, time, base64, argparse, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PALETTE = os.path.join(HERE, "palette.json")
EXPORT  = os.path.join(HERE, "agent-palette.json")
INDEX   = os.path.join(HERE, "index.html")
IMGROOT = os.path.join(HERE, "img")
SESSION = os.path.join(HERE, "tg_session")

ENV_TEMPLATE = """# --- Telegram API (для шага fetch). Получить: https://my.telegram.org -> API development tools
TG_API_ID=123456
TG_API_HASH=0123456789abcdef0123456789abcdef

# --- Vision-AI для авто-описания (шаг describe). Ключ: https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-...
VISION_MODEL=anthropic/claude-sonnet-4-5
LANG_OUT=русском
"""

GITIGNORE_TEMPLATE = """# НИКОГДА не коммить и не пересылать:
.env
tg_session*
# рабочие артефакты (генерятся заново):
img/
palette.json
palette.json.bak
agent-palette.json
agent_emoji.py
index.html
__pycache__/
"""

# Код вставки эмодзи для агента-получателя (команда `snippet` пишет его в agent_emoji.py).
AGENT_SNIPPET = r'''"""
Вставка кастом-эмодзи из agent-palette.json. Скопируй resolve_emoji()/emoji_menu() в свой агент.
Агент пишет текст с плейсхолдерами :key: — resolve_emoji заменяет их на emoji + entity.
⚠️ Отправлять кастом-эмодзи может ТОЛЬКО аккаунт с Telegram Premium (у получателя не нужен).
"""
import json, re
from telethon.tl.types import MessageEntityCustomEmoji

EMOJI_RE = re.compile(r":([a-z0-9_]+):")

def _u16(s):  # длина в UTF-16 code units — в них Telegram считает offset/length
    return len(s.encode("utf-16-le")) // 2

def load_palette(path="agent-palette.json"):
    return {e["key"]: e for e in json.load(open(path, encoding="utf-8"))["emoji"]}

def resolve_emoji(text, palette):
    """text с :key: -> (clean_text, [MessageEntityCustomEmoji...], [unknown_keys])."""
    out, ents, unknown = [], [], []
    pos = last = 0
    for m in EMOJI_RE.finditer(text):
        pre = text[last:m.start()]; out.append(pre); pos += _u16(pre)
        e = palette.get(m.group(1))
        if e:
            out.append(e["alias"]); ln = _u16(e["alias"])
            ents.append(MessageEntityCustomEmoji(offset=pos, length=ln, document_id=int(e["id"])))
            pos += ln
        else:
            out.append(m.group(0)); pos += _u16(m.group(0)); unknown.append(m.group(1))
        last = m.end()
    out.append(text[last:])
    return "".join(out), ents, unknown

def emoji_menu(palette):
    """Меню для агента: что доступно (отдай агенту, чтобы знал ключи и смыслы)."""
    return "\\n".join(f":{e['key']}:  {e['alias']}  - {e['meaning']}" for e in palette.values())

# отправка: clean, ents, _ = resolve_emoji("Путь :dharma:", load_palette())
#           await client.send_message(chat, clean, formatting_entities=ents or None)
'''


# ---------- маленький загрузчик .env (без зависимостей) ----------
def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)


def save_atomic(path, data):
    if os.path.exists(path):
        try: os.replace(path, path + ".bak")
        except OSError: pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_palette():
    if os.path.exists(PALETTE):
        return json.load(open(PALETTE, encoding="utf-8"))
    return {"version": 1, "sets": []}


def sniff_mime(path):
    """mime по магическим байтам, не по расширению (тумбы стикеров бывают webp под .jpg)."""
    with open(path, "rb") as f:
        h = f.read(16)
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP": return "image/webp"
    if h[:3] == b"\xff\xd8\xff":                return "image/jpeg"
    if h[:8] == b"\x89PNG\r\n\x1a\n":           return "image/png"
    if h[:6] in (b"GIF87a", b"GIF89a"):         return "image/gif"
    return "image/webp"


def vision_call(key, model, text, mime, b64, retries=3):
    """Запрос к OpenRouter vision с ретраями на 429/5xx. Возвращает текст ответа модели."""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]}).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as ex:
            last = ex
            if ex.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1)); continue
            raise
    raise last


# =================== ШАГ 1: FETCH ===================
def cmd_fetch(args):
    import asyncio
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetStickerSetRequest, GetEmojiStickersRequest
    from telethon.tl.types import (InputStickerSetShortName,
                                   DocumentAttributeCustomEmoji, DocumentAttributeSticker)

    api_id = os.getenv("TG_API_ID"); api_hash = os.getenv("TG_API_HASH")
    if not api_id or not api_hash:
        sys.exit("Нет TG_API_ID / TG_API_HASH в .env (получить: my.telegram.org).")

    def kind_of(mime):
        return {"image/webp": "static", "application/x-tgsticker": "animated",
                "video/webm": "video"}.get(mime, "other")

    def alias_of(doc):
        for a in doc.attributes:
            if isinstance(a, DocumentAttributeCustomEmoji): return a.alt
        for a in doc.attributes:
            if isinstance(a, DocumentAttributeSticker): return a.alt
        return "?"

    async def run():
        client = TelegramClient(SESSION, int(api_id), api_hash)
        await client.start()   # интерактивный вход при первом запуске (телефон + код)
        palette = load_palette()

        wanted = args.sets
        if wanted:
            names = wanted
        else:
            res = await client(GetEmojiStickersRequest(hash=0))
            names = [s.short_name for s in res.sets]
            print(f"Найдено установленных наборов: {len(names)}")

        for name in names:
            try:
                st = await client(GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=name), hash=0))
            except Exception as e:
                print(f"  ! {name}: {e}"); continue
            setrec = next((s for s in palette["sets"] if s["short_name"] == name), None)
            if setrec is None:
                setrec = {"short_name": name, "title": st.set.title, "emoji": []}
                palette["sets"].append(setrec)
            setrec["title"] = st.set.title
            by_id = {e["id"]: e for e in setrec["emoji"]}
            seen = set()
            imgdir = os.path.join(IMGROOT, name); os.makedirs(imgdir, exist_ok=True)
            for doc in st.documents:
                did = str(doc.id); seen.add(did)
                kind = kind_of(doc.mime_type)
                ext = "webp" if kind == "static" else "jpg"
                rel = f"img/{name}/{did}.{ext}"; path = os.path.join(HERE, rel)
                if not os.path.exists(path):
                    try:
                        if kind == "static": await client.download_media(doc, file=path)
                        else: await client.download_media(doc, thumb=-1, file=path)
                    except Exception as e:
                        print(f"    ! dl {did}: {e}")
                rec = by_id.get(did)
                if rec is None:
                    setrec["emoji"].append({"id": did, "alias": alias_of(doc), "kind": kind,
                        "file": rel, "meaning": "", "desc": "", "enabled": False, "missing": False})
                else:
                    rec["alias"] = alias_of(doc); rec["kind"] = kind
                    rec["file"] = rel; rec["missing"] = False
            for e in setrec["emoji"]:
                if e["id"] not in seen: e["missing"] = True
            print(f"  {name}: {len(st.documents)} эмодзи")

        save_atomic(PALETTE, palette)
        render_html(palette)
        await client.disconnect()
        print(f"\nГотово. Открой index.html, включи нужные эмодзи, скачай palette.json,")
        print(f"замени им этот файл, затем: python {os.path.basename(__file__)} describe")

    asyncio.run(run())


# =================== ШАГ 2: DESCRIBE (vision-AI) ===================
def cmd_describe(args):
    key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("VISION_MODEL", "anthropic/claude-sonnet-4-5")
    lang = os.getenv("LANG_OUT", "русском")
    if not key:
        sys.exit("Нет OPENROUTER_API_KEY в .env. (Либо впиши смыслы вручную в palette.json.)")
    palette = load_palette()
    todo = [e for s in palette["sets"] for e in s["emoji"]
            if e["enabled"] and not e.get("missing") and (args.all or not e.get("meaning"))]
    if not todo:
        print("Нечего описывать (у всех включённых уже есть смысл, или ничего не включено)."); return
    print(f"Описываю {len(todo)} эмодзи через {model}…")

    base_prompt = (f"На картинке — кастомный эмодзи Telegram. Ответь СТРОГО в JSON без пояснений: "
                   f'{{"desc":"что изображено, кратко","meaning":"2-4 варианта смысла через / — '
                   f'как трактовать эмодзи в тексте"}}. Язык ответа — {lang}. '
                   f"ВАЖНО: смотри на КАРТИНКУ (символ-подсказка ниже часто ей не соответствует).")

    done = fail = 0
    for e in todo:
        path = os.path.join(HERE, e["file"])
        if not os.path.exists(path):
            print(f"  ! нет файла {e['file']} (повтори fetch)"); fail += 1; continue
        mime = sniff_mime(path)
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        text = base_prompt + f"\nСимвол-подсказка (может быть неточной): {e.get('alias', '')}"
        try:
            txt = vision_call(key, model, text, mime, b64)
            m = re.search(r"\{.*\}", txt, re.DOTALL)
            obj = json.loads(m.group(0)) if m else {}
            meaning = (obj.get("meaning") or "").strip()
            if not meaning:
                raise ValueError("пустой/непарсимый ответ модели")
            e["desc"] = (obj.get("desc") or "").strip()
            e["meaning"] = meaning
            done += 1
            print(f"  {e['alias']} → {e['meaning']}")
        except urllib.error.HTTPError as ex:
            fail += 1; print(f"  ! HTTP {ex.code}: {ex.read().decode()[:160]}")
        except Exception as ex:
            fail += 1; print(f"  ! {type(ex).__name__}: {ex}")
        if done and done % 10 == 0:
            save_atomic(PALETTE, palette)
    save_atomic(PALETTE, palette)
    render_html(palette)
    tail = f" Не удалось: {fail} — запусти describe снова, повторит только их." if fail else ""
    print(f"\nОписано: {done}.{tail}\nОбнови вкладку index.html (перегенерирована). Дальше: "
          f"python {os.path.basename(__file__)} export")


# =================== ШАГ 3: EXPORT ===================
_TRANSLIT = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
 'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
 'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'',
 'э':'e','ю':'yu','я':'ya'}


def _slug(meaning):
    first = (meaning or "emoji").split("/")[0].strip().lower()
    lat = "".join(_TRANSLIT.get(c, c) for c in first)
    lat = re.sub(r"[^a-z0-9]+", "_", lat).strip("_")
    return (lat or "emoji")[:20]


def cmd_export(args):
    from collections import Counter
    palette = load_palette()
    # уже присвоенные ключи держим стабильными (контракт для промпта агента)
    used = {e["key"] for s in palette["sets"] for e in s["emoji"] if e.get("key")}
    out, skipped = [], 0
    for s in palette["sets"]:
        for e in s["emoji"]:
            if not e.get("enabled") or e.get("missing"):
                continue
            if not e.get("meaning") or e.get("alias") in (None, "", "?"):
                skipped += 1
                continue
            key = e.get("key")
            if not key:                                  # присвоить один раз и запомнить
                base = _slug(e["meaning"]); key = base; n = 1
                while key in used:
                    n += 1; key = f"{base}_{n}"
                used.add(key); e["key"] = key
            out.append({"id": e["id"], "alias": e["alias"], "key": key, "meaning": e["meaning"]})
    save_atomic(PALETTE, palette)                        # персистим присвоенные ключи
    save_atomic(EXPORT, {"version": 1, "emoji": out})
    print(f"agent-palette.json: {len(out)} эмодзи, {len(set(x['key'] for x in out))} уникальных ключей.")
    if skipped:
        print(f"⚠ пропущено включённых без смысла/битых: {skipped}. "
              f"Запусти describe, затем export снова.")
    dups = [m for m, c in Counter(x["meaning"] for x in out).items() if c > 1]
    if dups:
        print(f"⚠ одинаковый смысл у разных эмодзи ({len(dups)}) — агент их не различит: {dups[:5]}")
    for x in out[:200]:
        print(f"  :{x['key']:<20}: {x['alias']}  {x['meaning']}")


# =================== HTML ===================
def render_html(palette):
    total = sum(len(s["emoji"]) for s in palette["sets"])
    # экранируем </ чтобы title/meaning не могли закрыть <script> (XSS/инъекция)
    data = json.dumps(palette, ensure_ascii=False).replace("</", "<\\/")
    # __TOTAL__ подставляем ПЕРВЫМ, __DATA__ — последним (данные не тронут плейсхолдеры)
    open(INDEX, "w", encoding="utf-8").write(
        HTML_TEMPLATE.replace("__TOTAL__", str(total)).replace("__DATA__", data))


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Emoji Palette Kit</title>
<style>
  :root{--bg:#0f1115;--card:#1a1d24;--tx:#e8eaed;--mut:#9aa0aa;--acc:#4f9dff;--on:#2ecc71;--bd:#2a2f3a;--nav:250px}
  @media(prefers-color-scheme:light){:root{--bg:#f4f5f7;--card:#fff;--tx:#1a1d24;--mut:#6b7280;--acc:#2563eb;--on:#16a34a;--bd:#e2e5ea}}
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.4 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx)}
  header{position:fixed;top:0;left:0;right:0;height:56px;z-index:20;background:var(--bg);border-bottom:1px solid var(--bd);padding:0 18px;display:flex;gap:12px;align-items:center}
  header h1{font-size:16px;margin:0;font-weight:600;white-space:nowrap}
  .count{color:var(--mut);font-size:13px;white-space:nowrap}
  input[type=search]{flex:1;min-width:120px;padding:8px 12px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx)}
  button{padding:8px 14px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx);cursor:pointer;font-size:14px}
  button.primary{background:var(--acc);color:#fff;border-color:var(--acc);font-weight:600}
  button:hover{filter:brightness(1.1)}
  .dirty{color:#e0a800;font-size:12px;white-space:nowrap}
  .hint{position:fixed;top:56px;left:0;right:0;z-index:15;background:var(--card);border-bottom:1px solid var(--bd);color:var(--mut);font-size:12px;padding:8px 18px}
  nav{position:fixed;top:92px;bottom:0;left:0;width:var(--nav);overflow-y:auto;border-right:1px solid var(--bd);background:var(--bg);padding:8px}
  nav .navitem{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:13px}
  nav .navitem:hover{background:var(--card)}
  nav .navitem.active{background:var(--acc);color:#fff}
  nav .av{width:24px;height:24px;object-fit:contain;border-radius:5px;background:#8883;flex:0 0 auto}
  nav .navitem .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  nav .badge{font-size:11px;background:var(--on);color:#fff;border-radius:10px;padding:1px 7px;font-weight:600}
  nav .navitem.active .badge{background:#fff3}
  nav .cnt{font-size:11px;color:var(--mut)}
  nav .navitem.active .cnt{color:#fff9}
  main{margin-left:var(--nav);margin-top:92px;padding:14px 18px 40px}
  .sethead{display:flex;align-items:center;gap:10px;margin:0 0 12px;flex-wrap:wrap}
  .sethead h2{font-size:16px;margin:0;font-weight:600}
  .sethead .mut{color:var(--mut);font-size:13px}
  .sethead button{padding:4px 10px;font-size:12px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
  .tile{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:7px}
  .tile.on{border-color:var(--on);box-shadow:0 0 0 1px var(--on) inset}
  .tile.missing{opacity:.4}
  .row{display:flex;align-items:center;gap:8px}
  .row img{width:38px;height:38px;object-fit:contain;background:#8883;border-radius:6px}
  .alias{font-size:20px}
  .sw{margin-left:auto;position:relative;width:40px;height:22px;flex:0 0 auto}
  .sw input{display:none}
  .sw label{position:absolute;inset:0;background:var(--bd);border-radius:22px;cursor:pointer;transition:.15s}
  .sw label::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;background:#fff;border-radius:50%;transition:.15s}
  .sw input:checked+label{background:var(--on)}
  .sw input:checked+label::after{transform:translateX(18px)}
  textarea{width:100%;resize:vertical;min-height:30px;padding:6px 8px;border:1px solid var(--bd);border-radius:7px;background:var(--bg);color:var(--tx);font:12px system-ui}
  .missbadge{font-size:11px;color:#e0524f}
</style></head>
<body>
<header>
  <h1>🎨 Emoji Palette Kit</h1>
  <span class="count" id="count"></span>
  <input type="search" id="q" placeholder="поиск в наборе…">
  <span class="dirty" id="dirty"></span>
  <button class="primary" id="dl">⬇ Скачать palette.json</button>
</header>
<div class="hint">Включи тумблером эмодзи, которые агент сможет использовать. <b>Смысл писать НЕ нужно</b> — он сгенерируется автоматически на шаге <code>describe</code>. Поле «смысл» заполняй только если хочешь задать свой. Скачал → замени им palette.json.</div>
<nav id="nav"></nav>
<main id="main"></main>
<script>
const P = __DATA__;
let cur = 0, dirty = false;
function markDirty(){dirty=true;document.getElementById('dirty').textContent='● не сохранено';}
function setOn(s){return s.emoji.reduce((a,e)=>a+(e.enabled?1:0),0);}
function el(t,a={},...c){const n=document.createElement(t);for(const k in a){if(k==='class')n.className=a[k];else n.setAttribute(k,a[k]);}c.forEach(x=>n.append(x));return n;}
function recount(){let on=0,tot=0;P.sets.forEach(s=>s.emoji.forEach(e=>{tot++;if(e.enabled)on++;}));document.getElementById('count').textContent=`всего ${on}/${tot}`;}
function renderNav(){const nav=document.getElementById('nav');nav.innerHTML='';P.sets.forEach((s,i)=>{const on=setOn(s);const it=el('div',{class:'navitem'+(i===cur?' active':'')});const av=(s.emoji[0]&&s.emoji[0].file)||'';if(av)it.append(el('img',{class:'av',src:av,loading:'lazy',alt:''}));it.append(el('span',{class:'nm'},s.title||s.short_name),el('span',{class:'cnt'},String(s.emoji.length)));if(on)it.append(el('span',{class:'badge'},String(on)));it.onclick=()=>{cur=i;document.getElementById('q').value='';renderNav();renderMain();window.scrollTo(0,0);};nav.append(it);});}
function renderMain(){const s=P.sets[cur];const m=document.getElementById('main');m.innerHTML='';const head=el('div',{class:'sethead'});head.append(el('h2',{},s.title||s.short_name),el('span',{class:'mut'},`${s.short_name} · ${s.emoji.length} · включено ${setOn(s)}`));const bAll=el('button',{},'вкл все');const bNone=el('button',{},'выкл все');bAll.onclick=()=>{s.emoji.forEach(e=>e.enabled=true);markDirty();renderNav();renderMain();recount();};bNone.onclick=()=>{s.emoji.forEach(e=>e.enabled=false);markDirty();renderNav();renderMain();recount();};head.append(bAll,bNone);m.append(head);const grid=el('div',{class:'grid'});s.emoji.forEach((e,ei)=>{const tile=el('div',{class:'tile'+(e.enabled?' on':'')+(e.missing?' missing':'')});tile.dataset.search=((e.meaning||'')+' '+(e.alias||'')+' '+(e.desc||'')).toLowerCase();const row=el('div',{class:'row'});row.append(el('img',{src:e.file,loading:'lazy',alt:''}),el('span',{class:'alias'},e.alias||'?'));if(e.missing)row.append(el('span',{class:'missbadge'},'нет в наборе'));const sw=el('span',{class:'sw'});const inp=el('input',{type:'checkbox'});inp.checked=e.enabled;inp.id=`c${ei}`;inp.onchange=()=>{e.enabled=inp.checked;tile.classList.toggle('on',inp.checked);markDirty();renderNav();recount();head.querySelector('.mut').textContent=`${s.short_name} · ${s.emoji.length} · включено ${setOn(s)}`;};sw.append(inp,el('label',{for:inp.id}));row.append(sw);const ta=el('textarea',{placeholder:'смысл (авто, можно оставить пустым)'});ta.value=e.meaning||'';ta.oninput=()=>{e.meaning=ta.value;markDirty();};tile.append(row,ta);grid.append(tile);});m.append(grid);applyFilter();}
function applyFilter(){const q=document.getElementById('q').value.toLowerCase();document.querySelectorAll('#main .tile').forEach(t=>{t.style.display=!q||t.dataset.search.includes(q)?'':'none';});}
document.getElementById('q').oninput=applyFilter;
document.getElementById('dl').onclick=()=>{const blob=new Blob([JSON.stringify(P,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='palette.json';a.click();dirty=false;document.getElementById('dirty').textContent='сохранено ✓';};
cur=Math.max(0,P.sets.findIndex(s=>setOn(s)>0));renderNav();renderMain();recount();
</script></body></html>"""


def cmd_init(args):
    envp = os.path.join(HERE, ".env")
    if os.path.exists(envp):
        print(".env уже есть — не трогаю.")
    else:
        open(envp, "w", encoding="utf-8").write(ENV_TEMPLATE)
        print("создан .env — впиши ключи (TG_API_ID/HASH, OPENROUTER_API_KEY).")
    gip = os.path.join(HERE, ".gitignore")
    if not os.path.exists(gip):
        open(gip, "w", encoding="utf-8").write(GITIGNORE_TEMPLATE)
        print("создан .gitignore (исключит .env и tg_session из git).")
    print(f"Дальше: заполни .env, потом  python {os.path.basename(__file__)} fetch")


def cmd_snippet(args):
    outp = os.path.join(HERE, "agent_emoji.py")
    open(outp, "w", encoding="utf-8").write(AGENT_SNIPPET)
    print(f"Код вставки эмодзи записан в {outp}.")
    print("Скопируй resolve_emoji()/emoji_menu() в свой агент; ему нужен agent-palette.json.")


def main():
    load_env()
    ap = argparse.ArgumentParser(description="Emoji Palette Kit — палитра кастом-эмодзи для ИИ-агента")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="создать .env и .gitignore (первый шаг)")
    f = sub.add_parser("fetch", help="вытянуть установленные наборы эмодзи + собрать index.html")
    f.add_argument("sets", nargs="*", help="конкретные short_name (по умолчанию — все установленные)")
    d = sub.add_parser("describe", help="авто-описать включённые эмодзи через vision-AI")
    d.add_argument("--all", action="store_true", help="переописать даже те, где смысл уже есть")
    sub.add_parser("export", help="собрать agent-palette.json для агента")
    sub.add_parser("snippet", help="выгрузить код вставки эмодзи (agent_emoji.py) для твоего агента")
    args = ap.parse_args()
    {"init": cmd_init, "fetch": cmd_fetch, "describe": cmd_describe,
     "export": cmd_export, "snippet": cmd_snippet}[args.cmd](args)


if __name__ == "__main__":
    main()
