const tg = window.Telegram?.WebApp;

// ---------------------------------------------------------------------------
// 0. Helpers (Safe API / FastAPI Validation Error Formatting)
// ---------------------------------------------------------------------------
function extractErrorMessage(payload, fallback = "Operazione non riuscita al momento.") {
  if (!payload) return fallback;
  if (typeof payload === "string") {
    try {
      payload = JSON.parse(payload);
    } catch (_) {
      return payload.trim() || fallback;
    }
  }
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => (typeof item === "string" ? item : item?.msg || JSON.stringify(item)))
      .join("; ");
  }
  if (typeof payload?.message === "string" && payload.message.trim()) {
    return payload.message;
  }
  return fallback;
}

function showNativeAlert(msg) {
  if (tg?.showAlert) tg.showAlert(msg);
  else alert(msg);
}

// ---------------------------------------------------------------------------
// 1. Mini App Onboarding & Confession Form Actions
// ---------------------------------------------------------------------------
let currentConfessionId = null;

function setAuthError(msg) {
  const el = document.getElementById("authError");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
}

function syncRegisterGate() {
  const miniAppSection = document.getElementById("miniAppSection");
  const outsideSection = document.getElementById("openInTelegramSection");
  if (!miniAppSection || !outsideSection) return;

  const isInsideTelegram = Boolean(tg && tg.initData && tg.initData.length > 0);
  miniAppSection.classList.toggle("hidden", !isInsideTelegram);
  outsideSection.classList.toggle("hidden", isInsideTelegram);
}

window.handleTmaLogin = async function () {
  setAuthError(null);
  if (!tg?.initData) {
    setAuthError("Apri Hot-Mic direttamente da Telegram per accedere.");
    tg?.HapticFeedback?.notificationOccurred("error");
    return;
  }

  const accepted = document.getElementById("termsAccepted")?.checked;
  if (!accepted) {
    setAuthError("Devi accettare i termini per continuare.");
    tg?.HapticFeedback?.notificationOccurred("warning");
    return;
  }

  const btn = document.getElementById("tmaLoginBtn");
  if (btn?.disabled) return;
  if (btn) btn.disabled = true;

  try {
    const res = await fetch("/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": tg.initData,
      },
      body: JSON.stringify({
        data: { init_data: tg.initData },
        checkbox: { accepted: true },
      }),
    });

    const data = await res.json().catch(() => null);
    if (!res.ok) {
      throw new Error(extractErrorMessage(data, "Errore durante l'accesso."));
    }

    tg?.HapticFeedback?.notificationOccurred("success");
    window.location.replace("/");
  } catch (err) {
    tg?.HapticFeedback?.notificationOccurred("error");
    setAuthError(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
};

function setConfessionFeedback(msg, isError = false) {
  const errBox = document.getElementById("confessionError");
  const succBox = document.getElementById("confessionSuccess");
  if (errBox) {
    errBox.textContent = isError && msg ? msg : "";
    errBox.classList.toggle("hidden", !(isError && msg));
  }
  if (succBox) {
    succBox.textContent = !isError && msg ? msg : "";
    succBox.classList.toggle("hidden", !(!isError && msg));
  }
}

function syncMainButton() {
  if (!tg?.MainButton || !tg.initData) return;
  const textarea = document.getElementById("confessionContent");
  if (!textarea) {
    tg.MainButton.offClick?.(window.handleConfessionSubmit);
    tg.MainButton.hide();
    return;
  }

  tg.MainButton.setText("PUBBLICA CONFESSIONE");
  tg.MainButton.offClick?.(window.handleConfessionSubmit);
  tg.MainButton.onClick(window.handleConfessionSubmit);

  if (textarea.value.trim().length >= 10) {
    tg.MainButton.show();
    tg.MainButton.enable();
  } else {
    tg.MainButton.hide();
  }
}

window.updateCharCount = function () {
  const textarea = document.getElementById("confessionContent");
  const counter = document.getElementById("charCount");
  if (textarea && counter) {
    counter.textContent = `${textarea.value.length} / 2000`;
  }
  syncMainButton();
};

window.handleConfessionSubmit = async function () {
  const textarea = document.getElementById("confessionContent");
  if (!textarea) return;

  setConfessionFeedback(null);
  const content = textarea.value.trim();
  if (content.length < 10) {
    setConfessionFeedback("La confessione deve contenere almeno 10 caratteri.", true);
    tg?.HapticFeedback?.notificationOccurred("error");
    return;
  }

  const submitBtn = document.getElementById("submitBtn");
  if (submitBtn?.disabled) return;
  const origSubmitHtml = submitBtn ? submitBtn.innerHTML : "";
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = "<span>⏳</span> <span>La Corte sta deliberando...</span>";
  }
  if (tg?.MainButton) {
    tg.MainButton.showProgress();
    tg.MainButton.setText("LA CORTE STA DELIBERANDO...");
  }

  try {
    const response = await fetch("/confessions/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(tg?.initData ? { "X-Telegram-Init-Data": tg.initData } : {}),
      },
      body: JSON.stringify({ content }),
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(extractErrorMessage(data, "Errore durante la pubblicazione."));
    }

    tg?.HapticFeedback?.notificationOccurred("success");
    setConfessionFeedback("Confessione pubblicata con successo.");
    currentConfessionId = data.id;

    const section = document.getElementById("latestConfessionSection");
    const textElem = document.getElementById("latestConfessionText");
    const badgeElem = document.getElementById("latestConfessionIdBadge");
    if (section && textElem && badgeElem) {
      section.classList.remove("hidden");
      textElem.textContent = data.content;
      badgeElem.textContent = `#${data.id}`;

      const statusBadge = document.getElementById("latestConfessionStatusBadge");
      if (statusBadge) {
        if (data.mod_status === "approved") {
          statusBadge.textContent = "Approvata";
          statusBadge.className = "font-medium text-accent-text";
        } else if (data.mod_status === "crisis_held") {
          statusBadge.textContent = "In revisione";
          statusBadge.className = "font-medium text-danger";
        } else {
          statusBadge.textContent = "Non ammessa";
          statusBadge.className = "font-medium text-danger";
        }
      }

      const roastSection = document.getElementById("latestRoastSection");
      const roastText = document.getElementById("latestRoastText");
      if (roastSection && roastText) {
        if (data.ai_roast) {
          roastText.textContent = data.ai_roast;
          roastSection.classList.remove("hidden");
        } else {
          roastSection.classList.add("hidden");
        }
      }
    }

    textarea.value = "";
    window.updateCharCount();
  } catch (err) {
    tg?.HapticFeedback?.notificationOccurred("error");
    setConfessionFeedback(err.message, true);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      if (origSubmitHtml) submitBtn.innerHTML = origSubmitHtml;
    }
    if (tg?.MainButton) {
      tg.MainButton.hideProgress();
      syncMainButton();
    }
  }
};

window.handleDeleteLatest = async function () {
  if (!currentConfessionId) return;
  try {
    const response = await fetch(`/confessions/${currentConfessionId}`, {
      method: "DELETE",
      headers: {
        ...(tg?.initData ? { "X-Telegram-Init-Data": tg.initData } : {}),
      },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(extractErrorMessage(data, "Impossibile eliminare la confessione."));
    }
    tg?.HapticFeedback?.notificationOccurred("success");
    setConfessionFeedback("Confessione eliminata.");
    document.getElementById("latestConfessionSection")?.classList.add("hidden");
    currentConfessionId = null;
  } catch (err) {
    tg?.HapticFeedback?.notificationOccurred("error");
    setConfessionFeedback(err.message, true);
  }
};

// ---------------------------------------------------------------------------
// 2. Navigation, Segmented Controls & Telegram WebApp Integration
// ---------------------------------------------------------------------------
function syncNavigationState() {
  const path = window.location.pathname;
  const search = window.location.search;
  let active = "feed";
  if (search.includes("filter=my")) active = "my";
  else if (path.startsWith("/leaderboard")) active = "leaderboard";
  else if (path.startsWith("/confession")) active = "confess";

  document.querySelectorAll(".bottom-nav-item").forEach((el) => {
    const isCurrent = el.dataset.tab === active;
    el.classList.toggle("text-accent-text", isCurrent);
    el.classList.toggle("font-semibold", isCurrent);
    el.classList.toggle("text-hint", !isCurrent);
  });

  if (tg?.BackButton) {
    const back = document.querySelector("[data-back]")?.dataset.back;
    if (back) {
      tg.BackButton.show();
    } else {
      tg.BackButton.hide();
    }
  }

  syncRegisterGate();
  syncMainButton();
}

if (!window.__hotmic_initialized) {
  window.__hotmic_initialized = true;

  if (tg) {
    document.documentElement.dataset.tg = "";
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.("secondary_bg_color");
    tg.setBackgroundColor?.("secondary_bg_color");

    tg.BackButton?.onClick(() => {
      const back = document.querySelector("[data-back]")?.dataset.back;
      if (back === "history") history.back();
      else if (back) window.location.href = back;
    });

    tg.onEvent?.("themeChanged", () => {
      tg.setHeaderColor?.("secondary_bg_color");
      tg.setBackgroundColor?.("secondary_bg_color");
    });
  }

  // Attach Telegram initData to every HTMX request
  document.addEventListener("htmx:configRequest", (e) => {
    if (tg?.initData) {
      e.detail.headers["X-Telegram-Init-Data"] = tg.initData;
    }
  });

  document.addEventListener("htmx:afterSettle", syncNavigationState);
  window.addEventListener("popstate", syncNavigationState);

  // Instant 0ms visual feedback on bottom nav, segmented filter tabs, and haptic elements
  document.addEventListener("click", (e) => {
    const tabItem = e.target.closest(".bottom-nav-item");
    if (tabItem) {
      tg?.HapticFeedback?.selectionChanged();
      document.querySelectorAll(".bottom-nav-item").forEach((el) => {
        el.classList.remove("text-accent-text", "font-semibold");
        el.classList.add("text-hint");
      });
      tabItem.classList.add("text-accent-text", "font-semibold");
      tabItem.classList.remove("text-hint");
    }

    const segTab = e.target.closest(".filter-tab, .leaderboard-tab");
    if (segTab) {
      const groupSelector = segTab.classList.contains("filter-tab")
        ? ".filter-tab"
        : ".leaderboard-tab";
      document.querySelectorAll(groupSelector).forEach((tab) => {
        tab.classList.remove("bg-bg", "text-text", "shadow-sm", "font-semibold");
        tab.classList.add("text-hint");
      });
      segTab.classList.add("bg-bg", "text-text", "shadow-sm", "font-semibold");
      segTab.classList.remove("text-hint");
      tg?.HapticFeedback?.selectionChanged();
    }

    if (e.target.closest("[data-haptic]")) {
      tg?.HapticFeedback?.impactOccurred("light");
    }
  });

  // Centralized HTMX error handling
  document.addEventListener("htmx:responseError", (e) => {
    tg?.HapticFeedback?.notificationOccurred("error");
    const msg = extractErrorMessage(e.detail?.xhr?.responseText);
    showNativeAlert(msg);
  });
}

syncNavigationState();

// ---------------------------------------------------------------------------
// 3. Telegram Share & Adsgram Rewarded Video
// ---------------------------------------------------------------------------
window.shareConfession = function (id, snippet) {
  const shareText = `Guarda questo segreto anonimo su Hot-Mic! 🔥\n\n"${snippet}"\n\nScopri di più:`;
  const shareUrl = `https://t.me/${window.BOT_USERNAME || "HotMicBot"}/app?startapp=confession_${id}`;

  fetch(`/confessions/${id}/share`, {
    method: "POST",
    headers: {
      ...(tg?.initData ? { "X-Telegram-Init-Data": tg.initData } : {}),
    },
  })
    .then((r) => r.json())
    .then((data) => {
      const el = document.getElementById(`shares-count-${id}`);
      if (el && data.shares_count) el.textContent = data.shares_count;
    })
    .catch(() => {});

  const tgShareLink = `https://t.me/share/url?url=${encodeURIComponent(shareUrl)}&text=${encodeURIComponent(shareText)}`;
  if (tg?.openTelegramLink) {
    tg.openTelegramLink(tgShareLink);
  } else {
    window.open(tgShareLink, "_blank", "noopener,noreferrer");
  }
};

let adsgramController = null;

function getAdsgramController() {
  if (adsgramController) return adsgramController;
  if (window.Adsgram && window.ADSGRAM_BLOCK_ID) {
    try {
      adsgramController = window.Adsgram.init({
        blockId: window.ADSGRAM_BLOCK_ID,
        debug: false,
      });
    } catch (e) {
      console.warn("Adsgram init error:", e);
    }
  }
  return adsgramController;
}

window.watchRewardedAd = function () {
  const btn = document.getElementById("ad-reward-btn");
  if (btn) btn.disabled = true;

  const claimReward = () => {
    fetch("/ads/reward", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(tg?.initData ? { "X-Telegram-Init-Data": tg.initData } : {}),
      },
    })
      .then(async (res) => {
        const data = await res.json().catch(() => null);
        if (res.ok) {
          document.querySelectorAll(".user-coins-display").forEach((el) => {
            el.textContent = `${data.coins_balance} 🪙`;
          });
          tg?.HapticFeedback?.notificationOccurred("success");
          showNativeAlert(data?.message || "Hai guadagnato 20 monete! 🪙");
        } else {
          tg?.HapticFeedback?.notificationOccurred("error");
          showNativeAlert(
            extractErrorMessage(data, "Impossibile riscattare la ricompensa al momento.")
          );
        }
      })
      .catch(() => {
        showNativeAlert("Errore di connessione durante l'accredito monete.");
      })
      .finally(() => {
        if (btn) btn.disabled = false;
      });
  };

  const controller = getAdsgramController();
  if (controller) {
    controller
      .show()
      .then(claimReward)
      .catch(() => {
        if (btn) btn.disabled = false;
        tg?.HapticFeedback?.notificationOccurred("warning");
      });
  } else {
    const origText = btn ? btn.innerHTML : "";
    if (btn) btn.innerHTML = "<span>⏳</span><span>Caricamento...</span>";
    setTimeout(() => {
      if (btn) btn.innerHTML = origText;
      claimReward();
    }, 1500);
  }
};
