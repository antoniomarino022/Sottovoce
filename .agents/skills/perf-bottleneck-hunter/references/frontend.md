# Frontend & Client Performance

Questo riferimento guida la diagnosi di lentezze nel rendering, caricamenti pesanti, scatti nell'interfaccia e overhead di rete (Web, Mini App Telegram, Jinja/SSR, htmx e vanilla JS).

---

## 1. Misurare prima di toccare: Web Vitals e DevTools

### Metriche chiave (Core Web Vitals)
- **LCP (Largest Contentful Paint)**: tempo per visualizzare l'elemento visivo più grande (target: **< 2.5s**).
- **INP (Interaction to Next Paint)**: reattività agli input dell'utente (click, tap, digitazione) (target: **< 200ms**).
- **CLS (Cumulative Layout Shift)**: stabilità visiva durante il caricamento (target: **< 0.1**).

### Individuare i colli di bottiglia con Chrome DevTools
1. **Network Tab**:
   - Ordina per **Size**: individua payload giganti o mancata compressione Gzip/Brotli.
   - Ordina per **Waterfall / Time**: individua catene di richieste a cascata o TTFB (Time to First Byte) elevato causato dal backend.
2. **Performance Tab**:
   - Registra 5-10 secondi durante l'azione lenta (click o scroll).
   - Cerca i **Long Tasks** (blocchi rossi > 50ms): indicano che il Main Thread di JavaScript è bloccato e non risponde agli input.

---

## 2. Rendering Server-Side, Jinja2 e htmx

Nelle architetture SSR/htmx (come le Mini App Telegram), i problemi di prestazioni sono spesso legati alla quantità di HTML trasferito e scambiato.

### Invio di frammenti mirati (Partials) invece di intere pagine
- **Antipattern**: Rispondere a una chiamata htmx renderizzando l'intero template `base.html` con navbar e header, per poi scartarne l'80% via swap.
- **Fix**: Ritorna solo il frammento HTML necessario:
  ```python
  @app.post("/messages")
  async def add_message(request: Request, ...):
      # Ritorna SOLO la bolla del messaggio singolo
      return templates.TemplateResponse(
          "partials/message.html", {"request": request, "msg": new_msg}
      )
  ```

### Swap htmx mirati contro il re-render di grandi liste
- Sostituire un contenitore con 500 elementi per aggiungere un elemento causa ricalcolo completo del layout del browser.
- **Fix**: Usa `hx-swap="beforeend"` sul contenitore o un OOB (out-of-band) swap mirato:
  ```html
  <form hx-post="/messages" hx-target="#message-list" hx-swap="beforeend">
  ```

### Polling continuo senza disattivazione
- **Antipattern**: `hx-trigger="every 1s"` che continua a fare richieste anche quando l'utente non è attivo o la finestra è in background.
- **Fix**: Aumenta l'intervallo (es. 5-10s) o usa eventi Server-Sent Events (SSE) / WebSocket se serve aggiornamento real-time, oppure disattiva il polling con condizioni:
  ```html
  <div hx-get="/updates" hx-trigger="every 5s [document.visibilityState === 'visible']">
  ```

---

## 3. Risorse Bloccanti e Bundle Size

### CSS e JS nel percorso critico
- Qualsiasi `<script src="...">` senza attributi blocca il parsing dell'HTML finché lo script non è scaricato ed eseguito.
- **Fix**:
  - Aggiungi `defer` a tutti gli script non essenziali per il primo render:
    ```html
    <script src="/static/app.js" defer></script>
    ```
  - Carica solo CSS strettamente necessario nel `<head>`, eliminando stili inutilizzati (PurgeCSS/Tailwind scanning).

### Immagini e Asset non ottimizzati
- Immagini non dimensionate causano layout shift (CLS).
- **Fix**:
  - Specifica sempre `width` e `height` espliciti (o `aspect-ratio`).
  - Usa formati moderni compatti (WebP o AVIF).
  - Aggiungi caricamento differito per gli asset sotto la piega:
    ```html
    <img src="/avatar.webp" loading="lazy" width="48" height="48" alt="Avatar">
    ```

---

## 4. Esecuzione JS e DOM Thrashing

### Layout Thrashing (Interleaving di Read e Write)
- Se leggi una proprietà geometrica del DOM (`offsetHeight`, `clientWidth`) subito dopo averne modificata un'altra, forzi il motore del browser a ricalcolare il layout istantaneamente (Synchronous Reflow).
- **Antipattern**:
  ```javascript
  elements.forEach(el => {
      const height = el.clientHeight; // READ
      el.style.height = (height + 10) + 'px'; // WRITE (costringe il reflow!)
  });
  ```
- **Fix**: Raggruppa prima tutte le letture, poi tutte le scritture:
  ```javascript
  // 1. Fase di lettura
  const heights = elements.map(el => el.clientHeight);
  // 2. Fase di scrittura (o usa requestAnimationFrame)
  elements.forEach((el, i) => {
      el.style.height = (heights[i] + 10) + 'px';
  });
  ```

### Gestione degli eventi di Scroll e Resize
- Evita calcoli complessi direttamente dentro listener di scroll o resize.
- Usa `requestAnimationFrame`, `debounce` o `throttle`:
  ```javascript
  let ticking = false;
  window.addEventListener('scroll', () => {
      if (!ticking) {
          window.requestAnimationFrame(() => {
              updateScrollEffects();
              ticking = false;
          });
          ticking = true;
      }
  });
  ```
