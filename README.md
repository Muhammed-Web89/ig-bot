# Instagram Auto DM Botu

Reels videolariniza belirli anahtar kelimelerle yorum yapan kullanicilara otomatik DM gonderen, kuyruk tabanli ve anti-spam onlemli bir Python sistemi.

## Teknolojiler

- Python 3.11+
- FastAPI (webhook sunucusu)
- arq + Redis (asenkron kuyruk)
- httpx (async HTTP client)
- pydantic-settings, tenacity, structlog

## Onemli API Kisitlamalari

1. **Instagram yorumlari icin dogrudan webhook yoktur.** Bu projede Facebook Page Webhooks'un `instagram_feed` event'leri varsayilmistir. Calismazsa polling (düzenli cekme) kullanmaniz gerekir.
2. **"X beni takip ediyor mu?" sorgusu yoktur.** Cozum: kendi takipci listenizi Graph API ile cekip Redis'te onbelleklemek. Büyük hesaplarda bu pratik degildir; o durumda "önce takip et, sonra TAMAM yaz" iki adimli akisi önerilir.
3. **Private Reply** sayesinde yoruma yanit olarak 7 gün icinde DM gönderilebilir.

## Kurulum

1. Gerekli paketleri yükleyin:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Redis baslatin:

```bash
brew install redis
brew services start redis
```

3. `.env.example` dosyasini `.env` olarak kopyalayin ve Meta bilgilerinizi doldurun.

4. Uygulamayi calistirin (iki terminal):

```bash
# Terminal 1: Webhook sunucusu
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: arq worker
arq app.workers.WorkerSettings
```

5. Webhook'unuzu disari acin (`ngrok` veya sunucu):

```bash
ngrok http 8000
```

Sonra `https://sizin-adresiniz.ngrok.io/webhook/instagram` adresini Meta for Developers üzerinden webhook olarak kaydedin.

## Vercel Deployment

Vercel kullanacaksaniz:

1. Repo'yu Vercel'e import edin.
2. Vercel project settings icinde su environment variables'lari tanimlayin:

```text
META_APP_SECRET
META_PAGE_ACCESS_TOKEN
META_PAGE_ID
INSTAGRAM_ACCOUNT_ID
VERIFY_TOKEN
REDIS_URL
```

3. `REDIS_URL` icin Redis Cloud, Upstash veya benzeri bir dis servis kullanin. `redis://localhost:6379/0` Vercel icin uygun degildir.
4. Deploy sonrasi webhook adresi olarak uygulamanin root domain'ini kullanin; `vercel.json` tum rotalari FastAPI uygulamasina yonlendirir.

## Yapilandirma

`.env` icerisinde ayarlanabilir anahtarlar:

- `KEYWORDS`: Virgulle ayrilmis tetikleyici kelimeler
- `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS`: DM gonderimleri arasi rastgele bekleme
- `FOLLOWER_CACHE_TTL_SECONDS`: Takipci onbellek süresi
- `WELCOME_MESSAGE`: Takip etmeyen kullaniciya giden mesaj
- `CONTENT_MESSAGE`: Takip eden kullaniciya giden mesaj

## Klasor Yapisi

```text
ig-bot/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── meta_client.py
│   ├── followers.py
│   ├── models.py
│   └── workers.py
├── .env.example
├── requirements.txt
└── README.md
```

## Meta for Developers Adimlari (Özet)

1. [developers.facebook.com](https://developers.facebook.com)'da Business tipinde uygulama olusturun.
2. Instagram Graph API ve Instagram Messaging API ürünlerini ekleyin.
3. Instagram hesabinizi Business/Creator hesabina cevirin ve bir Facebook Sayfasi'na baglayin.
4. Sayfa erisim token'i (Page Access Token) alin.
5. Webhooks bölümünden `instagram_feed` aboneligini aktif edin.
6. Verify Token ve Webhook URL'nizi girin.

## Anti-Spam Önlemleri

- Her DM öncesinde 20-50 saniye arasi rastgele gecikme
- Ayni anda en fazla 5 is (max_jobs=5)
- Rate-limit durumunda exponential backoff ile retry
- Takipci listesi onbelleklenir (cache TTL)

## Not

Bu sistem test ortaminda küçük ölçekte denenmelidir. Instagram ve Meta politikalarinin zaman icinde degisebilecegini unutmayin.
