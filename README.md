# 🤫 Sottovoce

> **Telegram Mini App di confessioni anonime con Tribunale satirico AI (Giudice, Difesa e Accusa) e Privacy-First by Design.**  
> *Architettura cloud-native serverless basata su FastAPI, Neon PostgreSQL, Upstash Redis e deployment su Vercel.*

[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.159+-009688.svg)](https://fastapi.tiangolo.com/)
[![AI](https://img.shields.io/badge/AI-DeepSeek-4D6BFE.svg)](https://deepseek.com/)
[![Database](https://img.shields.io/badge/Database-Neon%20PostgreSQL-00E599.svg)](https://neon.tech/)
[![Cache & Rate Limit](https://img.shields.io/badge/Cache-Redis-DC382D.svg)](https://redis.io/)
[![Styling](https://img.shields.io/badge/Styling-Tailwind%20CSS%20v4-38B2AC.svg)](https://tailwindcss.com/)
[![Deploy](https://img.shields.io/badge/Deploy-Vercel-black.svg)](https://vercel.com/)
[![Telegram](https://img.shields.io/badge/Telegram-Mini%20App%20SDK-2CA5E0.svg)](https://core.telegram.org/bots/webapps)
[![uv](https://img.shields.io/badge/managed%20by-uv-261230.svg)](https://astral.sh/uv)

---

## 📑 Indice

1. [Panoramica del Progetto](#-1-panoramica-del-progetto)
2. [Requisiti di Sistema](#-2-requisiti-di-sistema)
3. [Architettura di Autenticazione e Privacy](#-3-architettura-di-autenticazione-e-privacy)
4. [Pipeline di Moderazione e Sicurezza (Content Governance)](#-4-pipeline-di-moderazione-e-sicurezza-content-governance)
5. [Schema del Database (SQLModel / Neon PostgreSQL)](#-5-schema-del-database-sqlmodel--neon-postgresql)
6. [Stack Tecnologico](#-6-stack-tecnologico)
7. [Guida Rapida & Setup Locale](#-7-guida-rapida--setup-locale)
8. [Architettura Serverless & Deploy su Vercel](#-8-architettura-serverless--deploy-su-vercel)
9. [Disclaimer Legale](#-9-disclaimer-legale)

---

## 💡 1. Panoramica del Progetto

**Sottovoce** (concept: *DisagioLab*) è una piattaforma di confessioni anonime interattiva concepita come applicazione ibrida:

- 🌐 **Web App Classica**: Accessibile via browser desktop/mobile tramite autenticazione Telegram.
- 📱 **Telegram Mini App (TMA)**: Integrata nativamente nell'ecosistema di Telegram tramite Bot (`aiogram`) e iframe dedicato.

Il sistema unisce un feed di post anonimi a un motore di intelligenza artificiale che funge da **"Giudice Bastardo"** (roast automatico e sarcastico), supportato da reazioni interattive, sondaggi live via **HTMX** e catene di gossip.

---

## 🎯 2. Requisiti di Sistema

### 2.1 Requisiti Funzionali
- **Invio Confessioni:** Inserimento di testo anonimo con opzione di sondaggio binario allegato (Opzione A vs Opzione B).
- **Triage e Roast IA:** Analisi automatica del testo tramite LLM (LangChain / LangGraph) per triage di sicurezza, moderazione e generazione del commento sarcastico.
- **Interattività Live:** Voti ai sondaggi e reazioni al "disagio" aggiornati in tempo reale senza ricaricare la pagina grazie ad HTMX (`hx-post`, `hx-swap`).
- **Cross-Platform:** Sincronizzazione trasparente dell'identità utente tra Web classica e Telegram Mini App.

### 2.2 Requisiti Non Funzionali & Sicurezza ("Anti-Grane")
- **Zero PII nel Database:** L'identità dell'utente (username, Telegram ID, nome, telefono) non viene mai salvata in chiaro nel DB.
- **Fail-Closed Moderation:** Se l'IA fallisce, va in timeout o solleva eccezioni, il post non riceve mai un roast automatico ed entra in regime cautelativo di sicurezza.
- **Gestione Crisi (Safety First):** Rilevamento automatico di segnali di autolesionismo o pericolo con interruzione istantanea del roast e visualizzazione di risorse di supporto reali (es. Telefono Amico, 1522).
- **Rate Limiting e Protezione API:** Prevenzione di script di spam e abuse per proteggere il budget delle chiamate LLM.
- **Serverless-Ready Concurrency:** Connessioni database ottimizzate per ambienti serverless (Vercel) tramite connection pooling nativo di **Neon**.

---

## 🔐 3. Architettura di Autenticazione e Privacy

Per evitare violazioni GDPR e garantire il vero anonimato anche in caso di compromissione del database, Sottovoce adotta un **modello di identità pseudonima non invertibile basato su HMAC**.

```mermaid
sequenceDiagram
    autonumber
    actor Utente
    participant Client as Telegram Mini App / Web
    participant Server as FastAPI su Vercel Serverless
    participant DB as Neon PostgreSQL (Pooled)

    Utente->>Client: Accesso (Mini App initData o Widget Telegram)
    Client->>Server: Invia dati di autenticazione crittografati
    Server->>Server: Valida firma Telegram con TELEGRAM_BOT_TOKEN
    Server->>Server: Calcola user_key = HMAC-SHA256(Telegram_ID, SECRET_KEY)
    Note over Server: Il Telegram ID in chiaro viene SCARTATO immediatamente
    Server->>DB: Recupera o registra utente tramite sola user_key
    Server-->>Client: Sessione su Cookie HTTP-only sicuro
```

### Canali Telegram
- **Telegram Mini App (TMA):** Passa l'oggetto crittograficamente firmato `initData`.
- **Sito Web:** Utilizza il widget ufficiale *Login with Telegram*.

### Derivazione della Chiave Utente (`user_key`)
Il server riceve l'ID Telegram dell'utente ed esegue la derivazione pseudonima:

$$\text{user\_key} = \text{HMAC-SHA256}(\text{Telegram ID}, \text{SECRET\_KEY})$$

- Il Telegram ID in chiaro viene **immediatamente scartato** dalla memoria. Nel database viene registrata esclusivamente la `user_key`.
- Le sessioni client utilizzano cookie `HTTP-only`, `Secure` e a breve scadenza.
- Nessun tracciamento IP permanente viene memorizzato sui confessionisti.

---

## 🛡️ 4. Pipeline di Moderazione e Sicurezza (Content Governance)

> [!IMPORTANT]
> **Regola d'Oro:** Non si pubblica mai alla cieca. La moderazione e il triage di sicurezza avvengono **sempre prima** dell'eventuale roast.

```mermaid
flowchart TD
    A["📝 Invio Post da Utente"] --> B["1. Filtri Deterministici (Zero Costi)"]
    
    B -->|Violazione: Spam / Link / Dati Privati| C["🚫 Blocco o Mascheramento PII"]
    B -->|Superato| D["2. Triage IA (JSON Strutturato)"]
    
    D -->|Crisi / Autolesionismo| E["🛑 Safety Protocol: Niente Roast<br>Box Supporto Reale (1522, Telefono Amico)"]
    D -->|Contenuto Illegale Grave| F["❌ Rifiuto Immediato & Blocco"]
    D -->|Post Conforme| G["🤖 Giudice Bastardo: Generazione Roast & Pubblicazione"]
```

### 4.1 Livelli di Controllo Dettagliati

1. **Filtri Deterministici (Zero Costi):**
   - Controllo vincoli su lunghezza minima e massima.
   - Mascheramento regex automatico di numeri di telefono, email, IBAN e link esterni (per prevenire doxxing e tentativi di phishing).
   - Rate limiting basato su `user_key` (es. massimo 1 post ogni 30 minuti).

2. **Triage IA con Output JSON Strutturato (LangGraph / LangChain):**
   L'LLM riceve il testo e restituisce un JSON rigoroso e tipizzato:
   ```json
   {
     "category": "ok | self_harm | violence | abuse | illegal | doxxing",
     "severity": 0,
     "roast_allowed": true,
     "reason": "motivazione interna"
   }
   ```

3. **Protocollo di Crisi (Safety First):**
   - Se il triage rileva segnali di disagio estremo o autolesionismo (`self_harm`), la generazione del roast viene bloccata d'ufficio.
   - Il post viene impostato come privato o contrassegnato con un blocco visivo che espone immediatamente le linee di supporto ufficiali italiane (es. **Telefono Amico**, **1522**). Questo previene la gogna mediatica su persone in stato di vulnerabilità.

4. **Guardrail del Prompt del "Giudice Bastardo":**
   - Il system prompt impone che la satira colpisca la situazione o la scelta paradossale, **mai la persona**.
   - È tassativamente vietato ironizzare su: salute fisica/mentale, orientamento sessuale, identità di genere, origine etnica, religione o disabilità.

---

## 🗄️ 5. Schema del Database (SQLModel / Neon PostgreSQL)

La persistenza si appoggia su **Neon PostgreSQL**, sfruttando il connection pooling integrato (PgBouncer) ideale per l'architettura serverless di Vercel.

```mermaid
erDiagram
    USER ||--o{ CONFESSION : "pubblica (1:N)"

   -- Estensione per generare UUID v4 (nativa in PG 13+, ma utile per compatibilità)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================
-- 1. ENUMS
-- ==========================================

CREATE TYPE user_status AS ENUM (
    'active',
    'shadowbanned',
    'suspended',
    'banned'
);

CREATE TYPE moderation_status AS ENUM (
    'pending_ai',
    'approved',
    'crisis_held',
    'under_review',
    'rejected'
);

CREATE TYPE triage_category AS ENUM (
    'ok',
    'self_harm',
    'violence',
    'abuse',
    'doxxing',
    'hate_speech',
    'illegal',
    'spam'
);

CREATE TYPE reaction_type AS ENUM (
    'skull',
    'disagio',
    'popcorn',
    'clown'
);

CREATE TYPE post_style AS ENUM (
    'standard',
    'neon_cyber',
    'gold_glitch'
);

CREATE TYPE shame_badge AS ENUM (
    'none',
    'certified_clown',
    'walking_red_flag',
    'touch_grass'
);

CREATE TYPE tx_type AS ENUM (
    'stars_purchase',
    'referral_bonus',
    'weekly_podium',
    'buy_highlight',
    'buy_pin_boost',
    'buy_ai_lawyer',
    'buy_ai_prosecutor',
    'buy_shame_stamp'
);

-- ==========================================
-- 2. TABELLE CORE
-- ==========================================

-- 1. UTENTI & REFERRAL
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key CHAR(64) NOT NULL UNIQUE, -- HMAC-SHA256(telegram_id, secret)
    status user_status NOT NULL DEFAULT 'active',
    ban_reason TEXT,
    banned_until TIMESTAMPTZ,
    
    -- Portafoglio & Referral
    coins_balance INTEGER NOT NULL DEFAULT 50 CHECK (coins_balance >= 0),
    referral_code VARCHAR(16) NOT NULL UNIQUE,
    referred_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
    referral_qualified_at TIMESTAMPTZ,
    
    -- Rate limiting & GDPR
    trust_score INTEGER NOT NULL DEFAULT 100,
    last_post_at TIMESTAMPTZ,
    terms_accepted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_referred_by ON users(referred_by_id) WHERE referred_by_id IS NOT NULL;


-- 2. CONFESSIONI, SONDAGGI & PODIO
CREATE TABLE confessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    
    -- Moderazione & Giudice IA Base
    ai_roast TEXT,
    mod_status moderation_status NOT NULL DEFAULT 'pending_ai',
    category triage_category NOT NULL DEFAULT 'ok',
    severity SMALLINT NOT NULL DEFAULT 0,
    
    -- Poteri IA, Sabotaggio & Podio
    ai_defense TEXT,
    ai_prosecution TEXT,
    visual_style post_style NOT NULL DEFAULT 'standard',
    shame_stamp shame_badge NOT NULL DEFAULT 'none',
    pinned_until TIMESTAMPTZ,
    weekly_rank SMALLINT CHECK (weekly_rank IN (1, 2, 3)),
    
    
    -- Contatori Reazioni & Segnalazioni
    count_skull INTEGER NOT NULL DEFAULT 0 CHECK (count_skull >= 0),
    count_disagio INTEGER NOT NULL DEFAULT 0 CHECK (count_disagio >= 0),
    count_popcorn INTEGER NOT NULL DEFAULT 0 CHECK (count_popcorn >= 0),
    count_clown INTEGER NOT NULL DEFAULT 0 CHECK (count_clown >= 0),
    
    -- Somma automatica gestita da PostgreSQL (zero bug di sincronizzazione)
    total_reactions INTEGER GENERATED ALWAYS AS (
        count_skull + count_disagio + count_popcorn + count_clown
    ) STORED,
    
    reports_count INTEGER NOT NULL DEFAULT 0 CHECK (reports_count >= 0),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

-- Indici Parziali per massime performance su Feed e Classifica (ignorano post cancellati o non approvati)
CREATE INDEX idx_public_feed ON confessions (pinned_until DESC NULLS LAST, created_at DESC)
    WHERE mod_status = 'approved' AND deleted_at IS NULL;

CREATE INDEX idx_leaderboard ON confessions (created_at DESC, total_reactions DESC)
    WHERE mod_status = 'approved' AND deleted_at IS NULL;

CREATE INDEX idx_confessions_author ON confessions (author_id, created_at DESC);


-- ==========================================
-- 3. INTERAZIONI (PK Composte)
-- ==========================================

CREATE TABLE reactions (
    confession_id UUID NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type reaction_type NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (confession_id, user_id)
);

CREATE TABLE reports (
    confession_id UUID NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
    reporter_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason triage_category NOT NULL,
    resolved BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (confession_id, reporter_id)
);

-- Indice per trovare subito le segnalazioni aperte in dashboard admin
CREATE INDEX idx_reports_unresolved ON reports (confession_id) WHERE resolved = false;


-- ==========================================
-- 4. TRANSAZIONI & AUDIT ECONOMICO
-- ==========================================

CREATE TABLE coin_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    
    amount INTEGER NOT NULL CHECK (amount <> 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    tx_type tx_type NOT NULL,
    
    -- Campi Telegram Stars
    stars_paid INTEGER CHECK (stars_paid > 0),
    telegram_charge_id VARCHAR(255) UNIQUE,
    
    -- Post collegato (se applicabile)
    target_confession_id UUID REFERENCES confessions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wallet_history ON coin_transactions (user_id, created_at DESC);
CREATE INDEX idx_tx_target_confession ON coin_transactions (target_confession_id) WHERE target_confession_id IS NOT NULL;
```

> [!TIP]
> In ambiente serverless, impostare `DATABASE_URL` con la stringa di connessione **pooled** fornita da Neon (con dominio contenente `-pooler.neon.tech` e parametro `?sslmode=require`).

---

## 🛠️ 6. Stack Tecnologico

| Componente | Tecnologia | Ruolo & Scopo |
| :--- | :--- | :--- |
| **Piattaforma Hosting** | [Vercel](https://vercel.com/) | Hosting serverless edge-optimized con deploy automatico da Git |
| **Backend Web** | [FastAPI](https://fastapi.tiangolo.com/) (Python 3.12+) | Framework asincrono ad alte performance, esposto come Serverless Function |
| **Database Serverless** | [Neon](https://neon.tech/) (PostgreSQL) | Postgres serverless con autoscaling e connection pooling integrato |
| **Cache & Rate Limiting** | [Redis](https://redis.io/) (`redis-py` / Upstash) | Rate limiting (1 post/30m per user_key), sessioni temporanee e cache |
| **ORM & Models** | [SQLModel](https://sqlmodel.tiangolo.com/) / SQLAlchemy | Modelli dati tipizzati con Pydantic e driver `psycopg` |
| **Telegram Bot** | [aiogram 3.x](https://docs.aiogram.dev/) | Bot webhook handler integrato negli endpoint serverless di FastAPI |
| **Agenti & AI Workflow** | [DeepSeek](https://deepseek.com/) via [LangChain DeepSeek](https://pypi.org/project/langchain-deepseek/) & [LangGraph](https://www.langchain.com/langgraph) | Orchestrazione a stati per safety triage, roast sarcastico, difesa e accusa |
| **Configurazione & Secrets** | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | Gestione tipizzata con `SecretStr` da `.env` e variabili d'ambiente |
| **Frontend SSR** | [Jinja2](https://palletsprojects.com/p/jinja/) | Server-Side Rendering per pagine e componenti parziali |
| **Interattività Client** | [HTMX](https://htmx.org/) | Reattività dinamica e votazioni live senza SPA complesse |
| **Design System** | [Tailwind CSS v4](https://tailwindcss.com/) | Styling utility-first compilato via `@tailwindcss/cli` |
| **Telegram SDK** | `telegram-web-app.js` | Integrazione con temi Dark/Light nativi, haptic feedback e MainButton |
| **Package Manager** | [uv](https://astral.sh/uv) | Gestione rapida dell'ambiente Python e delle dipendenze |

---

## 🚀 7. Guida Rapida & Setup Locale

### Prerequisiti
- Python 3.12+ (consigliato 3.12 per massima compatibilità con il runtime Python di Vercel)
- Node.js 20+ e `npm` (per compilare Tailwind CSS)
- Un account attivo su [Neon.tech](https://neon.tech/) (PostgreSQL)
- Un'istanza [Redis](https://redis.io/) (locale o cloud come [Upstash Redis](https://upstash.com/) per Vercel)
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installato sul sistema

### Passi di Avvio

1. **Clona la repository:**
   ```bash
   git clone https://github.com/tuo-username/hot-mic.git
   cd hot-mic
   ```

2. **Installa le dipendenze Python e Node:**
   ```bash
   # Dipendenze backend Python
   uv sync

   # Dipendenze frontend (Tailwind CLI)
   npm install
   ```

3. **Configura le variabili d'ambiente:**
   Crea un file `.env` nella root del progetto:
   ```ini
   # Database Neon PostgreSQL (usare la stringa pooled con -pooler)
   DATABASE_URL="postgresql://user:password@ep-example-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"

   # Redis (locale o Upstash Redis URL per rate limiting & cache)
   REDIS_URL="redis://localhost:6379/0"

   # Telegram Bot
   TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
   TELEGRAM_WEBHOOK_URL="https://tuo-dominio.vercel.app/api/telegram-webhook"

   # Sicurezza e Crittografia
   HMAC_SECRET_KEY="chiave-segreta-molto-lunga-e-casuale-per-hmac"

   # AI & LLM (DeepSeek)
   DEEPSEEK_API_KEY="sk-..."
   ```

4. **Compila Tailwind CSS:**
   ```bash
   # Compilazione singola / minificata per produzione:
   npm run build

   # Oppure watch mode continuo durante lo sviluppo:
   npm run watch
   ```

5. **Avvia il server di sviluppo in locale:**
   ```bash
   uv run fastapi dev
   ```

---

## ☁️ 8. Architettura Serverless & Deploy su Vercel

Il deploy su Vercel trasforma l'applicazione in una suite di funzioni serverless scalabili a zero costi a riposo.

### 8.1 Struttura del Progetto per Vercel
Vercel rileva automaticamente l'applicazione FastAPI tramite un file di entry point (es. `api/index.py`):

```
hot-mic/
├── api/
│   └── index.py            # Entrypoint ASGI per Vercel Serverless Function
├── src/
│   ├── agents/             # Pipeline LangGraph (Triage, Roast IA, Avvocato/Accusa con DeepSeek)
│   ├── model/              # Modelli SQLModel / PostgreSQL (User, Confession, Reaction, CoinTx)
│   ├── router/             # Router FastAPI (Web SSR Jinja2, HTMX endpoints, Webhook Telegram)
│   ├── schema/             # Schemi Pydantic e configurazione Settings (settings.py)
│   ├── services/           # Logica di business (HMAC user_key, rate-limit Redis, Stars)
│   ├── static/             # Asset statici (Tailwind CSS input.css/output.css, JS TMA)
│   └── telegram/           # Bot handler aiogram (comandi, pagamenti Stars, apertura TMA)
├── package.json            # Script di compilazione Tailwind v4 CLI
├── pyproject.toml          # Dipendenze Python gestite tramite uv
├── vercel.json             # Regole di build e routing per Vercel Serverless
└── README.md
```

### 8.2 File di configurazione `vercel.json`
```json
{
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

### 8.3 Entrypoint `api/index.py`
```python
import sys
from pathlib import Path

# Aggiunge src al path per import modulari
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from router.app import app

# Vercel esporta l'istanza ASGI 'app'
```

### 8.4 Accorgimenti Chiave per Vercel + Neon
1. **Telegram Bot via Webhook (No Long-Polling):**  
   In ambiente serverless le istanze terminano al termine della richiesta. `aiogram` deve quindi operare tramite **Webhook** esposto su `/api/telegram-webhook`, gestito direttamente come route FastAPI.
2. **Neon Connection Pooling:**  
   Ogni invocazione serverless di Vercel apre potenzialmente una nuova connessione. L'utilizzo della stringa di connessione **Pooled** di Neon (PgBouncer integrato) previene il superamento del limite massimo di connessioni PostgreSQL (`too many clients already`).
3. **Variabili d'Ambiente su Vercel:**  
   Inserire nella dashboard di Vercel (*Settings* > *Environment Variables*) tutti i valori configurati nel file `.env`.
4. **Deploy con Vercel CLI o Git:**
   ```bash
   vercel
   # oppure vercel --prod
   ```

---

## ⚖️ 9. Disclaimer Legale

Nel footer dell'applicazione e nella schermata di benvenuto della Telegram Mini App deve essere presente il seguente avviso:
> *"I commenti generati dall'Intelligenza Artificiale hanno esclusivo scopo satirico e d'intrattenimento. Sottovoce non fornisce consulenza psicologica, medica o legale. In caso di reale disagio emotivo o emergenza, si invita a contattare i numeri gratuiti di supporto indicati nella piattaforma (es. 1522 o Telefono Amico)."*
