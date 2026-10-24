---
name: perf-bottleneck-hunter
description: Individua colli di bottiglia e ottimizza codice e applicazioni (backend, database, frontend, pipeline AI/LLM). Usa SEMPRE questa skill quando l'utente dice che qualcosa è lento, "rallenta tutto", "scatta", consuma troppa memoria/CPU, ha latenza alta, timeout, query lente, N+1, memory leak, o chiede di ottimizzare, fare profiling, rendere più veloce/leggero/scalabile codice o un'app, anche se non usa la parola "performance". Triggera anche per code review orientate a efficienza, analisi di flame graph/profiler/EXPLAIN, tuning di cache, pool di connessioni, async, bundle size e costi di chiamate LLM. Use for slow code, bottlenecks, profiling, latency, throughput, memory and optimization requests.
---

# Perf Bottleneck Hunter

Obiettivo: trovare **dove** vanno davvero tempo e risorse, correggere solo quello, e dimostrare il miglioramento con una misura. Un'ottimizzazione senza misura è una supposizione, e spesso peggiora la leggibilità senza guadagnare nulla.

## Principi

1. **Misura prima di toccare.** Il collo di bottiglia raramente è dove si pensa. Senza dati, parti dal codice e dalle architetture sospette, ma dichiara che sono ipotesi.
2. **Un solo collo alla volta.** Rimosso il più grosso, il profilo cambia. Ordina i problemi per (impatto stimato) / (sforzo) e affrontali in quest'ordine.
3. **Lavoro inutile prima del lavoro veloce.** Le vittorie più grandi vengono dall'eliminare lavoro (connessioni riaperte a ogni richiesta, query ripetute, ricompilazioni, I/O superfluo, chiamate LLM evitabili), non dal rendere più veloce il lavoro che c'è.
4. **Non cambiare il comportamento.** Ogni ottimizzazione deve mantenere gli stessi risultati. Segnala i compromessi (cache stantia, consistenza, memoria in più).
5. **Semplicità.** Tra due soluzioni con lo stesso guadagno, scegli la più semplice. Rifiuta le micro-ottimizzazioni su codice che non è nel percorso caldo.

## Flusso di lavoro

### 1. Capire il sintomo
Se mancano, chiedi (al massimo 2-3 domande, solo quelle che cambiano la diagnosi):
- Cosa è lento: un endpoint, l'avvio, tutta l'app, una pagina, un job? Quanto (ms/s) e quanto dovrebbe essere?
- Sempre o sotto carico? Dopo quanto tempo cresce (memoria)?
- Ambiente e stack (DB, cache, hosting, volume dati).
Se l'utente ha già incollato codice, **parti subito dall'analisi** e fai le domande dopo, solo se servono.

### 2. Localizzare lo strato
Usa la tabella per capire dove cercare. Leggi il riferimento giusto solo per lo strato sospetto.

| Sintomo | Strato probabile | Riferimento |
|---|---|---|
| Latenza alta su singole richieste, CPU bassa | I/O: DB, rete, LLM, lock | `references/backend.md`, `references/database.md` |
| CPU al 100%, throughput basso | Calcolo, serializzazione, loop, codice sincrono in contesto async | `references/backend.md` |
| Memoria che cresce nel tempo | Cache/stato senza limite, riferimenti trattenuti, checkpoint/log che si accumulano | `references/backend.md` |
| Lento solo con molti dati | Query senza indice, N+1, paginazione con OFFSET grandi | `references/database.md` |
| Pagina lenta da caricare o da usare | Bundle, immagini, render bloccante, richieste a cascata | `references/frontend.md` |
| Lento solo la prima richiesta | Cold start, import pesanti, inizializzazioni lazy | `references/backend.md` |

### 3. Cercare i colpevoli tipici (checklist a colpo d'occhio)
Scorri il codice con queste domande, in ordine di frequenza:
- **Risorse costose create a ogni richiesta**: connessioni DB/Redis/HTTP, client SDK, grafi/modelli compilati, regex, template. Devono nascere una volta (startup/lifespan, cache a livello di modulo).
- **Query nel ciclo (N+1)** e round trip multipli dove ne basterebbe uno.
- **Codice bloccante dentro `async`** (driver sincroni, `requests`, `time.sleep`, lavoro CPU) che ferma l'event loop per tutti.
- **Lock o transazioni tenute aperte durante chiamate lente** (LLM, HTTP esterni).
- **Lavoro sequenziale indipendente** che può andare in parallelo (`asyncio.gather`).
- **Cache assente, mal chiavata o inutile**: chiavi che includono il singolo utente e azzerano l'hit rate, TTL sbagliati, mancata invalidazione.
- **Dati cresciuti senza limite**: tabelle di log/checkpoint, liste in memoria, cache senza `maxsize`.
- **Troppi dati trasferiti**: `SELECT *`, payload enormi, serializzazione di campi non usati.
- **Lavoro sincrono che potrebbe essere differito** (task in background, code) perché l'utente non ha bisogno del risultato subito.

### 4. Misurare (quando si può eseguire codice o l'utente può farlo)
Proponi lo strumento più semplice che risponde alla domanda "dove va il tempo?". Esempi pronti in `references/`. Regola: prima un timer sulle fasi grosse (rete/DB/LLM/CPU), poi un profiler solo dentro la fase dominante.
Se non puoi misurare, dì chiaramente quali misure servono e quale risultato confermerebbe o smentirebbe ciascuna ipotesi.

### 5. Correggere
Fai la modifica minima per ciascun problema, mostra il codice prima/dopo e spiega **perché** accelera. Se riscrivi file, mantieni API pubbliche e firme, e dillo.

### 6. Verificare
Indica come rimisurare con lo stesso metodo del passo 4 e cosa aspettarsi. Non dichiarare "più veloce" senza un numero o, se non misurabile, scrivi "atteso" invece di "ottenuto".

## Formato della risposta

Per un'analisi, usa questa struttura (prosa breve, non muri di elenchi):

1. **Diagnosi in una frase**: dove va il tempo/la risorsa e perché.
2. **Problemi trovati**, ordinati per impatto. Per ognuno: cosa succede, perché costa, severità (alta/media/bassa) e sforzo del fix.
3. **Fix**: codice o diff per quelli ad alto rapporto impatto/sforzo.
4. **Come verificare**: la misura prima/dopo.
5. **Da lasciare stare**: ottimizzazioni tentatrici ma inutili qui (evita lavoro sprecato).
6. **Compromessi e rischi** dei fix proposti.

Per domande piccole ("questa query è lenta?") rispondi corto e diretto, senza l'intera struttura.

## Errori da evitare

- Proporre cache come prima mossa: prima elimina il lavoro, poi memorizza il resto. Ogni cache porta invalidazione e dati stantii.
- Parallelizzare ovunque senza controllare limiti (pool, rate limit dei provider) e ordine dei risultati.
- Aggiungere indici alla cieca: costano in scrittura e spazio; verifica con `EXPLAIN (ANALYZE, BUFFERS)`.
- Ottimizzare il caso medio ignorando la coda (p95/p99), che è ciò che gli utenti sentono.
- Confondere latenza (tempo di una richiesta) con throughput (richieste al secondo): richiedono rimedi diversi.
- Scambiare lentezza di un servizio esterno (LLM, API) per lentezza del proprio codice: misura il tempo di attesa separatamente.
