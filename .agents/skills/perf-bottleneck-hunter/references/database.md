# Database Performance & Bottlenecks

Questo riferimento guida l'individuazione di query lente, configurazioni errate di pool, lock concorrenti e problemi di scalabilità del database (PostgreSQL, SQLite, MySQL con SQLAlchemy o SQL grezzo).

---

## 1. Misurare prima di toccare: Logging e Query Profiling

### Tracciare le query lente in SQLAlchemy
Aggiungi un listener sull'Engine per individuare qualsiasi query che superi una soglia (es. 50ms):

```python
import time
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(time.perf_counter())

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total_ms = (time.perf_counter() - conn.info["query_start_time"].pop()) * 1000
    if total_ms > 50:  # Soglia in ms
        print(f"[SLOW QUERY {total_ms:.1f}ms] {statement[:250]} | params: {parameters}")
```

### EXPLAIN ANALYZE: Leggere il piano di esecuzione
Esegui sempre `EXPLAIN (ANALYZE, BUFFERS)` in PostgreSQL o `EXPLAIN QUERY PLAN` in SQLite:

1. **Seq Scan (Sequential Scan)**:
   - Se avviene su tabelle con più di poche migliaia di righe, indica quasi sempre un **indice mancante** sulle colonne di `WHERE` o `JOIN`.
2. **Rows Removed by Filter**:
   - Se il motore legge 100.000 righe e ne scarta 99.980 via filtro in memoria, l'indice non è selettivo o non copre il filtro.
3. **Buffers: Shared Hit vs Read**:
   - `read`: lettura da disco (lenta).
   - `hit`: lettura dal buffer pool in RAM (molto più veloce). Una query lenta con molti `read` satura l'I/O del server.

---

## 2. Problema N+1 Query

### Il sintomo
Una query recupera la collezione principale (1), seguita da una query separata per ogni record figlio per caricare relazioni (N):
```
SELECT * FROM users;                       -- 1 query (restituisce 100 utenti)
SELECT * FROM profiles WHERE user_id = 1;  -- N query ripetute
SELECT * FROM profiles WHERE user_id = 2;
...
```

### Il fix in SQLAlchemy
Evita il caricamento lazy nei percorsi caldi. Configura esplicitamente la strategia di caricamento:

```python
from sqlalchemy.orm import selectinload, joinedload

# Per relazioni uno-a-molti (1:N): selectinload esegue 2 query efficienti con WHERE id IN (...)
stmt = select(User).options(selectinload(User.posts))

# Per relazioni molti-a-uno o uno-a-uno (N:1, 1:1): joinedload fa un singolo JOIN
stmt = select(Post).options(joinedload(Post.author))
```

---

## 3. Indici: Regole pratiche ed errori comuni

### Ordine delle colonne negli indici composti (Leftmost Prefix)
Se hai un indice su `(tenant_id, status, created_at)`:
- ✅ Funziona per query che filtrano su `tenant_id`
- ✅ Funziona per query su `tenant_id AND status`
- ✅ Funziona per query su `tenant_id AND status AND created_at`
- ❌ **NON viene usato** se filtri solo per `status` o solo per `created_at`.
- *Regola*: metti per prime le colonne con maggiore cardinalità o i vincoli di tenancy/uguaglianza (`=`), seguite dalle colonne con operatori di intervallo (`>`, `<`) o ordinamento (`ORDER BY`).

### Funzioni sulle colonne che annullano l'indice
- **Antipattern**:
  ```sql
  WHERE LOWER(email) = 'user@example.com'  -- L'indice su `email` viene ignorato!
  WHERE DATE(created_at) = '2026-10-24'   -- L'indice su `created_at` viene ignorato!
  ```
- **Fix**:
  - Usa intervalli diretti: `WHERE created_at >= '2026-10-24 00:00:00' AND created_at < '2026-10-25 00:00:00'`
  - Oppure crea un indice funzionale: `CREATE INDEX idx_user_lower_email ON users (LOWER(email));`

### Indici parziali (Risparmio di spazio e I/O)
Se hai una tabella da 10M di righe e il 95% è archiviato o soft-deleted:
```sql
CREATE INDEX idx_active_orders ON orders (user_id) WHERE is_active = true;
```
L'indice peserà solo il 5% di un indice normale, restando interamente in RAM cache.

---

## 4. Paginazione: OFFSET vs Keyset / Cursor

### Perché `OFFSET` fallisce su dataset grandi
```sql
SELECT * FROM messages ORDER BY created_at DESC LIMIT 20 OFFSET 100000;
```
Il database deve recuperare 100.020 righe, ordinarle e scartarne 100.000. Il tempo cresce linearmente con il numero di pagina.

### Fix: Keyset / Cursor Pagination
Filtra direttamente sull'ultimo valore visto:
```sql
SELECT * FROM messages 
WHERE (created_at, id) < (:last_created_at, :last_id)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```
Questa query salta istantaneamente alle 20 righe richieste usando l'indice $O(\log N)$, con tempo costante sia a pagina 1 che a pagina 10.000.

---

## 5. Pool di connessioni e Transazioni

### Transazioni lunghe durante chiamate esterne (Errore critico)
- **Antipattern**:
  ```python
  async with session.begin():
      user = await session.get(User, user_id)
      # PERICOLO: Connessione DB e lock bloccati per 2-5 secondi durante la chiamata AI!
      summary = await llm.generate_summary(user.bio)
      user.summary = summary
  ```
- **Fix**: Rilascia la transazione prima di toccare la rete:
  ```python
  # 1. Lettura veloce
  user = await session.get(User, user_id)

  # 2. Chiamata I/O esterna SENZA connessione DB trattenuta
  summary = await llm.generate_summary(user.bio)

  # 3. Scrittura transazionale veloce
  async with session.begin():
      await session.execute(
          update(User).where(User.id == user_id).values(summary=summary)
      )
  ```

### Sizing del Connection Pool
- Un pool troppo grande (es. 200 connessioni su un DB con 4 core) degrada le prestazioni a causa del context switching e della contesa sui lock.
- Formula empirica tipica: `pool_size = (core_cpu * 2) + numero_dischi`.
- Imposta sempre un `pool_timeout` ragionevole (es. 5-10s) e monitora le eccezioni `TimeoutError: QueuePool limit of size X overflow Y reached`.

---

## 6. Over-fetching di dati

- Evita `SELECT *` su tabelle con colonne pesanti (`TEXT` lungo, campi `JSONB` complessi) quando servono solo ID o status.
- In SQLAlchemy:
  ```python
  # Carica solo le colonne strettamente necessarie:
  stmt = select(Message.id, Message.status).where(...)
  ```
