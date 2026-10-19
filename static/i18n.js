"use strict";

(function (global) {
  const arabic = /[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]/;
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

  function createTranslator(initialCatalog = {}, options = {}) {
    let language = options.language === "en" ? "en" : "ar";
    let phrases = null;
    const catalog = new Map();
    const missing = new Set();
    const api = {
      get language() { return language; },
      get locale() { return language === "en" ? "en-US" : "ar-EG"; },
      get untranslated() { return [...missing]; },
      addCatalog(entries) {
        for (const [source, target] of Object.entries(entries)) {
          if (source && typeof target === "string") catalog.set(source, target);
        }
        phrases = null;
      },
      setLanguage(value) {
        if (value !== "ar" && value !== "en") return;
        language = value;
        missing.clear();
        if (options.onLanguageChange) options.onLanguageChange(value);
      },
      // Encode Arabic in business data as entities BEFORE translating markup.
      // The browser decodes the exact original value, while the translator only
      // sees literal UI text. Customer names that equal a UI label stay intact.
      escape(value) {
        return escapeHTML(value).replace(/[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]/g,
          (char) => `&#x${char.codePointAt(0).toString(16)};`);
      },
      t(value) { return translate(String(value ?? ""), false); },
      html(value) {
        let rawTag = null;
        return String(value ?? "").replace(/<!--[\s\S]*?-->|<[^>]*>|[^<]+|</g, (part) => {
          if (part.startsWith("<!--")) return part;
          if (part.startsWith("<")) {
            const tag = /^<\s*(\/?)([a-z][\w-]*)/i.exec(part);
            if (tag) {
              const name = tag[2].toLowerCase();
              if (tag[1] && name === rawTag) rawTag = null;
              else if (!tag[1] && (name === "script" || name === "style")) rawTag = name;
            }
            // Never translate values, IDs, data attributes, links or source code.
            return part.replace(/(\b(?:aria-label|aria-description|title|placeholder|alt)\s*=\s*)(["'])([\s\S]*?)\2/gi,
              (_, prefix, quote, text) => prefix + quote + translate(text, true) + quote);
          }
          return rawTag ? part : translate(part, true);
        });
      },
    };
    function translate(source, forHTML) {
      if (language !== "en" || !arabic.test(source)) return source;
      const encode = forHTML ? escapeHTML : (text) => text;
      const whitespace = /^(\s*)([\s\S]*?)(\s*)$/.exec(source);
      const core = whitespace[2];
      if (catalog.has(core)) return whitespace[1] + encode(catalog.get(core)) + whitespace[3];
      if (phrases === null) {
        const keys = [...catalog.keys()].filter((key) => arabic.test(key))
          .sort((a, b) => b.length - a.length)
          .map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
        phrases = keys.length ? new RegExp(`(?<![\\p{L}\\p{N}_])(?:${keys.join("|")})(?![\\p{L}\\p{N}_])`, "gu") : false;
      }
      const result = phrases ? source.replace(phrases, (phrase) => encode(catalog.get(phrase))) : source;
      if (arabic.test(result)) missing.add(source.trim());
      return result;
    }
    api.addCatalog(initialCatalog);
    return api;
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { createTranslator };
  if (typeof document === "undefined") return;
  let language = "ar";
  try { language = localStorage.getItem("serviq-language") || localStorage.getItem("madar-language") || "ar"; } catch (_) { /* Private storage can be disabled. */ }
  const i18n = createTranslator({}, {
    language,
    onLanguageChange(value) {
      try { localStorage.setItem("serviq-language", value); } catch (_) { /* The selection still works for this session. */ }
      document.documentElement.lang = value;
      document.documentElement.dir = value === "en" ? "ltr" : "rtl";
      document.title = value === "en" ? "Serviq | Business Management" : "Serviq | نظام إدارة الأعمال";
      const loading = document.querySelector(".initial-loading p");
      if (loading) loading.textContent = value === "en" ? "Preparing your workspace…" : "نجهّز مساحة عملك…";
      const mark = document.querySelector(".initial-loading .brand-mark");
      if (mark) mark.textContent = "S";
    },
  });
  global.I18n = i18n;
  i18n.setLanguage(i18n.language);
  i18n.ready = Promise.all(["/locales/en-data.json", "/locales/en-ui.json"].map(async (path) => {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) throw new Error("Unable to load the language catalog");
    return response.json();
  })).then((catalogs) => catalogs.forEach((catalog) => i18n.addCatalog(catalog)));
})(globalThis);
