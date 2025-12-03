// panel/static/panel/js/aliboard_crdt_core.js
// Prosty rdzeń CRDT / shared-doc dla Aliboard
// Na razie NIE integrujemy z rysowaniem – tylko model danych.

(function () {
  console.log("[AliboardDoc] init core…");

  // id -> element (obiekt JSON): { id, type, pageIndex, x, y, w, h, ... }
  const elements = new Map();

  // Subskrybenci zmian (np. tablica, która będzie chciała się prze-rysować)
  const subscribers = new Set();

  function notify() {
    const snapshot = getElementsArray();
    subscribers.forEach((fn) => {
      try {
        fn(snapshot);
      } catch (err) {
        console.error("[AliboardDoc] subscriber error", err);
      }
    });
  }

  function getElementsArray() {
    return Array.from(elements.values());
  }

  // ---- API dla lokalnych operacji (z poziomu tablicy) ----

  /**
   * Dodaj/ nadpisz element lokalnie (np. po przesunięciu obrazka).
   * Element musi mieć przynajmniej id oraz type.
   */
  function upsertLocal(element) {
    if (!element || !element.id || !element.type) {
      console.warn("[AliboardDoc] upsertLocal: brak id/type", element);
      return;
    }
    elements.set(element.id, { ...element });
    notify();
  }

  /**
   * Usuń element lokalnie (np. gumką / usuń zaznaczony).
   */
  function removeLocal(id) {
    if (!id) return;
    elements.delete(id);
    notify();
  }

  // ---- API dla danych z serwera (snapshot / add / update / remove) ----

  /**
   * Zastosuj pełny snapshot z serwera.
   * Oczekuje tablicy elementów JSON.
   */
  function applySnapshot(list) {
    elements.clear();
    if (Array.isArray(list)) {
      list.forEach((el) => {
        if (el && el.id && el.type) {
          elements.set(el.id, { ...el });
        }
      });
    }
    console.log("[AliboardDoc] snapshot applied:", elements.size, "elements");
    notify();
  }

  /**
   * Zastosuj pojedynczy element_add z serwera.
   */
  function applyRemoteAdd(element) {
    if (!element || !element.id || !element.type) return;
    elements.set(element.id, { ...element });
    notify();
  }

  /**
   * Zastosuj element_update z serwera.
   */
  function applyRemoteUpdate(element) {
    if (!element || !element.id || !element.type) return;
    elements.set(element.id, { ...element });
    notify();
  }

  /**
   * Zastosuj element_remove z serwera.
   */
  function applyRemoteRemove(id) {
    if (!id) return;
    elements.delete(id);
    notify();
  }

  // ---- Subskrypcje ----

  /**
   * Podłącz callback, który ma być wołany przy każdej zmianie stanu.
   * Zwraca funkcję do wypisania (unsubscribe).
   */
  function subscribe(fn) {
    if (typeof fn !== "function") return () => {};
    subscribers.add(fn);
    // od razu daj aktualny stan
    try {
      fn(getElementsArray());
    } catch (err) {
      console.error("[AliboardDoc] subscriber initial error", err);
    }
    return () => {
      subscribers.delete(fn);
    };
  }

  // ---- ID helper (przyda się później do PDF/obrazów) ----

  function generateId(prefix) {
    const base =
      (window.crypto?.randomUUID && window.crypto.randomUUID()) ||
      `rnd-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return (prefix || "el_") + base;
  }

  // ---- Eksport globalny ----

  window.AliboardDoc = {
    // stan
    getElementsArray,
    // lokalne modyfikacje
    upsertLocal,
    removeLocal,
    // dane z serwera
    applySnapshot,
    applyRemoteAdd,
    applyRemoteUpdate,
    applyRemoteRemove,
    // subskrypcje
    subscribe,
    // pomocnicze ID
    generateId,
  };
})();
