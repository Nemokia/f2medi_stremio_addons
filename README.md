# F2Medi Stremio Addon

> افزودنی (Addon) جستجوی زنده فیلم و سریال برای [Stremio](https://www.strem.io/) — لینک‌های دانلود سایت **f2medi.top** را به استریم‌های قابل پخش داخل Stremio تبدیل می‌کند.
>
> Live search add-on that resolves movies & series from f2medi.top into Stremio streams. Version **3.0.0** · Python · FastAPI

---

## فهرست مطالب

- [معرفی](#معرفی)
- [نحوه کارکرد](#نحوه-کارکرد)
  - [جریان کلی](#جریان-کلی)
  - [Endpointها](#endpointها)
  - [مراحل کشف محتوا (Discovery)](#مراحل-کشف-محتوا-discovery)
  - [امتیازدهی و گیت‌های تصمیم](#امتیازدهی-و-gateهای-تصمیم)
  - [اعتبارسنجی صفحه](#اعتبارسنجی-صفحه)
  - [پارس محتوا](#پارس-محتوا)
  - [شکل خروجی Stream](#شکل-خروجی-stream)
  - [کش (Cache)](#کش-cache)
  - [کلاینت HTTP مشترک](#کلاینت-http-مشترک)
- [ساختار پروژه](#ساختار-پروژه)
- [نصب و راه‌اندازی](#نصب-و-راهاندازی)
- [اتصال به Stremio](#اتصال-به-stremio)
- [تنظیمات (متغیرهای محیطی)](#تنظیمات-متغیرهای-محیطی)
- [اجرا و تست](#اجرا-و-تست)
- [رفع اشکال (Troubleshooting)](#رفع-اشکال-troubleshooting)
- [نکات توسعه](#نکات-توسعه)
- [سلب مسئولیت](#سلب-مسئولیت)

---

## معرفی

این پروژه یک **افزودنی Stream** برای Stremio است که کاملاً با پایتون نوشته شده و هیچ دیتابیس یا کاتالوگ از پیش ذخیره‌شده‌ای ندارد؛ به‌جای آن، هنگام هر درخواست کاربر:

1. متادیتای فیلم/سریال (نام، سال، شناسه IMDb) را از **Cinemeta** (افزودنی رسمی Stremio) می‌گیرد؛
2. با یک خط لولهٔ چندمرحله‌ای (جستجوی WordPress REST → اسلاگ مستقیم → سرچ داخلی سایت و DuckDuckGo) صفحهٔ محتوای همان اثر را در **f2medi.top** پیدا می‌کند؛
3. صحت صفحه را با چند سیگنال (عنوان، سال، ID ایم‌دی‌بی، ساختار HTML) اعتبارسنجی و امتیازدهی می‌کند؛
4. لینک‌های دانلود داخل صفحه را با کیفیت، زبان (دوبله فارسی / زیرنویس چسبیده)، فصل و قسمت جدا کرده و در قالب استاندارد Stremio برمی‌گرداند.

ویژگی‌های کلیدی:

- 🔎 **کشف زنده و دقیق**: امتیازدهی وزن‌دار چندعاملی + گیت‌های سخت‌گیرانه تا صفحهٔ اشتباه هرگز برنگردد.
- 🛡 **امنیت URL**: همهٔ آدرس‌ها قبل از هر fetch از فیلتر allowlist دامنه عبور می‌کنند (ضد SSRF).
- 🧠 **کش دوگانه**: مثبت (۶ ساعت) و منفی (۱۰ دقیقه) برای حداقل‌کردن درخواست تکراری به سایت.
- 🇮🇷 **فارسی‌آware**: یکسان‌سازی حروف عربی/فارسی، ارقام فارسی، فصل‌های «فصل اول/دوم/…» و پسوندهای تبلیغاتی در عنوان‌ها.
- 🚫 **بدون dependency سنگین**: فقط FastAPI، requests و BeautifulSoup.

---

## نحوه کارکرد

### جریان کلی

```
Stremio
   │  GET /stream/{movie|series}/tt….json
   ▼
FastAPI (main.py)
   │  ۱) meta (name/year) از Cinemeta: v3-cinemeta.strem.io
   │  ۲) فراخوانی F2MediaResolver.resolve(title, type, imdb_id, year)
   ▼
F2MediaResolver                       (resolvers/f2medi_resolver.py)
   │  بررسی کش مثبت/منفی
   ▼
Discovery (تنبل —Lazy— مرحله بعد فقط وقتی مرحله قبل چیزی تأییدنشده نداد)
   ├─ ① جستجوی WordPress REST (/wp-json/wp/v2/search) با variantهای کوئری
   ├─ ② اسلاگ مستقیم (فقط سریال‌ها — URL فیلم عدد نامحدوس دارد)
   └─ ③ سرچ داخلی سایت (?s=…) و سپس DuckDuckGo (site:f2medi.top …)
   ▼
Ranking + Gates (matcher.py)   ←→   Fetch + Validation (validator.py)
   │  بهترين كانديدِ تأييدشده (HTML)
   ▼
parse_f2media_page (parsers/f2medi_parser.py)
   │  ليست ParsedStream (کیفیت، URL، فصل/قسمت، زبان)
   ▼
{"streams": […]}  به Stremio برمی‌گردد
```

### Endpointها

| مسیر | توضیح |
|---|---|
| `GET /` | Health check — وضعیت سرویس |
| `GET /manifest.json` | مانیفست افزودنی (`id`: `org.f2medi.stremio`) |
| `GET /stream/{type}/{id}.json` | منبع اصلی؛ `type` یکی از `movie` یا `series` |

فرمت `id`:

- فیلم: `tt0111161` (شناسه IMDb)
- سریال: `tt10986410:S:E` مثل `tt10986410:2:5` → فصل ۲ قسمت ۵ (اعداد با صفر پیشوند هم پذیرفته می‌شود)

نمونه:

```bash
curl http://127.0.0.1:8081/
curl http://127.0.0.1:8081/manifest.json
curl "http://127.0.0.1:8081/stream/movie/tt0111161.json"
curl "http://127.0.0.1:8081/stream/series/tt10986410:2:5.json"
```

اگر Cinemeta متادیتایی برنگرداند یا هیچ کاندیدی اعتبارسنجی را رد نکند، پاسخ `{"streams": []}` است — سرویس **هرگز exception به Stremio برنمی‌گرداند**.

### مراحل کشف محتوا (Discovery)

بوت‌strap اصلی کلاس `F2MediaResolver` است. سفارش مراحل عمداً «ارزان به گران» است و یک generator تنبل از `resolvers/f2medi_resolver.py:_discovery_stages` ترتیب اجرا را کنترل می‌کند:

1. **WordPress REST** — پایدارترین کانال. روی `/wp-json/wp/v2/search` با `subtype=post` (فیلم) یا `subtype=series` (سریال) جستجو می‌کند، `per_page=8`. موتور جستجوی سایت به علائم نگارشی حساس است («Avengers: Endgame» نتیجه نمی‌دهد ولی «Avengers Endgame» بله)، بنابراین `utils/query_variants.py` به‌ترتیب قطعی این variantها را می‌سازد:
   1. عنوان اصلی
   2. عنوان بدون علائم نگارشی (اگر با مورد ۱ متفاوت باشد)
   3. عنوان بدون علائم + سال (اگر سال داشته باشیم)

   فقط اگر *همه* کوئری‌های typed خالی بودند، یک بار شبکهٔ امنیتی **untyped** اجرا می‌شود.
2. **Direct slug** — فقط سریال؛ چون URL فیلم‌ها پیشوند عددی غیرقابل حدس دارد (`/3010/slug/`). الگوها: `{slug}` , `{slug}-series`, `z{slug}-series`, `{slug}-tv`, `{slug}-tv-series`.
3. **Search fallback** (`search_fallback.py`) — اول سرچ داخلی سایت `/?s=<title>` و بعد DuckDuckGo HTML با کوئری `site:f2medi.top …`؛ حداکثر ۶ نتیجه از هر کانال. شکست DDG تحمل می‌شود و هرگز resolver را نمی‌شکند.

نکته‌های مهم پیاده‌سازی:

- **Dedupe کل استخر کاندید** بین همهٔ مراحل و variantها بر اساس `wp_id` وگرنه URL انجام می‌شود؛ هیچ صفحه‌ای دو بار fetch نمی‌شود.
- **بودجه درخواست**: در هر resolve حداکثر `_MAX_CANDIDATES_FETCH = 4` صفحه fetch و validate می‌شود؛ اگر بهترین امتیاز ≥ `_STOP_EARLY_SCORE` (0.85) شد، بلافاصله خارج می‌شود.

### امتیازدهی و Gateهای تصمیم

در `resolvers/matcher.py` هر کاندید دو بار امتیاز می‌گیرد: قبل از fetch (از متادیتای WP و شکل URL) و بعد از fetch (با شواهد واقعی صفحه). وزن‌ها:

| سیگنال | وزن | منبع شواهد |
|---|---|---|
| title | **0.45** | شباهت عنوان normalizeشدهٔ کوئری با عنوان WP/صفحه |
| type | 0.25 | تطابق movie/series |
| year | 0.15 | سال صفحه نسبت به سال Cinemeta |
| imdb | 0.10 | وجود `tt…` همین اثر در HTML صفحه |
| url | 0.05 | قالب مسیر (/movie/series regex) |

قواعد سخت (Hard gates):

- `type_match` باید **دقیقاً 1.0** باشد و `title_match ≥ 0.40` وگرنه کاندید حتی fetch هم نمی‌شود.
- بعد از fetch، مجموع باید ≥ `MIN_TOTAL_ACCEPT = 0.50` باشد.
- اختلاف سال ±۱ سال = امتیاز 0.5 (اختلاف رایج تاریخ انتشار).
- اگر صفحه به IMDB **اثر دیگری** لینک داده باشد، علاوه بر صفرشدن امتیاز imdb، امتیاز title هم ×0.6 می‌شود (وتوی قطعی).
- شباهت عنوان با الگوریتم مقاوم به متن دوزبانه: چون عنوان‌های سایت داخل متن تبلیغاتی فارسی هستند («دانلود سریال تد لاسو Ted Lasso…»)، اول runs لاتین استخراج و سپس `SequenceMatcher` + قانون containment (شامل‌بودن ⇒ حداقل 0.85) اعمال می‌شود.

نرمال‌سازی متن (`utils/normalization.py`): NFKC، lowercase، یکسان‌سازی ي/ی ك/ک أ/آ و… ، حذف zero-width و کشیده، همهٔ انواع خط‌تیره، حذف سال و پسوندهای کیفی/تبلیغاتی (`dubbed`, `hardsub`, `1080p`, `sansur`, `bedone`, `zirnevis`, …) — اما نه آنقدر تهاجمی که دو اثر متفاوت یکی شوند.

### اعتبارسنجی صفحه

سایت برای URLهای ناموجود 404 نمی‌دهد بلکه 301 به `/profile/` می‌زند؛ پس وضعیت HTTP به‌تنهایی بی‌معناست. `validators.validate_content_page` (فایل `resolvers/validator.py`) به‌ترتیب این‌ها را چک می‌کند:

1. status == 200
2. فرود روی صفحات `/profile` , `/login` , `/wp-login` , `/register`
3. صفحهٔ چالش Cloudflare («Just a moment», `cf-chl`, …)
4. طول بدنه ≥ ۵۰۰ بایت
5. نشانهٔ لاگین در `<title>`
6. **ساختار Download درست برای نوع درخواستی**:
   - سریال: وجود `.download-season`
   - فیلم: وجود `.download-list` دارای `a.btn-download` **و نبود** `.download-season`
7. اگر `<link rel="canonical">` با URL نهایی فرق کند و نوع مسیرش بخورد → صفحه canonical دوباره fetch و validate می‌شود.
8. عنوان (`h1.entry-title` یا `<title>`) و سال برای امتیازدهی نهایی استخراج می‌شود.

### پارس محتوا

`parsers/f2medi_parser.py` (بدون هیچ دسترسی شبکه) روی HTMLِ validateشده:

- **فیلم**: بلاک‌های `.download-list.dubbled` (دوبله) و `.download-list.hardsub` (زیرنویس چسبیده)؛ هر `<li>` شامل لیبل کیفیت در `span.text[dir="ltr"]` و لینک دانلود `a.btn-download`.
- **سریال**: گروه‌های `.download-season`؛ هر دکمهٔ `button[data-bs-target]` به باکس فصل اشاره می‌کند؛ داخل باکس هر `li.bg-body` یک ردیف کیفیت است و در `.series-downloaditems .d-flex` هر بلاک قسمت، **آخرین anchor** لینک واقعی دانلود است («قسمت NN»).
- شمارهٔ فصل از برچسب دکمه استخراج می‌شود: «فصل ۲»، ارقام فارسی (۰–۹) و اعداد ترتیبی فارسی تا «پانزدهم».
- متادیتای جانبی: پوستر (`figure.entry-poster img`)، توضیحات (`.entry-excerpt p`)، امتیاز IMDb (اولین strong لینک‌شده به imdb.com)، ژانرها (`.entry-genres a`).

### شکل خروجی Stream

در `main.py` خروجی پارسر به فرمت Stremio تبدیل و فیلتر می‌شود:

- برای سریال فقط ردیف‌هایی که فصل/قسمتشان با درخواست مطابق است (زیر ۱۰٫یعنی `02` سازگار).
- لینک‌های `.mka` (فایل صوتی جدا) حذف می‌شوند.
- نام هر stream ثابت `F2Medi` است و description برابر `کیفیت + 🎤 دوبله فارسی / 📝 زیرنویس چسبیده`.
- `behaviorHints.notWebReady = true` (پخش‌کننده خارجی لازم است) و `bingeGroup` برای گروه‌بندی کیفیت/زبان.

```json
{
  "streams": [
    {
      "name": "F2Medi",
      "description": "WEB-DL 1080p\n🎤 دوبله فارسی",
      "url": "https://…/movie.mkv",
      "behaviorHints": {
        "notWebReady": true,
        "bingeGroup": "f2medi-WEB-DL 1080p-Dubbed"
      }
    }
  ]
}
```

### کش (Cache)

`utils/cache.py` یک TTL + LRU thread-safe است.

| کش | TTL | ظرفیت | نقش |
|---|---|---|---|
| مثبت | ۶ ساعت | ۴۸ ورودی | نتیجهٔ موفق: `found=True` + HTML صفحه |
| منفی | ۱۰ دقیقه | ۲۵۶ ورودی | جلوگیری از هجوم مکرر به عنوان‌های نبوده (وقتی محتوا بعداً منتشر شود سریع دوباره چک می‌شود) |

کلید: `f2medi:{type}:{imdb_id}:{year}:{normalized_title}`. خطاهای کش swallow می‌شوند و هرگز باعث شکست resolve نمی‌شوند.

### کلاینت HTTP مشترک

`httpclient/client.py` یک Session-based client با connection pooling است (`pool_connections=4`, `pool_maxsize=8`) که **فقط خطاهای گذرا را retry می‌کند**:

- Statuses قابل retry: `408, 429, 500, 502, 503, 504` (+ احترام به هدر `Retry-After` تا سقف ۶۰ ثانیه)
- Exceptionهای قابل retry: ConnectionError / Timeout / ChunkedEncodingError
- Backoff نمایی: `1.5^(n−1)` سانیه، سقف ۳۰ ثانیه، پیش‌فرض ۳ بار
- Timeout تفکیک‌شده: connect ۸s / read ۱۵s (قابل تغییر)
- 400/401/403/404 دوباره امتحان نمی‌شوند (fail-fast)
- پس از اتمام retryها `HttpError` پرتاب می‌شود که بالادست همیشه catch شده است.

خروجی JSON همهٔ APIهای سایت با BOM شروع می‌شود؛ همه پارس‌ها الزاماً از `httpclient/json_utils.py` (UTF‑8‑sig tolerant) عبور می‌کنند.

---

## ساختار پروژه

```
fardabin_stremio_addons/
├── main.py                     # ورودی FastAPI: manifest + stream + health (+ playing_hook برای GUI)
| `gui.py`                      # پنل کنترل **Native Windows (tkinter)**: Connect/Disconnect + لاگ زنده + عنوان در حال پخش
| `gui_backend.py`              # سرور کنترل داخلی WSL (FastAPI روی پورت 9090) — توسط gui.py فراخوانی می‌شود
├── F2Media.bat                 # لانچر ویندوز: بدون پنجره CMD، با pythonw اجرا می‌شود
├── requirements.txt            # fastapi, uvicorn, requests, beautifulsoup4, urllib3
│
├── httpclient/                 # زیرساخت شبکه
│   ├── client.py               # HttpClient + HttpClientConfig + HttpError (retry گذرا)
│   └── json_utils.py           # پارس JSON مقاوم به UTF-8 BOM
│
├── resolvers/                  # هستهٔ تصمیم
│   ├── models.py               # dataclassها: SearchCandidate, CandidateScore, ResolverResult, ParsedStream, F2MediaPage
│   ├── url_policy.py           # BASE_URL, ALLOWED_HOSTS, ریگکس مسیر فیلم/سریال، ضدSSRF (safe_fetch_url)
│   ├── wordpress_resolver.py   # کشف از WP REST API (+ نگاشت movie↔post / series↔series)
│   ├── direct_resolver.py      # تولید اسلاگ مستقیم — فقط سریال (fallback)
│   ├── search_fallback.py      # سرچ داخلی سایت + DuckDuckGo — آخرین fallback
│   ├── matcher.py              # امتیازدهی prefetch/postfetch + hard gates
│   ├── validator.py            # اعتبارسنجی صفحه (Cloudflare/login-wall/structure/canonical)
│   ├── f2medi_resolver.py      # Facade اصلی: orchestration مراحل + کش
│   └── __init__.py             # خروجی عمومی پکیج
│
├── parsers/
│   └── f2medi_parser.py        # HTML → F2MediaPage (استخراج streamها؛ بدون شبکه)
│
├── utils/
│   ├── normalization.py        # نرمال‌سازی فارسی/لاتین، extract_year, slugify
│   ├── query_variants.py       # variantهای قطعی کوئری جستجو
│   └── cache.py                # TTLCache (+LRU) thread-safe
│
├── tests/                      # ۱۱۶ تست offline (unittest)
│   ├── test_integration_live.py# تست‌های زندهٔ end-to-end (پیش‌فرض skip؛ F2MEDIA_LIVE=1)
│   ├── test_resolver_flow.py   # ترتیب fallback، dedupe، بودجهٔ fetch، کش
│   ├── test_matcher.py         # امتیازدهی و rejectها
│   ├── test_validator.py       # wallها، cloudflare، structure، canonical
│   └── …                       # http_client, json_utils, url_policy, normalization, query_variants, wordpress_resolver, direct_and_cache
│
├── *.html                      # فیکسچرهای ذخیره‌شده برای دیباگ دستی (Toy Story 5, Shawshank, president-curtis)
├── venv/                       # virtualenv لوکال
└── .gitignore
```

---

## نصب و راه‌اندازی

### پیش‌نیازها

| مورد | نسخه |
|---|---|
| Python | **3.10+** (تست‌شده روی 3.12) |
| pip | همراه پایتون |
| Git | برای clone مخزن |
| شبکه | دسترسی به `f2medi.top` و `v3-cinemeta.strem.io` |

### گام ۱ — دریافت کد

```bash
git clone git@github.com:Nemokia/f2medi_stremio_addons.git
cd f2medi_stremio_addons
```

### گام ۲ — ساخت محیط مجازی و نصب وابستگی‌ها

```bash
python3 -m venv venv
source venv/bin/activate          # لینوکس / macOS
# venv\Scripts\activate           # ویندوز

pip install -r requirements.txt
```

وابستگی‌ها فقط این‌ها هستند: `fastapi`, `uvicorn`, `requests`, `beautifulsoup4`, `urllib3`.

### گام ۳ — اجرای سرور

**راه ساده (پنجره گرافیکی):**

```bash
./venv/bin/python gui.py
```

یک تب مرورگر باز می‌شود (http://localhost:9090) با سه چیز:

- دکمه **Connect** → سرور addon روی `0.0.0.0:8081` بالا می‌آید و Stremio خودکار باز می‌شود
- دکمه **Disconnect** → سرور متوقف می‌شود
- نام فیلم/سریالی که همین لحظه از addon درخواست شده، لحظه‌به‌لحظه زیر دکمه‌ها

از ویندوز هم بدون ترمینال: دابل‌کلیک روی `F2Media.bat`.

**راه ترمینالی:**

```bash
python main.py
```

سرور روی `http://127.0.0.1:8081` بالا می‌آید. صحت را بررسی کنید:

```bash
curl http://127.0.0.1:8081/
# {"status":"ok","addon":"F2Medi","version":"3.0.0"}
```

برای اجرا با پارامتر دلخواه (بدون تغییر فایل main) می‌توانید uvicorn را مستقیم صدا بزنید:

```bash
uvicorn main:app --host 127.0.0.1 --port 8081 --reload   # --reload فقط برای توسعه
```

### (اختیاری) Exposing روی شبکه

پنل (gui.py) خودش addon را روی `0.0.0.0:8081` بالا می‌آورد — از دستگاه دیگری (اندروید/تلویزیون) آدرس `http://<IP-سرور>:8081/manifest.json` را در Stremio نصب کنید.

اگر سرور را با `python main.py` اجرا می‌کنید، پیش‌فرض localhost است؛ برای دسترسی شبکه:

- یا در `main.py` مقدار `host="127.0.0.1"` را به `host="0.0.0.0"` تغییر دهید؛
- یا: `uvicorn main:app --host 0.0.0.0 --port 8081`

سپس در Stremio آدرس `http://<IP-سرور>:8081/manifest.json` را نصب کنید.

> ⚠️ باز کردن `0.0.0.0` یعنی هرکسی در شبکه می‌تواند درخواست بزند؛ برای اینترنت عمومی حتماً پشت reverse proxy با احراز هویت یا محدودسازی IP قرار دهید.

### اتصال به Stremio

**خودکار:** بعد از Connect در پنل (gui.py)، Stremio خودش باز می‌شود و مانیفست را می‌گیرد — نیازی به مراحل زیر نیست.

**دستی:**

1. Stremio را باز کنید → **Add-ons** → نوار جستجو (pencil icon).
2. آدرس مانیفست را paste کنید:
   ```
   http://127.0.0.1:8081/manifest.json
   ```
   (روی همان سیستمی که سرور اجراست. برای دستگاه دیگر به‌جای 127.0.0.1، IP سرور.)
3. Enter → افزونهٔ **F2Medi** ظاهر می‌شود → Install.
4. هر فیلم/سریالی را جستجو و انتخاب کنید؛ streamهایی با نام «F2Medi» و برچسب 🎤 دوبله فارسی یا 📝 زیرنویس چسبیده نمایش داده می‌شوند.

> چون خروجی `notWebReady: true` است، Stremio ممکن است برای پخش، play با player خارجی را پیشنهاد دهد — طبیعی است (لینک‌ها دانلودی هستند).

## تنظیمات (متغیرهای محیطی)

همهٔ تنظیمات اختیاری‌اند و توسط `HttpClientConfig.from_env()` خوانده می‌شوند:

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `F2MEDIA_USER_AGENT` | UA کروم ۱۳۱ | User-Agent ارسالی به سایت |
| `F2MEDIA_TIMEOUT` | `15.0` | ثانیهٔ read-timeout |
| `F2MEDIA_MAX_RETRIES` | `3` | حداکثر تلاش برای خطاهای گذرا |
| `F2MEDIA_VERIFY_SSL` | `true` | با `0/false/off` خاموش می‌شود (فقط برای شبکه‌های پروکسی‌دار؛ با احتیاط) |

نمونهٔ استفاده:

```bash
F2MEDIA_TIMEOUT=25 F2MEDIA_MAX_RETRIES=2 python main.py
```

> مقادیر ثابت خط لوله هم در بالای `resolvers/f2medi_resolver.py` و `resolvers/matcher.py` قابل تنظیم‌اند:
> `_POSITIVE_TTL=6h`, `_NEGATIVE_TTL=600s`, `_MAX_CANDIDATES_FETCH=4`, `_STOP_EARLY_SCORE=0.85`,
> `MIN_TITLE_SCORE_PREFETCH=0.40`, `MIN_TOTAL_ACCEPT=0.50`.

## اجرا و تست

سوئیت کامل تست‌ها offline و سریع (< ۱ ثانیه):

```bash
python -m unittest discover -s tests -v
```

خروجی مورد انتظار: `Ran 116 tests … OK (skipped=4)` — چهار skip مربوط به تست‌های زنده است.

تست‌های یکپارچهٔ زنده (درخواست واقعی به f2medi.top؛ Ted Lasso، Shawshank Redemption، Infinity War، Endgame):

```bash
F2MEDIA_LIVE=1 python -m unittest tests.test_integration_live -v
```

منوآل end-to-end بدون تست:

```bash
curl "http://127.0.0.1:8081/stream/movie/tt0111161.json" | python -m json.tool
```

## رفع اشکال (Troubleshooting)

**هیچ streamی برنمی‌گردد**
- لاگ را نگاه کنید؛ مسیر `[WP] → [MATCH] → [F2M]` مشخص می‌کند مشکل کجاست:
  - `[CINEMETA] request failed` → دسترسی به `v3-cinemeta.strem.io` را چک کنید.
  - `[WP] search status=…` یا همهٔ مراحل `no candidates` → احتمالاً عنوان در سایت نیست یا WP API موقتاً پاسخ نمی‌دهد.
  - `cloudflare challenge` → سایت مقابل IP سرور شما چالش گذاشته؛ با UA سفارشی (`F2MEDIA_USER_AGENT`) یا خروجی متفاوت امتحان کنید.
- فرمت id را چک کنید: `tt10986410:2:5.json` نه `tt10986410-2-5`.
- فصل/قسمت درخواستی باید دقیقاً روی سایت موجود باشد؛ پشت کش منفی ۱۰ دقیقه‌ای صبر کنید یا سرویس را restart کنید.

**خطای SSL در شبکه‌های پروکسی‌دار**

```bash
F2MEDIA_VERIFY_SSL=false python main.py     # فقط در محیط قابل اعتماد!
```

**دامنهٔ سایت عوض شد**

این افزونه تا امروز دو مهاجرت دامنه را از سر گذرانده (`film2media.top` ← `fardabin.top` ← `f2medi.top`). پس از مهاجرت بعدی فقط دو ثابت زیر را در `resolvers/url_policy.py` به‌روز کنید:

```python
BASE_URL = "https://www.f2medi.top"
ALLOWED_HOSTS = frozenset({"f2medi.top", "www.f2medi.top"})
```

سلکتورهای HTML نیز ممکن است تغییر کنند؛ یک صفحهٔ نمونه ذخیره کنید و `resolvers/validator.py` + `parsers/f2medi_parser.py` را مطابق آن تنظیم کنید.

**Port busy** — نمونهٔ دیگری روی ۸۰۸۱ روشن است؟ با `lsof -i :8081` پیدا و ببندیدش، یا با uvicorn port دلخواه بدهید: `uvicorn main:app --port 9090`.

**پنل باز نمی‌شود / مرورگر باز نشد** — gui.py خودش تب مرورگر باز می‌کند؛ اگر نشد، دستی به `http://localhost:9090/` بروید. پورت پنل 9090 است و addon روی 8081 — هردو باید آزاد باشند.

## نکات توسعه

- **قواعد معماری که هنگام توسعه باید حفظ شوند:**
  - بین ماژول‌ها فقط dataclass تایپ‌شده جابه‌جا می‌شود (`resolvers/models.py`)، نه dict آزاد.
  - هر URL پیش از fetch باید از `safe_fetch_url()` عبور کند؛ این تنها نقطهٔ کنترل ضدSSRF است.
  - هر پاسخ JSON باید از `json_utils.parse_json_response` برود (پاسخ‌های سایت BOM دارند).
  - resolver و parser هیچ‌وقت exception به بالا پرتاب نمی‌کنند؛ شکست یعنی `found=False` یا `streams=[]`.
  - تست‌های واحد باید بدون شبکه سبز شوند؛ تعامل HTTP mock می‌شود.
- **افزودن منبع جدید محتوا**: یک discovery تولیدکنندهٔ `list[SearchCandidate]` بسازید و در `_discovery_stages` (به‌ترتیب هزینه) اضافه کنید؛ امتیازدهی/اعتبارسنجی/کش خودکار روی آن اعمال می‌شود.
- فایل‌های `.html` روت پروژه، صفحات واقعی ذخیره‌شده برای عیب‌یابی دستی سلکتورها هستند؛ سلکتور جدید را اول روی آن‌ها راستی‌آزمایی کنید.

## سلب مسئولیت

- این پروژه صرفاً یک **لینک‌یاب** است؛ هیچ محتوایی هاست نمی‌کند و تمام لینک‌ها متعلق به سایت منبع هستند.
- قالب سلکتورها به HTML فعلی `f2medi.top` وابسته است و با هر redesign سایت باید به‌روز شود.
- مخزن فعلاً فایل LICENSE ندارد؛ استفاده شخصی/آموزشی توصیه می‌شود.

---

<div align="center">

**F2Medi Stremio Addon · v3.0.0**

</div>

