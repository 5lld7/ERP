"use strict";

(function (global) {
  function createController(runtime) {
    let options = null, generation = 0, timer = null, audio = null;
    let queue = Promise.resolve(), polling = null, lastPoll = 0;
    let seen = new Set();
    let state = { items: [], unread_count: 0, soundEnabled: false, sound_enabled: false, ready: false };
    const document = runtime.document;
    const clone = () => ({ ...state, items: state.items.map((item) => ({ ...item })) });
    const storageKey = () => `serviq-notification-sound:${options.userId}`;
    function notify() { if (options?.onUpdate) options.onUpdate(clone()); }
    function error(error) { if (options?.onError) options.onError(error); }
    function saveSound() {
      try { runtime.localStorage.setItem(storageKey(), state.soundEnabled ? "1" : "0"); } catch (_) { /* Selection works without storage. */ }
    }
    function audioContext() {
      if (!audio || audio.state === "closed") {
        const Context = runtime.AudioContext || runtime.webkitAudioContext;
        if (!Context) throw new Error("صوت الإشعارات غير متاح في هذا المتصفح");
        audio = new Context();
      }
      return audio;
    }
    function tone() {
      // Never attempt to bypass browser autoplay policy. A real user gesture
      // must have enabled/resumed this context before any notification sounds.
      if (!state.soundEnabled || !audio || audio.state !== "running") return;
      try {
        const start = audio.currentTime;
        for (const [offset, frequency] of [[0, 660], [0.15, 880]]) {
          const oscillator = audio.createOscillator(), gain = audio.createGain();
          oscillator.type = "sine";
          oscillator.frequency.setValueAtTime(frequency, start + offset);
          gain.gain.setValueAtTime(0, start + offset);
          gain.gain.linearRampToValueAtTime(0.07, start + offset + 0.025);
          gain.gain.exponentialRampToValueAtTime(0.001, start + offset + 0.17);
          oscillator.connect(gain);
          gain.connect(audio.destination);
          oscillator.start(start + offset);
          oscillator.stop(start + offset + 0.18);
        }
      } catch (_) { /* A suspended/closed audio device must not stop polling. */ }
    }
    function apply(payload) {
      const items = (Array.isArray(payload?.items) ? payload.items : []).map((item) => ({
        ...item, is_read: typeof item.is_read === "boolean" ? item.is_read : item.read_at != null,
      }));
      const unread = new Set(items.filter((item) => !item.is_read).map((item) => `${item.id}:${item.created_at}`));
      const arrivals = state.ready && [...unread].some((key) => !seen.has(key));
      const count = Number(payload?.unread_count);
      state = { ...state, items, unread_count: Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0, ready: true };
      seen = unread;
      if (arrivals) tone();
      notify();
      return clone();
    }
    function enqueue(operation) {
      const selected = generation;
      const task = queue.catch(() => {}).then(async () => {
        if (!options || selected !== generation) return clone();
        const payload = await operation();
        if (!options || selected !== generation) return clone();
        return apply(payload);
      });
      queue = task.catch(() => {});
      return task;
    }
    function refresh() {
      if (!options) return Promise.resolve(clone());
      if (polling) return polling;
      const selected = generation, fetch = options.fetchNotifications;
      lastPoll = Date.now();
      const pending = enqueue(fetch).catch((failure) => {
        if (options && selected === generation) error(failure);
        return clone();
      });
      polling = pending;
      pending.finally(() => { if (polling === pending) polling = null; });
      return pending;
    }
    function onFocus() {
      if (options && document?.visibilityState !== "hidden" && Date.now() - lastPoll > 5000) refresh();
    }
    function onGesture() {
      if (!options || !state.soundEnabled) return;
      try {
        const context = audioContext();
        if (context.state !== "running") context.resume().catch(() => {});
      } catch (_) { /* The explicit toggle reports unavailable audio support. */ }
    }
    function stop() {
      generation += 1;
      if (timer !== null) runtime.clearInterval(timer);
      timer = null;
      runtime.removeEventListener?.("focus", onFocus);
      runtime.removeEventListener?.("pointerdown", onGesture, true);
      runtime.removeEventListener?.("keydown", onGesture, true);
      document?.removeEventListener("visibilitychange", onFocus);
      if (audio) {
        const previous = audio;
        audio = null;
        try { Promise.resolve(previous.close()).catch(() => {}); } catch (_) { /* Already closed. */ }
      }
      options = null;
      queue = Promise.resolve();
      polling = null;
      seen = new Set();
      state = { items: [], unread_count: 0, soundEnabled: false, sound_enabled: false, ready: false };
    }
    function start(next) {
      if (!next || next.userId == null || typeof next.fetchNotifications !== "function") {
        stop();
        return Promise.resolve(clone());
      }
      if (options && String(options.userId) === String(next.userId)) {
        options = next;
        notify();
        return Date.now() - lastPoll > 1000 ? refresh() : Promise.resolve(clone());
      }
      stop();
      options = next;
      try { state.soundEnabled = runtime.localStorage.getItem(storageKey()) === "1"; } catch (_) { /* Disabled storage. */ }
      state.sound_enabled = state.soundEnabled;
      runtime.addEventListener?.("focus", onFocus);
      runtime.addEventListener?.("pointerdown", onGesture, true);
      runtime.addEventListener?.("keydown", onGesture, true);
      document?.addEventListener("visibilitychange", onFocus);
      timer = runtime.setInterval(() => {
        if (document?.visibilityState !== "hidden") refresh();
      }, 30000);
      notify();
      return refresh();
    }
    async function markRead(ids) {
      if (!options || typeof options.markRead !== "function") return clone();
      const operation = options.markRead;
      return enqueue(() => operation(ids));
    }
    async function toggleSound() {
      if (!options) return false;
      if (state.soundEnabled) {
        state.soundEnabled = state.sound_enabled = false;
        saveSound();
        notify();
        return false;
      }
      const selected = generation;
      const context = audioContext();
      await context.resume();
      if (!options || selected !== generation) return false;
      if (context.state !== "running") throw new Error("تعذر تشغيل صوت الإشعارات. اضغط لتفعيله مرة أخرى");
      state.soundEnabled = state.sound_enabled = true;
      saveSound();
      notify();
      return true;
    }
    return { start, stop, refresh, getState: clone, markRead, markAllRead: () => markRead(undefined), toggleSound };
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { createController };
  if (typeof window !== "undefined") global.ServiqNotifications = createController(global);
})(typeof window !== "undefined" ? window : globalThis);
