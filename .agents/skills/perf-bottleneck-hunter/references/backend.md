# Backend Performance & Bottlenecks

Questo riferimento guida la diagnosi e l'ottimizzazione del codice applicativo backend (Python, FastAPI, Starlette, runtime async, worker e pipeline AI/LLM).

---

## 1. Misurare prima di toccare: Strumenti essenziali

### Timer a blocchi (Zero dipendenze)
Usa un context manager per isolare le macro-fasi (rete, calcolo, DB, chiamate esterne):

```python
import time
from contextlib import contextmanager

@contextmanager
def time_block(label: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"[{label}] {elapsed_ms:.2f} ms")

# Uso:
with time_block("OpenAI API call"):
    res = await llm.ainvoke(...)
```

### Profiler CPU (Standard & Async)
1. **cProfile per codice sincrono o CPU-bound**:
   ```bash
   python -m cProfile -s cumtime main.py
   ```
2. **yappi per codice `asyncio` e multithread**:
   ```python
   import yappi
   yappi.set_clock_type("cpu")  # oppure "wall" per includere I/O
   yappi.start()
   # ... esegui codice o endpoint ...
   yappi.stop()
   yappi.get_func_stats().sort("cumtime").print_all()
   ```
3. **py-spy (Sampling profiler non invasivo)**:
   Utile per ispezionare processi attivi senza modificare il codice:
   ```bash
   py-spy top --pid <PID>
   py-spy record -o flamegraph.svg --pid <PID>
   ```

---

## 2. I/O, Latenza e Chiamate Esterne (LLM, Rete, Lock)

### Errore comune: Ricreazione di client HTTP / SDK per richiesta
- **Sintomo**: Ogni richiesta subisce handshake TCP + TLS negoziazione (~50–150ms buttati a richiesta).
- **Antipattern**:
  ```python
  @app.post("/ask")
  async def ask():
      client = httpx.AsyncClient()  # Aperto e chiuso a ogni request!
      res = await client.post(...)
  ```
- **Fix**: Creare il client nel ciclo di vita dell'applicazione (`lifespan`) o come singleton:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      app.state.http_client = httpx.AsyncClient(timeout=10.0)
      yield
      await app.state.http_client.aclose()
  ```

### Esecuzione sequenziale di chiamate indipendenti
- **Sintomo**: Latenza totale = somma delle latenze ($T_1 + T_2 + T_3$).
- **Fix**: Esegui in parallelo con controllo di concorrenza (`asyncio.Semaphore` per proteggere i rate limit):
  ```python
  sem = asyncio.Semaphore(5)

  async def bounded_call(item):
      async with sem:
          return await call_api(item)

  results = await asyncio.gather(*(bounded_call(i) for i in items))
  ```

### Lock tenuti aperti durante chiamate di rete o LLM
- **Antipattern**:
  ```python
  async with state_lock:
      # BLOCCO TOTALE: tutti gli altri utenti aspettano la risposta dell'LLM (1-3s)
      answer = await llm.ainvoke(prompt)
      state[user_id] = answer
  ```
- **Fix**: Riduci la sezione critica alla sola mutazione in memoria:
  ```python
  answer = await llm.ainvoke(prompt)  # Fuori dal lock
  async with state_lock:
      state[user_id] = answer          # Microsecondi dentro il lock
  ```

---

## 3. CPU al 100% e Throughput Basso

### Codice bloccante sincrono dentro contesto `async`
- **Sintomo**: Una singola richiesta CPU-heavy o bloccante congela l'event loop di Node/Python, causando timeout a tutte le altre connessioni.
- **Colpevoli tipici**: `time.sleep()`, `requests.get()`, hashing password sincrono (`bcrypt`), manipolazione file con `open()`.
- **Fix**:
  - Sostituire con l'alternativa asincrona (`asyncio.sleep()`, `httpx.AsyncClient`, `aiofiles`).
  - Oppure delegare al threadpool con `asyncio.to_thread`:
    ```python
    import asyncio
    result = await asyncio.to_thread(sync_heavy_function, arg1, arg2)
    ```

### Serializzazione e Deserializzazione costosa (JSON / Pydantic)
- In percorsi caldi con payload grandi (decine di MB o migliaia di record), `json` standard o parsing ricorsivo Pydantic v1 costa decine di ms.
- **Fix**:
  - Usa librerie C/Rust come `orjson`:
    ```python
    import orjson
    data = orjson.loads(raw_bytes)
    output = orjson.dumps(data)
    ```
  - In FastAPI, usa `ORJSONResponse` per serializzare direttamente le risposte.
  - In Pydantic v2, usa `model_validate_json()` direttamente da byte invece di passare per `dict`.

### Complessità algoritmica nei cicli ($O(N^2) \rightarrow O(N)$)
- Evita lookup con `item in my_list` dentro un ciclo:
  ```python
  # Lento (O(N * M)):
  filtered = [x for x in items if x.id in id_list]

  # Veloce (O(N + M)):
  id_set = set(id_list)
  filtered = [x for x in items if x.id in id_set]
  ```

---

## 4. Memoria che cresce nel tempo (Memory Leaks)

### Cache in-memory senza limite di dimensione
- **Antipattern**:
  ```python
  cache = {}  # Cresce all'infinito fino all'OOM killer!
  @lru_cache(maxsize=None)  # Stesso problema se le chiavi sono infinite (es. UUID utente)
  ```
- **Fix**: Usa sempre una dimensione massima o un TTL:
  ```python
  from functools import lru_cache
  @lru_cache(maxsize=1024)

  # Oppure con TTL (libreria cachetools):
  from cachetools import TTLCache
  cache = TTLCache(maxsize=1000, ttl=300)
  ```

### Task in background accumulati o orfani
- Creare task con `asyncio.create_task()` senza raccoglierli o gestirne gli errori può trattenere riferimenti a oggetti enormi.
- Conserva sempre un set di riferimenti deboli (`weakref`) o un task supervisor per pulire i task completati.

---

## 5. Cold Start e Import

- **Problema**: L'avvio o la prima richiesta impiega secondi a causa di import pesanti (`torch`, `transformers`, `spacy`) eseguiti nel percorso caldo.
- **Fix**:
  - Sposta gli import pesanti a livello globale una volta sola durante l'avvio del container/worker (pre-warming).
  - Pre-compila le regex usate di frequente: `PATTERN = re.compile(r"...")` a livello di modulo.
