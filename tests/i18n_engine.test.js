"use strict";
const assert = require("node:assert/strict");
const { createTranslator } = require("../static/i18n.js");
const i18n = createTranslator({
  "المخزون": "Inventory", "اسم العميل": "Customer name", "أهلًا،": "Welcome,",
  "إضافة": "Add", "عرض": 'Show "details" & more',
}, { language: "en" });
assert.equal(i18n.t("  المخزون  "), "  Inventory  ");
assert.equal(i18n.t("إضافة اسم العميل"), "Add Customer name");
assert.equal(i18n.t("المخزونات"), "المخزونات", "Do not replace part of an Arabic word");
const customer = "المخزون <img src=x onerror=alert(1)> & 'quote'";
const escaped = i18n.escape(customer);
assert(!escaped.includes("المخزون"));
assert(!escaped.includes("<img"));
const markup = `<label title="عرض">اسم العميل<input value="${escaped}" placeholder="اسم العميل" data-status="المخزون"></label><p>${escaped}</p>`;
const result = i18n.html(markup);
assert(result.includes('title="Show &quot;details&quot; &amp; more"'));
assert(result.includes('placeholder="Customer name"'));
assert(result.includes('data-status="المخزون"'), "Canonical data attributes are untouched");
assert(result.includes(`value="${escaped}"`), "Stored field values stay byte-for-byte encoded");
assert(result.includes(`<p>${escaped}</p>`), "User names matching UI terms are not translated");
assert.equal(i18n.html('<script>const a="المخزون"</script><style>.المخزون{}</style>'), '<script>const a="المخزون"</script><style>.المخزون{}</style>');
assert.equal(i18n.html('<!-- المخزون --><b>المخزون</b>'), '<!-- المخزون --><b>Inventory</b>');
i18n.setLanguage("ar");
assert.equal(i18n.t("المخزون"), "المخزون");
assert.equal(i18n.html("<b>المخزون</b>"), "<b>المخزون</b>");
assert.equal(i18n.locale, "ar-EG");
i18n.setLanguage("en");
assert.equal(i18n.locale, "en-US");
i18n.setLanguage("unsupported");
assert.equal(i18n.language, "en");
console.log("PASS: bilingual engine, escaping, data preservation, safe HTML and locale selection");
