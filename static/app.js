"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (value) => window.I18n.escape(value);
const t = (text) => window.I18n.t(text);
function setHTML(element, markup) {
  element.innerHTML = window.I18n.html(markup);
}
function languageButton(extraClass = "") {
  const next = window.I18n.language === "ar" ? "English" : "العربية";
  const description = window.I18n.language === "ar" ? "Switch to English" : "Switch to Arabic";
  return `<button type="button" class="btn secondary language-toggle ${extraClass}" data-action="language" lang="${window.I18n.language === "ar" ? "en" : "ar"}" dir="auto" aria-label="${description}">${next}</button>`;
}
const numeric = (value) =>
  new Intl.NumberFormat(window.I18n.locale, { maximumFractionDigits: 2, numberingSystem: "latn" }).format(
    Number(value || 0),
  );
const dateNow = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const state = {
  boot: null,
  page: "dashboard",
  rows: [],
  catalog: null,
  documentLines: [],
  docKind: "sale",
  source: null,
  search: "",
  reportRows: [],
  requestId: 0,
};
const icons = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.7"/><rect x="14" y="3" width="7" height="7" rx="1.7"/><rect x="3" y="14" width="7" height="7" rx="1.7"/><rect x="14" y="14" width="7" height="7" rx="1.7"/>',
  box: '<path d="m12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8M7 5.8l9 5"/>',
  chart: '<path d="M4 3v17h17M8 15l4-5 4 2 5-7"/><path d="M16 5h5v5"/>',
  users:
    '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 4v2"/>',
  wallet:
    '<path d="M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h16v12H5a3 3 0 0 1-3-3V6"/><path d="M21 12h-6v5h6M17 14.5h.01"/>',
  cart: '<path d="M2 3h3l3 13h11l3-10H6M9 21h.01M19 21h.01"/><circle cx="9" cy="20" r="1"/><circle cx="19" cy="20" r="1"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  whatsapp: '<path d="M21 11.5a9 9 0 0 1-13 8L3 21l1.5-5A9 9 0 1 1 21 11.5Z"/><path d="M8 7c0 5 4 9 9 9l1-3-3-1-1 1c-2-1-3-2-4-4l1-1-1-3Z"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  arrow: '<path d="M19 12H5m6-6-6 6 6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  settings:
    '<path d="m9 3-1 3-3 1-2 4 2 2v4l4 3 3-1 3 1 4-3v-4l2-2-2-4-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>',
  logout: '<path d="M9 3H4v18h5M10 12h12m-5-5 5 5-5 5"/>',
  file: '<path d="M14 2H5v20h14V7zM14 2v5h5M8 12h8M8 16h8"/>',
  check: '<path d="m5 12 4 4L20 5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  filter: '<path d="M3 5h18M6 12h12M10 19h4M7 3v4M16 10v4M12 17v4"/>',
  edit: '<path d="m15 4 5 5M3 21l5-1L21 7a3.5 3.5 0 0 0-5-5L3 15z"/>',
  trash: '<path d="M3 6h18M8 6V3h8v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7"/><circle cx="12" cy="12" r="3"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 2v6M16 2v6M7 14h3M14 14h3M7 17h3"/>',
  branch:
    '<circle cx="6" cy="4" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="6" cy="20" r="2"/><path d="M6 6v12M6 14c9 0 12-2 12-5"/>',
  shield: '<path d="M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6"/>',
  spark: '<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  print: '<path d="M6 9V3h12v6M6 18H3v-8h18v8h-3M6 14h12v7H6zM17 12h1"/>',
  receipt:
    '<path d="M5 3l3 2 4-2 4 2 3-2v18l-3-2-4 2-4-2-3 2zM8 9h8M8 13h8M8 17h4"/>',
  barcode: '<path d="M3 3v18M6 3v18M10 3v18M12 3v18M16 3v18M19 3v18M21 3v18"/>',
  building:
    '<path d="M4 21V3h16v18M2 21h20M8 7h2M14 7h2M8 11h2M14 11h2M10 21v-6h4v6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
};
function icon(name, cls = "") {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
}
// Keep legacy company currency values readable without changing financial data.
function currencyCode(value = state.boot?.settings.currency || "EGP") {
  const aliases = { "ج.م": "EGP", "جنيه مصري": "EGP", "ر.س": "SAR", "ريال سعودي": "SAR", "د.إ": "AED", "درهم إماراتي": "AED", "ر.ق": "QAR", "ريال قطري": "QAR", "€": "EUR", "£": "GBP", "$": "USD" };
  const candidate = aliases[value] || String(value).toUpperCase();
  return state.boot?.currencies?.some((item) => item.code === candidate) ? candidate : value;
}
function currencyText(value = state.boot?.settings.currency || "EGP") {
  const currency = state.boot?.currencies?.find((item) => item.code === currencyCode(value));
  return currency ? currency[window.I18n.language === "en" ? "symbol_en" : "symbol_ar"] || currency.code : value;
}
const money = (n) => `${numeric(n)} <small>${esc(currencyText())}</small>`;
function currencyField() {
  const current = currencyCode();
  const currencies = state.boot.currencies || [];
  const known = currencies.some((item) => item.code === current);
  return `<label class="field"><span>العملة الأساسية للشركة <b>*</b></span><select name="currency" required ${state.boot.currency_locked ? "disabled" : ""} aria-describedby="currency-help">${!known ? `<option value="${esc(current)}" selected>${esc(state.boot.settings.currency)}</option>` : ""}${currencies.map((item) => `<option value="${esc(item.code)}" ${current === item.code ? "selected" : ""}>${esc(item.code)} — ${esc(item[window.I18n.language === "en" ? "label_en" : "label_ar"])}</option>`).join("")}</select><small id="currency-help">${state.boot.currency_locked ? "تم تثبيت العملة لوجود قيود مالية. حافظًا على الأرصدة، لا يمكن تغييرها." : "تستخدم الشركة عملة أساسية واحدة لكل الحسابات والفواتير. لا يتم تحويل المبالغ تلقائيًا."}</small></label>`;
}
function accountingCurrencyPanel() {
  return `<section class="panel settings-panel currency-panel"><header class="panel-header"><div><h2>عملة الحسابات</h2><p>اختر العملة الأساسية للشركة قبل تسجيل أول حركة مالية.</p></div>${icon("wallet")}</header>${allowed("admin") ? `<form id="currency-form"><div class="form-grid one">${currencyField()}</div><div class="form-error" role="alert"></div>${!state.boot.currency_locked ? '<button class="btn primary" type="submit">حفظ العملة الأساسية</button>' : ""}</form>` : `<p>${esc(currencyText())}</p><p class="muted">يمكن لمسؤول النظام تحديد العملة الأساسية للشركة.</p>`}</section>`;
}
const modules = {
  accounting: {
    name: "الحسابات المالية",
    short: "الحسابات",
    icon: "wallet",
    color: "blue",
    description: "رؤية مالية واضحة، من القيد إلى الميزانية.",
    groups: [
      [
        "العمليات المالية",
        [
          "doc_purchase",
          "doc_purchase_return",
          "suppliers",
          "customers",
          "payments",
          "journal",
        ],
      ],
      [
        "الأصول والتقارير",
        [
          "accounts",
          "assets",
          "report_trial_balance",
          "report_income",
          "report_balance_sheet",
          "report_cashflow",
          "report_tax",
          "report_customer_balances",
          "report_supplier_balances",
          "report_statement",
        ],
      ],
    ],
  },
  inventory: {
    name: "المخازن والفروع",
    short: "المخزون",
    icon: "box",
    color: "green",
    description: "كل صنف في مكانه، وكل حركة محسوبة.",
    groups: [
      [
        "إدارة المخزون",
        ["products", "branches", "warehouses", "categories", "units"],
      ],
      [
        "الحركات والتوريد",
        [
          "doc_purchase_order",
          "doc_receipt",
          "doc_transfer",
          "doc_issue",
          "doc_adjustment",
        ],
      ],
      ["تقارير المخزون", ["report_stock", "report_moves"]],
    ],
  },
  sales: {
    name: "المعاينات والمبيعات",
    short: "المبيعات",
    icon: "chart",
    color: "orange",
    description: "من أول معاينة إلى آخر فاتورة.",
    groups: [
      [
        "المبيعات والعملاء",
        ["customers", "doc_inspection", "doc_sale", "doc_sale_return", "pos"],
      ],
      [
        "الأسعار والتقارير",
        [
          "price_lists",
          "report_sales",
          "report_sales_summary",
          "report_inspections",
          "report_best_customers",
          "report_best_products",
        ],
      ],
    ],
  },
  hr: {
    name: "الموارد البشرية",
    short: "الموظفين",
    icon: "users",
    color: "purple",
    description: "تفاصيل فريقك، في مساحة واحدة.",
    groups: [
      [
        "شؤون الموظفين",
        ["employees", "departments", "jobs", "attendance", "leaves"],
      ],
      [
        "الرواتب والتقارير",
        [
          "payroll",
          "employee_adjustments",
          "loans",
          "report_payroll",
          "report_attendance",
        ],
      ],
    ],
  },
};
const reportNames = {
  best_customers: "أفضل العملاء",
  sales_summary: "ملخص المبيعات حسب اليوم والشهر والفرع",
  stock: "المخزون العام وحدود التنبيه",
  moves: "حركة الأصناف والتحويلات",
  trial_balance: "ميزان المراجعة",
  income: "قائمة الدخل والأرباح",
  balance_sheet: "الميزانية العمومية",
  tax: "التقرير الضريبي",
  sales: "المبيعات اليومية والشهرية والفروع",
  purchases: "تقرير المشتريات",
  inspections: "تقرير المعاينات",
  best_products: "الأصناف الأكثر مبيعًا وربحيتها",
  customer_balances: "أرصدة العملاء",
  supplier_balances: "أرصدة الموردين",
  statement: "كشف حساب عميل أو مورد",
  cashflow: "التدفقات النقدية والبنكية",
  payroll: "كشف الرواتب وتكاليف الموظفين",
  attendance: "تقرير الحضور والغياب",
  assets: "سجل الأصول والإهلاك",
};
const labels = {
  payments: "المصروفات والإيرادات",
  journal: "القيود اليومية",
  payroll: "مسيرات الرواتب",
  loans: "سلف الموظفين",
  pos: "نقطة البيع",
  reports: "مركز التقارير",
  settings: "إعدادات النظام",
  users: "المستخدمون والصلاحيات",
  audit: "سجل النشاط",
  dashboard: "نظرة عامة",
  documents: "المستندات",
  files: "الملفات والعقود",
};
const colNames = {
  id: "#",
  name: "الاسم",
  sku: "كود الصنف",
  barcode: "الباركود",
  phone: "الهاتف",
  email: "البريد الإلكتروني",
  address: "العنوان",
  tax_number: "الرقم الضريبي",
  classification: "التصنيف",
  credit_limit: "حد الائتمان",
  payment_terms: "شروط الدفع",
  number: "رقم المستند",
  date: "التاريخ",
  kind: "النوع",
  status: "الحالة",
  total: "الإجمالي",
  paid: "المدفوع",
  remaining: "المتبقي",
  due_date: "الاستحقاق",
  party: "الطرف",
  warehouse: "المخزن",
  branch: "الفرع",
  code: "الكود",
  type: "النوع",
  debit: "مدين",
  credit: "دائن",
  balance: "الرصيد",
  value: "القيمة",
  description: "البيان",
  source_type: "المصدر",
  source_id: "رقم المصدر",
  created_at: "وقت التسجيل",
  direction: "النوع",
  method: "طريقة الدفع",
  amount: "المبلغ",
  note: "ملاحظات",
  document: "المستند",
  month: "الشهر",
  employees: "عدد الموظفين",
  employee: "الموظف",
  installment: "القسط",
  quantity: "الكمية",
  price: "السعر",
  cost: "التكلفة",
  min_stock: "حد الطلب",
  expiry_date: "الصلاحية",
  product: "الصنف",
  reason: "البيان",
  revenue: "صافي المبيعات",
  profit: "مجمل الربح",
  taxable: "الوعاء الضريبي",
  tax: "الضريبة",
  tax_rate: "النسبة %",
  basic: "الأساسي",
  allowance: "البدلات",
  overtime: "الإضافي",
  bonus: "المكافأة",
  deduction: "الخصومات",
  absence: "خصم الغياب",
  loan: "السلف",
  net: "الصافي",
  department: "الإدارة",
  check_in: "حضور",
  check_out: "انصراف",
  overtime_hours: "ساعات إضافية",
  purchase_date: "تاريخ الشراء",
  salvage: "التخريدية",
  life_months: "العمر بالشهور",
  depreciation: "مجمع الإهلاك",
  book_value: "القيمة الدفترية",
  user: "المستخدم",
  action: "الإجراء",
  entity: "القسم",
  entity_id: "رقم السجل",
  detail: "التفاصيل",
  username: "اسم الدخول",
  role: "الصلاحية",
  active: "نشط",
  progress: "مرحلة المعاينة",
  appointment_date: "موعد المعاينة",
  location: "موقع المعاينة",
  size: "الحجم (بايت)",
  period: "الفترة",
  invoices: "عدد الفواتير",
};
function title(page) {
  if (modules[page]) return modules[page].name;
  if (page.startsWith("doc_"))
    return state.boot?.kinds[page.slice(4)]?.[0] || "المستندات";
  if (page.startsWith("report_"))
    return reportNames[page.slice(7)] || "التقرير";
  return state.boot?.resources[page]?.label || labels[page] || page;
}
function allowed(module, write = false) {
  const role = state.boot?.user.role;
  return (
    role === "admin" ||
    role === module ||
    (!write && role === "viewer" && module !== "admin")
  );
}
function canPage(page) {
  if (modules[page]) return allowed(page);
  if (page.startsWith("doc_")) return Boolean(state.boot.kinds[page.slice(4)]);
  if (page.startsWith("report_"))
    return Boolean(state.boot.reports[page.slice(7)]);
  if (page === "pos") return allowed("sales");
  if (["users", "audit", "settings"].includes(page)) return allowed("admin");
  if (["payments", "journal"].includes(page)) return allowed("accounting");
  if (["loans", "payroll"].includes(page)) return allowed("hr");
  return (
    Boolean(state.boot.resources[page]) ||
    ["dashboard", "reports"].includes(page)
  );
}
async function api(path, opts = {}) {
  const response = await fetch(`/api/${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-ERP-Request": "1",
      "Accept-Language": window.I18n.language,
      ...(opts.headers || {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("تعذّر قراءة رد الخادم");
  }
  if (!response.ok) {
    if (response.status === 401 && state.boot) {
      state.boot = null;
      renderAuth(false);
    }
    const error = new Error(data.error || t("تعذّر تنفيذ الطلب"));
    error.localized = Boolean(data.error);
    throw error;
  }
  return data;
}
function errorText(error) {
  // Backend errors are already localized and may contain a customer's exact name.
  return error.localized ? error.message : t(error.message);
}
function toast(message, error = false) {
  const el = document.createElement("div");
  el.className = `toast ${error ? "error" : ""}`;
  setHTML(el, `${icon(error ? "info" : "check")}<span>${esc(error ? message : t(message))}</span>`);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 5500);
}
function button(text, action, cls = "primary", extra = "") {
  return `<button type="button" class="btn ${cls}" data-action="${action}" ${extra}>${text}</button>`;
}
function badge(value) {
  const status = {
    posted: ["مرحّل", "green"],
    draft: ["مسودة", "gray"],
    معتمدة: ["معتمدة", "green"],
    "قيد المراجعة": ["قيد المراجعة", "orange"],
    مرفوضة: ["مرفوضة", "red"],
    نشط: ["نشط", "green"],
    حاضر: ["حاضر", "green"],
    غائب: ["غائب", "red"],
    إجازة: ["إجازة", "purple"],
  };
  const [label, color] = status[value] || [value, "gray"];
  return `<span class="badge ${color}"><i></i>${esc(t(label))}</span>`;
}
function empty(
  message = "لا توجد سجلات بعد",
  detail = "ابدأ بإضافة أول سجل، وستظهر بياناتك هنا.",
  detailIsLocalized = false,
) {
  return `<div class="empty">${icon("file")}<h3>${esc(t(message))}</h3><p>${esc(detailIsLocalized ? detail : t(detail))}</p></div>`;
}
function modal(title, content, wide = false) {
  setHTML($("#modal-root"), `<div class="modal-backdrop"><section class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabindex="-1"><header class="modal-header"><div><span class="eyebrow">Serviq / مساحة العمل</span><h2 id="modal-title">${esc(t(title))}</h2></div>${button(icon("close"), "close", "icon-button", 'aria-label="إغلاق"')}</header>${content}</section></div>`);
  $(".modal").focus();
  setTimeout(
    () => $(".modal input:not([type=hidden]), .modal select")?.focus(),
    30,
  );
  document.body.classList.add("has-modal");
}
function closeModal() {
  if ($("#modal-root").innerHTML) {
    setHTML($("#modal-root"), "");
    document.body.classList.remove("has-modal");
  }
}
function modalFooter(label = "حفظ البيانات") {
  return `<footer class="modal-footer"><button class="btn primary" type="submit">${icon("check")}${label}</button>${button("إلغاء", "close", "secondary")}</footer>`;
}
function inputField(f, value) {
  const key = f.key;
  let input;
  const required = f.required ? "required" : "";
  if (f.type === "ref" || f.type === "select") {
    const options =
      f.type === "ref"
        ? (state.boot.refs[f.ref] || []).map((o) => ({
            value: o.id,
            label: f.ref === "accounts" ? accountLabel(o.name, o) : o.name,
          }))
        : f.options.map((o) => ({
            value: typeof o === "object" ? o.value : o,
            label: typeof o === "object" ? o.label : o,
          }));
    input = `<select name="${key}" ${required}><option value="">اختر ${esc(t(f.label))}</option>${options.map((o) => `<option value="${esc(o.value)}" ${String(value ?? "") === String(o.value) ? "selected" : ""}>${esc(f.type === "select" && f.translateOptions !== false ? t(o.label) : o.label)}</option>`).join("")}</select>`;
  } else if (f.type === "textarea")
    input = `<textarea name="${key}" ${required} rows="3">${esc(value ?? "")}</textarea>`;
  else {
    const type = ["money", "number"].includes(f.type)
      ? "number"
      : f.type || "text";
    input = `<input name="${key}" type="${type}" value="${esc(value ?? "")}" ${required} ${["money", "number"].includes(f.type) ? 'min="0" step="' + (f.type === "money" ? "0.01" : "0.001") + '"' : ""} ${f.type === "password" ? 'minlength="10" autocomplete="new-password"' : ""} ${key === "username" ? 'autocomplete="username" dir="ltr"' : ""} placeholder="${esc(t(f.placeholder || f.label))}">`;
  }
  return `<label class="field ${f.type === "textarea" ? "full" : ""}"><span>${esc(t(f.label))} ${f.required ? "<b>*</b>" : ""}</span>${input}</label>`;
}
function formData(form) {
  return Object.fromEntries(new FormData(form));
}
function nav(page) {
  location.hash = `/${page}`;
}
async function refreshBoot() {
  state.boot = await api("bootstrap");
}
function renderAuth(setup, setupTokenRequired = false) {
  state.auth = { setup, setupTokenRequired };
  setHTML($("#app"), `<main class="auth-layout"><section class="auth-story"><a class="brand"><span class="brand-mark">${icon("chart")}</span><span>Serviq<small>نظام إدارة الأعمال</small></span></a><div><span class="pill light">مساحة واحدة. أعمال مترابطة.</span><h1>كل تفاصيل شغلك،<br><em>في مساحة واحدة.</em></h1><p>الحسابات والمخزون والمبيعات وفريق العمل.<br>نظام عربي يجمع الصورة كاملة.</p><div class="auth-orbit"><div class="orbit-center">${icon("grid")}</div><span>${icon("wallet")} الحسابات</span><span>${icon("box")} المخازن</span><span>${icon("chart")} المبيعات</span><span>${icon("users")} الموظفون</span></div></div><small>مصمم لتفاصيل يومك، وقابل للنمو مع أعمالك.</small></section><section class="auth-panel">${languageButton("auth-language")}<div class="auth-card"><span class="eyebrow">أهلًا بك في Serviq</span><h2>${setup ? "لنبدأ حكاية شركتك" : "سعداء برجوعك"}</h2><p>${setup ? "أنشئ حساب المسؤول الأول. بيانات شركتك تبدأ من هنا." : "سجّل دخولك وتابع أعمالك من مكان واحد."}</p><form id="auth-form" data-setup="${setup}"><div class="form-grid one">${setup ? inputField({ key: "company_name", label: "اسم الشركة", required: true }) + inputField({ key: "name", label: "اسم المسؤول", required: true }) : ""}${setup && setupTokenRequired ? inputField({ key: "setup_token", label: "رمز إعداد المدير الأول", type: "password", required: true }) : ""}${inputField({ key: "username", label: "اسم المستخدم", required: true })}${inputField({ key: "password", label: "كلمة المرور", type: "password", required: true })}</div><p class="form-error" role="alert"></p><button class="btn primary block" type="submit">${setup ? "إنشاء مساحة العمل" : "تسجيل الدخول"} ${icon("arrow")}</button></form><div class="auth-security">${icon("shield")} ${setup ? "اختر كلمة مرور من 10 أحرف على الأقل؛ لا توجد كلمة مرور افتراضية." : "بياناتك محفوظة في قاعدة بيانات مساحة عملك."}</div></div><small class="auth-bottom">Serviq ERP · إدارة أبسط، قرارات أوضح</small></section></main>`);
}
function moduleOf(page) {
  for (const [key, m] of Object.entries(modules))
    if (page === key || m.groups.some((g) => g[1].includes(page))) return key;
  return null;
}
function shell() {
  const page = state.page,
    module = moduleOf(page),
    u = state.boot.user;
  setHTML($("#app"), `<div class="app-shell"><aside class="sidebar"><a href="#/dashboard" class="brand"><span class="brand-mark">${icon("chart")}</span><span>Serviq<small>نظام إدارة الأعمال</small></span></a><div class="workspace-label">مساحة العمل</div><a class="nav-item ${page === "dashboard" ? "active" : ""}" href="#/dashboard">${icon("grid")}<span>نظرة عامة</span></a><div class="nav-caption">إدارة أعمالك</div><nav>${Object.entries(
      modules,
    )
      .filter(([key]) => allowed(key))
      .map(
        ([key, m]) =>
          `<a class="nav-item ${module === key ? "active" : ""}" href="#/${key}">${icon(m.icon)}<span>${m.name}</span>${icon("chevron", "nav-chev")}</a>${
            module === key
              ? `<div class="subnav">${m.groups
                  .flatMap((g) => g[1])
                  .filter(canPage)
                  .map(
                    (p) =>
                      `<a href="#/${p}" class="${page === p ? "selected" : ""}">${esc(t(title(p)))}</a>`,
                  )
                  .join("")}</div>`
              : ""
          }`,
      )
      .join(
        "",
      )}<a class="nav-item ${page === "reports" ? "active" : ""}" href="#/reports">${icon("file")}<span>التقارير والتحليلات</span></a></nav><div class="sidebar-bottom"><div class="sync-card"><span class="sync-dot"></span><div>بيانات مترابطة<small>كل الأقسام في قاعدة بيانات واحدة</small></div>${icon("shield")}</div>${u.role === "admin" ? `<a class="nav-item ${page === "settings" ? "active" : ""}" href="#/settings">${icon("settings")}<span>إعدادات النظام</span></a>` : ""}<button class="user-card" data-action="profile"><span class="avatar">${esc(u.name.slice(0, 1))}</span><span>${esc(u.name)}<small>${esc(t(state.boot.roles[u.role]))}</small></span>${icon("chevron")}</button></div></aside><div class="mobile-shade" data-action="menu"></div><div class="main-wrap"><header class="topbar">${button(icon("menu"), "menu", "icon-button menu-toggle", 'aria-label="فتح القائمة"')}<div class="breadcrumbs">مساحة العمل ${icon("chevron")} <strong>${esc(t(title(page)))}</strong></div><div class="topbar-tools"><div class="search-wrap">${icon("search")}<input type="search" id="global-search" placeholder="ابحث في الصفحة الحالية…" aria-label="ابحث في الصفحة الحالية" value="${esc(state.search)}"><kbd>/</kbd></div><div class="notification-tools">${languageButton()}<button class="icon-button notification" data-action="notifications" aria-label="التنبيهات">${icon("bell")}<i></i></button></div><span class="topbar-divider"></span><span class="company-label">${icon("building")}${esc(state.boot.settings.company_name)}</span></div></header><main id="main" class="main-content"><div class="loading">جارٍ تحميل البيانات…</div></main><footer class="page-footer"><span>Serviq <b>ERP</b> <i>•</i> كل تفاصيل أعمالك، مترابطة.</span><span><i class="live-dot"></i> متصل بقاعدة البيانات</span></footer></div></div>`);
}
function pageHeader(titleText, subtitle, actions = "", titleIsHTML = false) {
  return `<div class="page-heading"><div><div class="eyebrow">${esc(state.boot.settings.company_name)} <span>/</span> مساحة العمل</div><h1>${titleIsHTML ? titleText : esc(t(titleText))}</h1><p>${esc(t(subtitle))}</p></div><div class="heading-actions">${actions}</div></div>`;
}
async function renderPage() {
  if (!state.boot) return;
  state.page = decodeURIComponent(
    location.hash.replace(/^#\//, "") || "dashboard",
  );
  state.search = "";
  const id = ++state.requestId;
  if (!canPage(state.page)) {
    state.page = "dashboard";
  }
  shell();
  try {
    // Refresh the lock when entering accounting/settings after financial posting.
    if (["accounting", "settings"].includes(state.page)) await refreshBoot();
    let html;
    if (state.page === "dashboard") html = await dashboardPage();
    else if (modules[state.page]) html = modulePage(state.page);
    else if (state.boot.resources[state.page])
      html = await resourcePage(state.page);
    else if (state.page.startsWith("doc_"))
      html = await documentsPage(state.page.slice(4));
    else if (state.page === "reports") html = reportsPage();
    else if (state.page.startsWith("report_"))
      html = await reportPage(state.page.slice(7));
    else if (state.page === "settings") html = settingsPage();
    else if (state.page === "pos") html = await posPage();
    else html = await specialPage(state.page);
    if (id === state.requestId) setHTML($("#main"), html);
  } catch (error) {
    if (id === state.requestId && $("#main"))
      setHTML($("#main"), empty("تعذّر تحميل الصفحة", errorText(error), true));
    toast(errorText(error), true);
  }
}
async function dashboardPage() {
  const d = await api("dashboard");
  state.dashboard = d;
  const date = new Intl.DateTimeFormat(window.I18n.locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());
  const stats = [
    ["مبيعات هذا الشهر", "sales", "chart", "blue", "القيمة شاملة الضريبة"],
    [
      "قيمة المخزون",
      "stock_value",
      "box",
      "green",
      `${numeric(d.products)} صنف مسجل`,
    ],
    [
      "مستحقات العملاء",
      "receivables",
      "wallet",
      "orange",
      "إجمالي الأرصدة المدينة",
    ],
    ["فريق العمل", "employees", "users", "purple", "موظف نشط في الشركة"],
  ].filter((s) => d[s[1]] !== undefined);
  if (!stats.length)
    stats.push([
      "السيولة المتاحة",
      "cash",
      "wallet",
      "green",
      "الصندوق والحسابات البنكية",
    ]);
  const max = Math.max(...(d.chart || []).map((p) => p.value), 1);
  const coords = (d.chart || []).map((p, i) => [
    42 + i * 96,
    148 - (Math.max(0, p.value) / max) * 112,
  ]);
  const path = coords
    .map((p, i) => `${i ? "L" : "M"} ${p[0]} ${p[1]}`)
    .join(" ");
  const chart = `<svg class="sales-chart" viewBox="0 0 570 185" role="img" aria-label="مبيعات آخر ستة أشهر"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#0F766E" stop-opacity=".24"/><stop offset="100%" stop-color="#0F766E" stop-opacity="0"/></linearGradient></defs>${[36, 74, 112, 150].map((y) => `<path d="M25 ${y}H555" stroke="#e5eaf0" stroke-dasharray="4 5"/>`).join("")}<path d="${path} L522 153 L42 153Z" fill="url(#chart-fill)"/><path d="${path}" fill="none" stroke="#0F766E" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${coords.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4.5" fill="#fff" stroke="#0F766E" stroke-width="2"><title>${esc(d.chart[i].month)}: ${numeric(d.chart[i].value)}</title></circle><text x="${p[0]}" y="178" text-anchor="middle" fill="#6c7e93" font-size="10">${new Intl.DateTimeFormat(window.I18n.locale, { month: "short" }).format(new Date(d.chart[i].month + "-15"))}</text>`).join("")}</svg>`;
  return `${pageHeader(`${esc(t("أهلًا،"))} ${esc(state.boot.user.name.split(" ")[0])} 👋`, "إليك نظرة شاملة على أعمالك اليوم.", `<span class="date-chip">${icon("calendar")}${esc(date)}</span>${allowed("sales", true) ? button(`${icon("plus")} فاتورة جديدة`, "new-doc", "primary", 'data-kind="sale"') : ""}`, true)}
 <section class="welcome-banner"><div><span class="pill light"><i class="live-dot"></i> أعمالك على المسار الصحيح</span><h2>صورة أوضح.<br>قرارات <em>أذكى.</em></h2><p>كل أقسام شركتك تعمل معًا. تابع الأداء،<br>واكتشف ما يحتاج انتباهك، من مكان واحد.</p><a class="hero-link" href="#/reports">استكشف تقارير أعمالك ${icon("arrow")}</a></div><div class="hero-art" aria-hidden="true"><div class="hero-rings"></div><div class="float-card inventory-float">${icon("box")}<span>المخزون<small>تحديث مع كل حركة</small></span><i class="mini-dot"></i></div><div class="hero-core">${icon("grid")}<span>Serviq</span><small>كل شيء متصل</small></div><div class="float-card finance-float">${icon("wallet")}<span>الحسابات<small>قيود مترابطة</small></span>${icon("check")}</div><div class="float-mini">${icon("users")}</div><div class="hero-cross cross-one">+</div><div class="hero-cross cross-two">+</div></div><span class="banner-tag">YOUR BUSINESS, CONNECTED</span></section>
 <section class="stats-grid">${stats.map(([label, key, ic, color, desc]) => `<article class="stat-card"><div class="stat-top"><span>${label}</span><span class="icon-tile ${color}">${icon(ic)}</span></div><div class="stat-number">${key === "employees" ? numeric(d[key]) : money(d[key])}</div><div class="stat-meta"><span class="tiny-dot ${color}"></span>${esc(t(desc))}</div></article>`).join("")}</section>
 <div class="section-label"><h2>أقسام أعمالك</h2><span>كل التفاصيل، في متناولك</span></div><section class="module-grid">${Object.entries(
   modules,
 )
   .filter(([key]) => allowed(key))
   .map(
     ([key, m]) =>
       `<a class="module-card ${m.color}" href="#/${key}"><div class="module-card-top"><span class="icon-tile ${m.color}">${icon(m.icon)}</span>${icon("arrow")}</div><h3>${m.name}</h3><p>${m.description}</p><span class="module-card-link">فتح القسم ${icon("chevron")}</span></a>`,
   )
   .join("")}</section>
 <section class="dashboard-middle">${d.chart ? `<article class="panel performance"><header class="panel-header"><div><h2>أداء المبيعات</h2><p>تابع نمو أعمالك خلال آخر 6 أشهر</p></div><span class="chart-legend"><i></i> المبيعات</span></header><div class="chart-summary">${money(d.sales)}<span>هذا الشهر</span></div>${chart}</article>` : ""}<article class="panel attention"><header class="panel-header"><div><h2>يحتاج انتباهك</h2><p>خطوات صغيرة تصنع فرقًا</p></div><span class="icon-tile orange small">${icon("bell")}</span></header><div class="attention-list">${
   d.low_stock?.length
     ? `<a href="#/report_stock"><span class="attention-icon orange">${icon("box")}</span><span><b>${d.low_stock.length} أصناف عند حد الطلب</b><small>${esc(
         d.low_stock
           .slice(0, 2)
           .map((p) => p.name)
           .join("، "),
       )}</small></span>${icon("chevron")}</a>`
     : ""
 }${d.pending_inspections !== undefined ? `<a href="#/doc_inspection"><span class="attention-icon blue">${icon("file")}</span><span><b>${numeric(d.pending_inspections)} معاينات بانتظار التحويل</b><small>تابع عروض الأسعار وفرص المبيعات</small></span>${icon("chevron")}</a>` : ""}${d.pending_leaves !== undefined ? `<a href="#/leaves"><span class="attention-icon purple">${icon("users")}</span><span><b>${numeric(d.pending_leaves)} طلبات إجازة للمراجعة</b><small>نظّم حضور فريقك واستحقاقاته</small></span>${icon("chevron")}</a>` : ""}${d.expiring?.length ? `<a href="#/products"><span class="attention-icon red">${icon("clock")}</span><span><b>${d.expiring.length} أصناف قريبة من انتهاء الصلاحية</b><small>راجع التواريخ قبل البيع</small></span>${icon("chevron")}</a>` : ""}${!d.chart && d.cash !== undefined ? `<a href="#/report_cashflow"><span class="attention-icon green">${icon("wallet")}</span><span><b>${numeric(d.cash)} السيولة المتاحة</b><small>الصندوق والبنك</small></span>${icon("chevron")}</a>` : ""}</div></article></section>
 <section class="panel"><header class="panel-header"><div><h2>آخر الحركات</h2><p>أحدث المستندات في أقسام شركتك</p></div><a class="text-link" href="#/reports">كل التقارير ${icon("arrow")}</a></header>${d.recent_documents.length ? table(d.recent_documents, ["number", "party", "kind", "date", "status", "total"], (r) => button(icon("eye"), "view-doc", "icon-button", `data-id="${r.id}" aria-label="عرض المستند"`)) : empty("مساحة أعمالك جاهزة", "أضف الأصناف والعملاء، ثم سجّل أول عملية.")}</section>
 ${state.boot.user.role === "admin" && d.products === 0 ? `<aside class="demo-banner"><span class="icon-tile green">${icon("spark")}</span><div><b>اكتشف النظام ببيانات تجريبية</b><p>أصناف وعملاء ومبيعات وموظفون؛ لتجربة دورة العمل قبل إضافة بيانات شركتك.</p></div>${button("تحميل بيانات تجريبية", "demo", "secondary")}</aside>` : ""}`;
}
function modulePage(key) {
  const m = modules[key];
  return `${pageHeader(m.name, m.description)}${key === "accounting" ? accountingCurrencyPanel() : ""}<section class="module-intro ${m.color}"><span class="intro-icon">${icon(m.icon)}</span><div><h2>تفاصيل أكثر. إدارة أسهل.</h2><p>ابدأ من البيانات الأساسية، ثم سجّل العمليات وتابع نتائجها في التقارير.</p></div><span class="pill">${icon("shield")} مرتبط بباقي الأقسام</span></section>${m.groups
    .map(
      ([name, pages]) =>
        `<div class="section-label"><h2>${name}</h2></div><div class="feature-grid">${pages
          .filter(canPage)
          .map(
            (p) =>
              `<a class="feature-card" href="#/${p}"><span class="icon-tile ${m.color}">${icon(p.startsWith("report_") ? "chart" : p.startsWith("doc_") ? "receipt" : p === "branches" ? "branch" : m.icon)}</span><h3>${esc(t(title(p)))}</h3><p>${p.startsWith("report_") ? "عرض وتحليل وتصدير البيانات" : p.startsWith("doc_") ? "إنشاء ومتابعة وترحيل المستندات" : "إضافة وتعديل وإدارة السجلات"}</p>${icon("arrow")}</a>`,
          )
          .join("")}</div>`,
    )
    .join("")}`;
}
// Only unchanged built-in chart names are presentation labels. Custom names stay exact.
const chartNames = {
  "1000": "الأصول", "1100": "الصندوق", "1110": "البنك", "1200": "العملاء",
  "1300": "المخزون", "1400": "ضريبة مدخلات", "1500": "سلف الموظفين", "1600": "الأصول الثابتة",
  "2000": "الالتزامات", "2100": "الموردون", "2200": "ضريبة مخرجات", "2300": "الرواتب المستحقة",
  "2400": "مجمع الإهلاك", "3000": "حقوق الملكية", "3100": "رأس المال والأرصدة الافتتاحية",
  "4000": "الإيرادات", "4100": "إيرادات المبيعات", "4200": "إيرادات أخرى",
  "5000": "المصروفات", "5100": "تكلفة البضاعة المباعة", "5200": "الرواتب والأجور",
  "5300": "مصروفات تشغيلية", "5400": "مصروف الإهلاك", "5500": "فروق الجرد والتالف",
};
function accountLabel(value, row) {
  if (state.page === "report_balance_sheet" && row?.code === "3999" && value === "نتيجة الأعمال المرحلة") return t(value);
  return row?.code && chartNames[row.code] === value ? t(value) : value;
}
function journalDescription(row) {
  return ["document", "payment", "payroll", "loan", "depreciation"].includes(row?.source_type)
    ? t(row.description) : row?.description;
}
function dateLabel(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return value ?? "—";
  return new Intl.DateTimeFormat(window.I18n.locale, {
    year: "numeric", month: "2-digit", day: "2-digit", numberingSystem: "latn",
  }).format(new Date(`${value}T12:00:00`));
}
function display(value, key, spec, row = null) {
  if (value === null || value === undefined || value === "")
    return '<span class="muted">—</span>';
  const f = spec?.fields.find((f) => f.key === key);
  if (f?.type === "ref") {
    const ref = state.boot.refs[f.ref]?.find((r) => r.id === Number(value));
    return esc(ref ? f.ref === "accounts" ? accountLabel(ref.name, ref) : ref.name : value);
  }
  if (key === "name") return esc(accountLabel(value, row));
  if (key === "reason" && state.page === "report_moves")
    return esc(t(state.boot.kinds[value]?.[0] || value));
  if (key === "description" && state.page === "report_statement" && row === state.reportRows[0] && value === "الرصيد الافتتاحي")
    return esc(t(value));
  if (key === "description" && row?.source_type) return esc(journalDescription(row));
  if (key === "status") return badge(value);
  if (key === "kind")
    return `<span class="doc-type">${esc(t(state.boot.kinds[value]?.[0] || erpKind(value)))}</span>`;
  if (key === "role") return esc(t(state.boot.roles[value] || value));
  if (key === "active") return badge(value ? "نشط" : "موقوف");
  if (key === "direction")
    return badge(value === "in" ? "قبض" : value === "out" ? "صرف" : value);
  if (key === "method")
    return esc(t(
      { cash: "نقدي", bank: "تحويل بنكي", card: "بطاقة" }[value] || value,
    ));
  if (f?.type === "select") {
    const option = f.options.find((o) => String(typeof o === "object" ? o.value : o) === String(value));
    return esc(t(typeof option === "object" ? option.label : option ?? value));
  }
  if (key === "source_type") return esc(t({
    document: "المستندات", payment: "سند قبض / صرف", payroll: "مسيرات الرواتب",
    loan: "سلف الموظفين", depreciation: "احتساب إهلاك الأصول", manual: "قيد يومية يدوي",
  }[value] || erpKind(value)));
  if (["progress", "type"].includes(key)) return esc(t(erpKind(value)));
  if (key === "entity") return esc(t(title(value)));
  if (key === "action") return esc(t(value));
  if (/^(?:\d{4}-\d{2}-\d{2})$/.test(String(value)) && (key === "date" || key.endsWith("_date")))
    return esc(dateLabel(value));
  if (typeof value === "number")
    return `<span class="num">${numeric(value)}</span>`;
  return esc(value);
}
function erpKind(value) {
  return (
    {
      sale: "فاتورة مبيعات",
      sale_return: "مرتجع مبيعات",
      purchase: "فاتورة مشتريات",
      purchase_return: "مرتجع مشتريات",
    }[value] || value
  );
}
function table(rows, columns, actions = null, spec = null) {
  return `<div class="table-scroll"><table><thead><tr>${columns.map((k) => `<th>${esc(t(spec?.fields.find((f) => f.key === k)?.label || colNames[k] || k))}</th>`).join("")}${actions ? '<th class="actions-col">الإجراءات</th>' : ""}</tr></thead><tbody>${rows
    .map(
      (r, i) =>
        `<tr data-search="${esc(
          Object.values(r)
            .map((v) => String(v ?? ""))
            .join(" ")
            .toLowerCase(),
        )}">${columns.map((k, j) => `<td class="${j === 0 ? "first-col" : ""}">${j === 0 && k === "name" ? `<span class="table-name"><span class="table-avatar">${esc(String(accountLabel(r[k], r)).slice(0, 1))}</span>${display(r[k], k, spec, r)}</span>` : display(r[k], k, spec, r)}</td>`).join("")}${actions ? `<td><div class="row-actions">${actions(r, i)}</div></td>` : ""}</tr>`,
    )
    .join(
      "",
    )}</tbody></table><div class="no-search-results hidden">لا توجد نتائج مطابقة للبحث</div></div>`;
}
function tableTools(count, placeholder = "بحث في السجلات…", extra = "") {
  return `<div class="table-tools"><div class="table-search">${icon("search")}<input id="table-search" type="search" placeholder="${placeholder}" aria-label="${placeholder}"></div><div class="table-controls">${extra}<span class="record-count">${numeric(count)} سجل</span></div></div>`;
}
async function resourcePage(name) {
  const spec = state.boot.resources[name];
  state.rows = await api(`resources/${name}`);
  const columns = spec.fields
    .slice(0, Math.min(name === "employees" ? 6 : 7, spec.fields.length))
    .map((f) => f.key);
  return `${pageHeader(spec.label, "أضف بياناتك وحدّثها، وستتاح تلقائيًا في العمليات المرتبطة.", allowed(spec.module, true) ? button(`${icon("plus")} إضافة ${name === "products" ? "صنف" : name === "employees" ? "موظف" : "سجل"}`, "new-resource", "primary", `data-resource="${name}"`) : "")}<section class="panel">${tableTools(state.rows.length)}${state.rows.length ? table(state.rows, columns, (r) => `${button(icon("eye"), "view-resource", "icon-button", `data-id="${r.id}" data-resource="${name}" aria-label="عرض التفاصيل"`)}${allowed(spec.module, true) ? button(icon("edit"), "edit-resource", "icon-button", `data-id="${r.id}" data-resource="${name}" aria-label="تعديل"`) + button(icon("trash"), "delete-resource", "icon-button danger-text", `data-id="${r.id}" data-resource="${name}" aria-label="حذف"`) : ""}${name === "employees" ? button(icon("file"), "employee-files", "icon-button", `data-id="${r.id}" aria-label="الملفات والعقود"`) : ""}${name === "products" ? button(icon("barcode"), "barcode", "icon-button", `data-id="${r.id}" aria-label="طباعة باركود"`) : ""}`, spec) : empty()}</section>${name === "assets" ? `<div class="inline-note">${icon("info")} تسجيل الأصل لا يسدد تكلفة شرائه تلقائيًا. سجّل قيد اقتناء الأصل في القيود اليومية، ثم احتسب الإهلاك شهريًا.${allowed("accounting", true) ? button("احتساب الإهلاك", "depreciate", "secondary") : ""}</div>` : ""}`;
}
function resourceModal(name, id = null) {
  const spec = state.boot.resources[name],
    row = id ? state.rows.find((r) => r.id === id) : {};
  modal(
    `${id ? "تعديل" : "إضافة"} — ${spec.label}`,
    `<form id="resource-form" data-resource="${name}" data-id="${id || ""}"><div class="modal-body"><div class="form-grid">${spec.fields.map((f) => inputField(f, row?.[f.key] ?? (f.type === "date" && f.required ? dateNow() : f.key === "status" ? f.options?.[0] : f.key === "classification" ? "عادي" : f.key === "leave_balance" ? state.boot.settings.leave_days : ["money", "number"].includes(f.type) ? 0 : ""))).join("")}</div><div class="form-error" role="alert"></div></div>${modalFooter()}</form>`,
  );
}
async function documentsPage(kind) {
  state.rows = await api(`documents?kind=${kind}`);
  const m = state.boot.kinds[kind][1];
  return `${pageHeader(state.boot.kinds[kind][0], "المستند المرحّل يحدّث المخزون والحسابات تلقائيًا ولا يمكن حذفه.", allowed(m, true) ? button(`${icon("plus")} مستند جديد`, "new-doc", "primary", `data-kind="${kind}"`) : "")}<section class="panel">${tableTools(state.rows.length, "ابحث برقم المستند أو الطرف…", '<select id="status-filter" aria-label="فلتر الحالة"><option value="">كل الحالات</option><option value="posted">مرحّل</option><option value="draft">مسودة</option></select>')}${state.rows.length ? table(state.rows, kind === "inspection" ? ["number", "date", "party", "progress", "appointment_date", "status", "total"] : ["number", "date", "party", "warehouse", "status", "total", "paid"], (r) => `${button(icon("eye"), "view-doc", "icon-button", `data-id="${r.id}" aria-label="عرض المستند"`)}${kind === "inspection" ? inspectionActions(r.id, true) : ""}${kind === "inspection" && allowed(m, true) ? button(icon("clock"), "inspection-progress", "icon-button", `data-id="${r.id}" aria-label="متابعة حالة المعاينة"`) : ""}${r.status === "draft" && allowed(m, true) ? button(icon("check"), "post-doc", "icon-button", `data-id="${r.id}" aria-label="ترحيل"`) + button(icon("trash"), "delete-doc", "icon-button danger-text", `data-id="${r.id}" aria-label="حذف المسودة"`) : ""}${["inspection", "purchase_order", "sale", "purchase"].includes(kind) && r.status === "posted" && allowed(m, true) ? button(icon("arrow"), "convert-doc", "icon-button", `data-id="${r.id}" aria-label="${["sale", "purchase"].includes(kind) ? "إنشاء مرتجع" : "تحويل إلى فاتورة"}"`) : ""}`) : empty()}</section>`;
}
async function documentModal(kind, source = null) {
  state.catalog = await api("catalog");
  state.docKind = kind;
  state.source = source;
  state.documentLines = source
    ? source.lines.map((l) => ({
        product_id: l.product_id,
        quantity: l.quantity,
        price: l.price,
      }))
    : [];
  const customer = ["sale", "sale_return", "inspection"].includes(kind),
    supplier = ["purchase", "purchase_return", "purchase_order"].includes(kind);
  const fiscal = [
    "sale",
    "sale_return",
    "purchase",
    "purchase_return",
    "inspection",
    "purchase_order",
  ].includes(kind);
  let originals = [];
  if (["sale_return", "purchase_return"].includes(kind) && !source)
    originals = (
      await api(
        `documents?kind=${kind === "sale_return" ? "sale" : "purchase"}`,
      )
    ).filter((d) => d.status === "posted");
  modal(
    state.boot.kinds[kind][0],
    `<form id="document-form"><div class="modal-body"><div class="inline-note compact">${icon("info")}${kind === "adjustment" ? "أدخل الكمية الفعلية بعد الجرد؛ الفرق يُرحّل على المخزون والحسابات." : kind === "receipt" ? "استلام بدون فاتورة: يثبت المخزون مقابل الأرصدة الافتتاحية. للمشتريات استخدم فاتورة مشتريات، أو حوّل أمر الشراء." : "راجع الأصناف والأسعار قبل الترحيل. المسودة لا تغيّر أرصدة المخزون أو الحسابات."}</div>${source ? `<div class="source-chip">${icon("file")} مستند مصدر: ${esc(source.number)}</div>` : ""}<div class="form-grid three">${originals.length ? inputField({ key: "original_document", label: "الفاتورة الأصلية", type: "select", translateOptions: false, required: true, options: originals.map((d) => ({ value: d.id, label: `${d.number} — ${d.party}` })) }) : ""}${inputField({ key: "date", label: "تاريخ المستند", type: "date", required: true }, dateNow())}${inputField({ key: "warehouse_id", label: "المخزن", type: "ref", required: true, ref: "warehouses" }, source?.warehouse_id || state.boot.refs.warehouses[0]?.id)}${customer ? inputField({ key: "customer_id", label: "العميل", type: "ref", required: true, ref: "customers" }, source?.customer_id) : ""}${supplier ? inputField({ key: "supplier_id", label: "المورد", type: "ref", required: true, ref: "suppliers" }, source?.supplier_id) : ""}${kind === "inspection" ? inputField({ key: "appointment_date", label: "موعد المعاينة", type: "date" }, source?.appointment_date) + inputField({ key: "location", label: "عنوان المعاينة" }, source?.location) : ""}${kind === "transfer" ? inputField({ key: "target_warehouse_id", label: "المخزن المستلم", type: "ref", required: true, ref: "warehouses" }) : ""}${fiscal ? inputField({ key: "due_date", label: "تاريخ الاستحقاق", type: "date" }, dateNow()) : ""}</div><div class="line-add"><select id="line-product" aria-label="اختر صنفًا"><option value="">اختر صنفًا لإضافته…</option>${state.catalog.products.map((p) => `<option value="${p.id}">${esc(p.sku)} — ${esc(p.name)}</option>`).join("")}</select><input type="text" id="barcode-input" placeholder="امسح الباركود ثم Enter" aria-label="قارئ الباركود" autocomplete="off">${button(`${icon("plus")} إضافة`, "add-line", "secondary")}</div><div id="document-lines"></div><div class="document-bottom"><div class="form-grid">${fiscal ? inputField({ key: "discount", label: "خصم على الفاتورة", type: "money" }, source?.discount || 0) + inputField({ key: "tax_rate", label: "ضريبة القيمة المضافة %", type: "number" }, source?.tax_rate ?? state.boot.settings.tax_rate) : ""}${
      ["sale", "sale_return", "purchase", "purchase_return"].includes(kind)
        ? inputField(
            { key: "paid", label: "المبلغ المدفوع الآن", type: "money" },
            0,
          ) +
          inputField(
            {
              key: "payment_method",
              label: "طريقة الدفع",
              type: "select",
              options: [
                { value: "cash", label: "نقدي" },
                { value: "bank", label: "تحويل بنكي" },
                { value: "card", label: "بطاقة — تسجيل سداد" },
              ],
            },
            "cash",
          )
        : ""
    }${inputField({ key: "note", label: "ملاحظات المستند", type: "textarea" }, source?.note || "")}</div><div class="invoice-summary" id="doc-summary"></div></div><div class="form-error" role="alert"></div></div><footer class="modal-footer"><button class="btn primary" type="submit" name="mode" value="post">${icon("check")} حفظ وترحيل</button><button class="btn secondary" type="submit" name="mode" value="draft">حفظ كمسودة</button>${button("إلغاء", "close", "ghost")}</footer></form>`,
    true,
  );
  renderDocLines();
}
function renderDocLines() {
  const container = $("#document-lines");
  if (!container) return;
  setHTML(container, state.documentLines.length
    ? `<div class="table-scroll"><table class="line-table"><thead><tr><th>الصنف</th><th>المتاح</th><th>الكمية ${state.docKind === "adjustment" ? "الفعلية" : ""}</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead><tbody>${state.documentLines
        .map((l, i) => {
          const p = state.catalog.products.find((p) => p.id === l.product_id),
            wid = Number($("[name=warehouse_id]")?.value);
          const stock =
            state.catalog.stocks.find(
              (s) => s.product_id === l.product_id && s.warehouse_id === wid,
            )?.quantity || 0;
          return `<tr><td><strong>${esc(p?.name)}</strong><small class="block muted">${esc(p?.sku)}</small></td><td>${numeric(stock)}</td><td><input class="line-input" data-line="${i}" data-field="quantity" type="number" step="0.001" min="${state.docKind === "adjustment" ? 0 : 0.001}" value="${l.quantity}" required aria-label="كمية ${esc(p?.name)}"></td><td><input class="line-input" data-line="${i}" data-field="price" type="number" step="0.01" min="0" value="${l.price}" required aria-label="سعر ${esc(p?.name)}"></td><td class="num line-total" data-index="${i}">${money(l.quantity * l.price)}</td><td>${button(icon("close"), "remove-line", "icon-button danger-text", `data-index="${i}" aria-label="حذف الصنف"`)}</td></tr>`;
        })
        .join("")}</tbody></table></div>`
    : empty("أضف أصناف المستند", "اختر صنفًا أو امسح باركود المنتج."));
  updateDocSummary();
}
function updateDocSummary() {
  const container = $("#doc-summary");
  if (!container) return;
  const subtotal = state.documentLines.reduce(
    (s, l) => s + Math.round(l.quantity * l.price * 100) / 100,
    0,
  );
  if (
    state.source &&
    ["sale_return", "purchase_return"].includes(state.docKind)
  ) {
    const discount = $("[name=discount]"),
      tax = $("[name=tax_rate]");
    discount.value = state.source.subtotal
      ? Math.round(
          ((subtotal * state.source.discount) / state.source.subtotal) * 100,
        ) / 100
      : 0;
    discount.readOnly = true;
    tax.value = state.source.tax_rate;
    tax.readOnly = true;
  }
  const discount = Number($("[name=discount]")?.value || 0),
    taxRate = Number($("[name=tax_rate]")?.value || 0),
    paid = Number($("[name=paid]")?.value || 0);
  const tax = Math.round((subtotal - discount) * taxRate) / 100,
    total = subtotal - discount + tax;
  setHTML(container, `<div><span>إجمالي الأصناف</span><b>${money(subtotal)}</b></div><div><span>الخصم</span><span>− ${money(discount)}</span></div><div><span>الضريبة (${numeric(taxRate)}%)</span><span>${money(tax)}</span></div><div class="grand-total"><span>الإجمالي</span><b>${money(total)}</b></div><div><span>المتبقي</span><b>${money(total - paid)}</b></div>`);
}
function addLine(pid) {
  if (!pid) return;
  const p = state.catalog.products.find((p) => p.id === Number(pid));
  if (!p) return toast("الصنف غير موجود", true);
  const exists = state.documentLines.find((l) => l.product_id === p.id);
  if (exists) exists.quantity += 1;
  else {
    const buying = [
        "purchase",
        "purchase_order",
        "purchase_return",
        "receipt",
      ].includes(state.docKind),
      cid = Number($("[name=customer_id]")?.value);
    const offers = (state.catalog.prices || [])
      .filter(
        (o) =>
          o.product_id === p.id &&
          (!o.customer_id || o.customer_id === cid) &&
          o.start_date <= dateNow() &&
          o.end_date >= dateNow(),
      )
      .sort(
        (a, b) =>
          Number(Boolean(b.customer_id)) - Number(Boolean(a.customer_id)),
      );
    state.documentLines.push({
      product_id: p.id,
      quantity: 1,
      price: buying ? p.cost || 0 : (offers[0]?.price ?? p.price),
    });
  }
  renderDocLines();
}
function inspectionActions(id, compact = false) {
  return button(`${icon("download")}${compact ? "" : " تنزيل عرض السعر PDF"}`, "quotation-pdf", compact ? "icon-button" : "primary", `data-id="${id}" aria-label="تنزيل عرض السعر PDF" title="تنزيل عرض السعر PDF"`)
    + (allowed("sales", true) ? button(`${icon("whatsapp")}${compact ? "" : " إرسال إلى واتساب العميل"}`, "quotation-whatsapp", compact ? "icon-button" : "secondary", `data-id="${id}" aria-label="إرسال إلى واتساب العميل" title="إرسال إلى واتساب العميل"`) : "");
}
async function shareQuotation(id, buttonElement) {
  // Open during the gesture, then detach the opener before navigating externally.
  // WhatsApp only prepares the message; the user chooses whether to send it.
  const popup = window.open("about:blank", "_blank");
  if (popup) {
    popup.opener = null;
    popup.document.title = "Serviq";
    popup.document.body.textContent = t("جارٍ تجهيز عرض السعر…");
  }
  buttonElement.disabled = true;
  try {
    const quote = await api(`documents/${id}/share?lang=${window.I18n.language}`, { method: "POST", body: {} });
    const phone = String(quote.whatsapp_phone || "").replace(/^\+/, "");
    if (!/^[1-9]\d{7,14}$/.test(phone)) throw new Error("أضف رقم واتساب صحيحًا للعميل مع كود الدولة، ثم حاول مرة أخرى.");
    const shared = new URL(quote.url, location.origin);
    if (shared.origin !== location.origin || shared.pathname !== "/api/quotations/shared" || !shared.searchParams.get("token")) throw new Error("تعذر تجهيز رابط عرض السعر");
    const message = window.I18n.language === "en"
      ? `Hello ${quote.customer_name},\nHere is your inspection quotation ${quote.number} from ${state.boot.settings.company_name}.\nTotal: ${numeric(quote.total)} ${currencyText(quote.currency)}\nDownload your PDF quotation (valid for 7 days):\n${shared.href}`
      : `أهلًا ${quote.customer_name}،\nعرض سعر المعاينة ${quote.number} من ${state.boot.settings.company_name}.\nالإجمالي: ${numeric(quote.total)} ${currencyText(quote.currency)}\nتنزيل عرض السعر PDF (الرابط صالح لمدة 7 أيام):\n${shared.href}`;
    const whatsapp = `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
    if (popup && !popup.closed) {
      popup.location.replace(whatsapp);
      toast("تم تجهيز الرسالة في واتساب. اضغط إرسال هناك لإرسالها للعميل.");
    } else {
      modal("إرسال عرض السعر عبر واتساب", `<div class="modal-body"><p>عرض السعر جاهز. افتح واتساب وراجع الرسالة، ثم اضغط إرسال.</p><a class="btn primary" href="${esc(whatsapp)}" target="_blank" rel="noopener noreferrer">فتح واتساب العميل</a><p class="muted">رابط PDF خاص بالعميل وصالح لمدة 7 أيام. شاركه مع العميل فقط.</p></div>`);
    }
  } catch (error) {
    if (popup && !popup.closed) popup.close();
    throw error;
  } finally {
    buttonElement.disabled = false;
  }
}
async function viewDocument(id) {
  const d = await api(`documents/${id}`);
  const m = state.boot.kinds[d.kind][1];
  modal(
    d.number,
    `<div class="modal-body printable" id="print-content"><div class="invoice-header"><div><h2>${esc(state.boot.settings.company_name)}</h2><p>${esc(state.boot.settings.company_address)}</p><p>الرقم الضريبي: ${esc(state.boot.settings.tax_number || "—")}</p></div><div><span class="eyebrow">${esc(t(d.kind === "inspection" ? "عرض سعر معاينة" : state.boot.kinds[d.kind][0]))}</span><h2 class="num">${esc(d.number)}</h2>${badge(d.status)}</div></div><div class="detail-grid"><div><small>التاريخ</small><b>${esc(dateLabel(d.date))}</b></div><div><small>${d.kind === "inspection" ? "العميل" : "العميل / المورد"}</small><b>${esc(d.customer || d.supplier || "—")}</b></div><div><small>المخزن</small><b>${esc(d.warehouse)}</b></div>${d.kind !== "inspection" ? `<div><small>الاستحقاق</small><b>${esc(dateLabel(d.due_date))}</b></div>` : ""}${d.kind === "inspection" ? `<div><small>مرحلة المعاينة</small><b>${esc(t(d.progress))}</b></div><div><small>موعد وموقع المعاينة</small><b>${esc(dateLabel(d.appointment_date || "—"))} — ${esc(d.location || "—")}</b></div>` : ""}${d.target_warehouse ? `<div><small>المخزن المستلم</small><b>${esc(d.target_warehouse)}</b></div>` : ""}</div>${table(d.lines, ["sku", "name", "quantity", "price", "total"])}<div class="invoice-summary detail-summary"><div><span>إجمالي الأصناف</span><b>${money(d.subtotal)}</b></div><div><span>خصم</span><b>${money(d.discount)}</b></div><div><span>الضريبة</span><b>${money(d.tax)}</b></div><div class="grand-total"><span>الإجمالي</span><b>${money(d.total)}</b></div>${d.kind !== "inspection" ? `<div><span>المدفوع / المتبقي</span><b>${money(d.paid)} / ${money(d.total - d.paid)}</b></div>` : ""}</div><p class="muted">${esc(d.note)}</p><p class="print-signatures">توقيع المستلم: __________________ &nbsp; توقيع المسؤول: __________________</p></div><footer class="modal-footer">${d.kind === "inspection" ? inspectionActions(id) : ""}${button(`${icon("print")} طباعة`, "print", d.kind === "inspection" ? "secondary" : "primary")}${d.status === "draft" && allowed(m, true) ? button("ترحيل المستند", "post-doc", "secondary", `data-id="${id}"`) : ""}${d.status === "posted" && ["inspection", "purchase_order", "sale", "purchase"].includes(d.kind) && allowed(m, true) ? button(["sale", "purchase"].includes(d.kind) ? "إنشاء مرتجع" : "تحويل إلى فاتورة", "convert-doc", "secondary", `data-id="${id}"`) : ""}${["sale", "purchase", "sale_return", "purchase_return"].includes(d.kind) && d.status === "posted" && d.paid < d.total && allowed("accounting", true) ? button("تسجيل سداد", "pay-doc", "secondary", `data-id="${id}"`) : ""}</footer>`,
    true,
  );
}
function reportsPage() {
  const groups = Object.entries(modules)
    .map(([key, m]) => [
      key,
      m,
      Object.keys(state.boot.reports).filter(
        (n) => state.boot.reports[n] === key,
      ),
    ])
    .filter((g) => g[2].length);
  return `${pageHeader("مركز التقارير", "بيانات تتحول إلى قرارات. فلترة بالتاريخ، وطباعة، وتصدير إلى Excel بصيغة CSV.")}<div class="reports-intro">${icon("chart")}<div><h2>القصة الكاملة وراء الأرقام</h2><p>تقارير مبنية على العمليات المسجلة بالفعل، وتتحدث عند فتحها.</p></div><span class="pill green">${Object.keys(state.boot.reports).length} تقرير</span></div>${groups.map(([key, m, reports]) => `<div class="section-label"><h2>${m.name}</h2></div><div class="report-grid">${reports.map((name) => `<a class="report-card" href="#/report_${name}"><span class="icon-tile ${m.color}">${icon("file")}</span><span><h3>${reportNames[name]}</h3><small>عرض التقرير وتصديره</small></span>${icon("arrow")}</a>`).join("")}</div>`).join("")}`;
}
function reportParams() {
  const form = $("#report-filter");
  return form ? formData(form) : {};
}
async function reportPage(name) {
  state.reportRows = await api(`reports/${name}`);
  return `${pageHeader(reportNames[name], "تقرير من البيانات الفعلية. استخدم الفلاتر لتحديد الفترة ونطاق العرض.", button(`${icon("download")} تصدير CSV`, "export-report", "secondary") + button(`${icon("print")} طباعة`, "print-report", "primary"))}<section class="panel"><form id="report-filter" class="report-filter"><label class="field"><span>من تاريخ</span><input type="date" name="from"></label><label class="field"><span>إلى تاريخ</span><input type="date" name="to"></label>${inputField({ key: "branch_id", label: "الفرع (كل الفروع افتراضيًا)", type: "ref", ref: "branches" })}${
    name === "sales_summary"
      ? inputField(
          {
            key: "group",
            label: "تجميع النتائج",
            type: "select",
            options: [
              { value: "day", label: "يومي" },
              { value: "month", label: "شهري" },
            ],
          },
          "day",
        )
      : ""
  }${
    name === "statement"
      ? inputField(
          {
            key: "party_type",
            label: "نوع الطرف",
            type: "select",
            options: [
              { value: "customer", label: "عميل" },
              { value: "supplier", label: "مورد" },
            ],
          },
          "customer",
        ) +
        inputField({
          key: "party_id",
          label: "الطرف",
          type: "ref",
          ref: "customers",
        })
      : ""
  }<button class="btn primary" type="submit">${icon("filter")} تطبيق</button></form><div class="report-note">${icon("info")}${name === "stock" ? "تقرير رصيد المخزون الحالي؛ فلتر التاريخ لا يغيّر الرصيد الحالي." : name === "balance_sheet" ? "أرصدة حتى تاريخ النهاية، مع نتيجة الأعمال ضمن حقوق الملكية." : name === "trial_balance" ? "حركة المدين والدائن داخل الفترة، والرصيد حتى تاريخ النهاية." : name === "statement" ? "الرصيد = المدين ناقص الدائن، ويبدأ بالرصيد السابق للفترة." : "تظهر النتائج المسجلة داخل نطاق التقرير."}</div><div id="report-content" class="printable">${renderReport(name, state.reportRows)}</div></section>`;
}
function renderReport(name, rows) {
  if (!rows.length)
    return empty(
      "لا توجد بيانات لهذا التقرير",
      "سجّل العمليات أو غيّر نطاق التاريخ.",
    );
  let summary = "";
  if (name === "income") {
    const revenue = rows
        .filter((r) => r.type === "إيرادات")
        .reduce((s, r) => s + r.value, 0),
      expense = rows
        .filter((r) => r.type === "مصروفات")
        .reduce((s, r) => s + r.value, 0);
    summary = `<div class="report-totals"><span>الإيرادات <b>${money(revenue)}</b></span><span>المصروفات <b>${money(expense)}</b></span><span>صافي الربح <b>${money(revenue - expense)}</b></span></div>`;
  } else if (name === "trial_balance") {
    const debit = rows.reduce((s, r) => s + r.debit, 0),
      credit = rows.reduce((s, r) => s + r.credit, 0);
    summary = `<div class="report-totals"><span>إجمالي المدين <b>${money(debit)}</b></span><span>إجمالي الدائن <b>${money(credit)}</b></span>${badge(Math.abs(debit - credit) < 0.01 ? "متوازن" : "غير متوازن")}</div>`;
  } else if (name === "payroll")
    summary = `<div class="report-totals"><span>صافي الرواتب <b>${money(rows.reduce((s, r) => s + r.net, 0))}</b></span><span>سجلات الرواتب <b>${rows.length}</b></span></div>`;
  else if (name === "stock")
    summary = `<div class="report-totals"><span>قيمة المخزون <b>${money(rows.reduce((s, r) => s + r.value, 0))}</b></span><span>أصناف عند حد الطلب <b>${rows.filter((r) => r.quantity <= r.min_stock).length}</b></span></div>`;
  return `${summary}${table(
    rows,
    Object.keys(rows[0]).filter((k) => k !== "id"),
  )}`;
}
async function specialPage(page) {
  state.rows = await api(page);
  const config = {
    payments: {
      desc: "سندات القبض والصرف والسداد النقدي والبنكي مرتبطة بقيود الحسابات.",
      cols: ["date", "direction", "party", "document", "method", "amount"],
      action: "new-payment",
      module: "accounting",
    },
    journal: {
      desc: "كل العمليات تترك أثرًا محاسبيًا. القيود المرحلة محفوظة للمراجعة.",
      cols: ["id", "date", "description", "source_type", "total"],
      action: "new-journal",
      module: "accounting",
    },
    payroll: {
      desc: "احتساب الرواتب والبدلات والإضافي والخصومات والسلف مع الترحيل للحسابات.",
      cols: ["month", "branch", "employees", "status", "total"],
      action: "new-payroll",
      module: "hr",
    },
    loans: {
      desc: "صرف سلفة للموظف وخصم الأقساط تلقائيًا من مسير الرواتب.",
      cols: ["employee", "date", "amount", "installment", "balance", "note"],
      action: "new-loan",
      module: "hr",
    },
    users: {
      desc: "حسابات مستقلة وصلاحيات وصول حسب القسم.",
      cols: ["name", "username", "role", "active"],
      action: "new-user",
      module: "admin",
    },
    audit: {
      desc: "سجل العمليات والتعديلات وتسجيل الدخول. أحدث 1000 إجراء.",
      cols: ["created_at", "user", "action", "entity", "entity_id", "detail"],
      module: "admin",
    },
  }[page];
  return `${pageHeader(title(page), config.desc, config.action && allowed(config.module, true) ? button(`${icon("plus")} ${page === "payroll" ? "مسير جديد" : page === "journal" ? "قيد جديد" : "إضافة"}`, config.action, "primary") : "")}<section class="panel">${tableTools(state.rows.length)}${state.rows.length ? table(state.rows, config.cols, page === "journal" ? (r) => button(icon("eye"), "view-journal", "icon-button", `data-id="${r.id}" aria-label="عرض القيد"`) : page === "users" ? (r) => button(icon("edit"), "edit-user", "icon-button", `data-id="${r.id}" aria-label="تعديل الصلاحيات"`) : page === "payroll" ? () => '<a class="text-link" href="#/report_payroll">كشف الرواتب</a>' : null) : empty()}</section>`;
}
async function paymentModal(doc = null) {
  let docs = [];
  if (!doc)
    docs = (await api("documents")).filter(
      (d) =>
        d.status === "posted" &&
        ["sale", "purchase", "sale_return", "purchase_return"].includes(
          d.kind,
        ) &&
        d.total > d.paid,
    );
  const direction = doc
    ? ["sale", "purchase_return"].includes(doc.kind)
      ? "in"
      : "out"
    : "in";
  modal(
    "سند قبض / صرف",
    `<form id="payment-form"><div class="modal-body"><div class="inline-note compact">${icon("info")} ربط السند بالفاتورة يحدّث المدفوع والمتبقي. السند المستقل للطرف يسوّي رصيده فقط.</div><div class="form-grid">${inputField({ key: "date", label: "التاريخ", type: "date", required: true }, dateNow())}${inputField(
      {
        key: "direction",
        label: "نوع السند",
        type: "select",
        required: true,
        options: [
          { value: "in", label: "قبض" },
          { value: "out", label: "صرف" },
        ],
      },
      direction,
    )}${inputField({ key: "document_id", label: "الفاتورة (اختياري)", type: "select", translateOptions: false, options: (doc ? [doc] : docs).map((d) => ({ value: d.id, label: `${d.number} — ${t("متبقي")} ${numeric(d.total - d.paid)}` })) }, doc?.id)}${inputField({ key: "amount", label: "المبلغ", type: "money", required: true }, doc ? doc.total - doc.paid : "")}${inputField(
      {
        key: "method",
        label: "وسيلة الدفع",
        type: "select",
        required: true,
        options: [
          { value: "cash", label: "نقدي" },
          { value: "bank", label: "تحويل بنكي" },
          { value: "card", label: "بطاقة — تسجيل سداد" },
        ],
      },
      "cash",
    )}${inputField({ key: "customer_id", label: "عميل بدون فاتورة", type: "ref", ref: "customers" })}${inputField({ key: "supplier_id", label: "مورد بدون فاتورة", type: "ref", ref: "suppliers" })}${inputField({ key: "account_id", label: "حساب المصروف أو الإيراد (للسند العام)", type: "ref", ref: "accounts" })}${inputField({ key: "note", label: "ملاحظات", type: "textarea" })}</div><div class="form-error"></div></div>${modalFooter("حفظ السند وترحيل القيد")}</form>`,
  );
}
function journalModal() {
  modal(
    "قيد يومية يدوي",
    `<form id="journal-form"><div class="modal-body"><div class="form-grid">${inputField({ key: "date", label: "التاريخ", type: "date", required: true }, dateNow())}${inputField({ key: "description", label: "البيان", required: true })}</div><div id="journal-lines">${journalLine()}${journalLine()}</div>${button(`${icon("plus")} سطر جديد`, "add-journal-line", "secondary")}<p class="muted">كل سطر مدين أو دائن. يجب تساوي الإجماليين قبل الحفظ.</p><div class="form-error"></div></div>${modalFooter("حفظ وترحيل القيد")}</form>`,
    true,
  );
}
function journalLine() {
  return `<div class="journal-line">${inputField({ key: "account_id", label: "الحساب", type: "ref", required: true, ref: "accounts" })}${inputField({ key: "debit", label: "مدين", type: "money" }, 0)}${inputField({ key: "credit", label: "دائن", type: "money" }, 0)}${inputField({ key: "customer_id", label: "العميل (عند استخدام حساب العملاء)", type: "ref", ref: "customers" })}${inputField({ key: "supplier_id", label: "المورد (عند استخدام حساب الموردين)", type: "ref", ref: "suppliers" })}${button(icon("trash"), "remove-journal-line", "icon-button danger-text", 'aria-label="حذف سطر القيد"')}</div>`;
}
function simpleModal(kind) {
  const configs = {
    payroll: {
      name: "إنشاء مسير الرواتب",
      note: "يرحّل المسير استحقاق الرواتب للحسابات مرة واحدة لكل موظف وشهر. الغياب يخصم من الأساسي على أساس 30 يومًا، ويُخصم القسط المتاح من السلف. دفع الرواتب يتم بسند صرف على حساب الرواتب المستحقة.",
      fields: [
        { key: "month", label: "شهر الرواتب", type: "month", required: true },
        {
          key: "branch_id",
          label: "الفرع (الكل إذا تركته فارغًا)",
          type: "ref",
          ref: "branches",
        },
        { key: "bonus", label: "مكافأة إضافية لكل موظف", type: "money" },
      ],
    },
    loans: {
      name: "صرف سلفة موظف",
      note: "تُسجّل السلفة مقابل الصندوق، وتُحصّل الأقساط عند ترحيل الرواتب.",
      fields: [
        {
          key: "employee_id",
          label: "الموظف",
          type: "ref",
          ref: "employees",
          required: true,
        },
        { key: "date", label: "تاريخ الصرف", type: "date", required: true },
        { key: "amount", label: "مبلغ السلفة", type: "money", required: true },
        {
          key: "installment",
          label: "القسط الشهري",
          type: "money",
          required: true,
        },
        { key: "note", label: "ملاحظات" },
      ],
    },
    depreciate: {
      name: "احتساب إهلاك الأصول",
      note: "إهلاك شهري بالقسط الثابت: (التكلفة − القيمة التخريدية) ÷ العمر بالشهور، مع منع التكرار لنفس الشهر.",
      fields: [{ key: "month", label: "الشهر", type: "month", required: true }],
    },
  };
  const c = configs[kind];
  modal(
    c.name,
    `<form id="simple-form" data-endpoint="${kind}"><div class="modal-body"><div class="inline-note compact">${icon("info")}${c.note}</div><div class="form-grid">${c.fields.map((f) => inputField(f, f.type === "month" ? dateNow().slice(0, 7) : f.type === "date" ? dateNow() : undefined)).join("")}</div><div class="form-error"></div></div>${modalFooter("حفظ وترحيل")}</form>`,
  );
}
function userModal(id) {
  const user = state.rows.find((u) => u.id === id);
  modal(
    id ? "تعديل صلاحيات المستخدم" : "مستخدم جديد",
    `<form id="user-form" data-id="${id || ""}"><div class="modal-body"><div class="form-grid">${!id ? inputField({ key: "name", label: "الاسم", required: true }) + inputField({ key: "username", label: "اسم الدخول", required: true }) : `<p>${esc(user.name)} — ${esc(user.username)}</p>`}${inputField({ key: "role", label: "صلاحيات القسم", type: "select", required: true, options: Object.entries(state.boot.roles).map(([value, label]) => ({ value, label })) }, user?.role || "sales")}${inputField({ key: "password", label: id ? "كلمة مرور جديدة (اختياري)" : "كلمة المرور", type: "password", required: !id })}${
      id
        ? inputField(
            {
              key: "active",
              label: "حالة الحساب",
              type: "select",
              required: true,
              options: [
                { value: 1, label: "نشط" },
                { value: 0, label: "موقوف" },
              ],
            },
            user.active,
          )
        : ""
    }</div><div class="form-error"></div></div>${modalFooter()}</form>`,
  );
}
function settingsPage() {
  const s = state.boot.settings;
  return `${pageHeader("إعدادات مساحة العمل", "بيانات الشركة وسياسات المبيعات والعمل والصلاحيات.")}<div class="settings-layout"><section class="panel settings-panel"><header class="panel-header"><div><h2>بيانات الشركة والتفضيلات</h2><p>تظهر بيانات شركتك على الفواتير المطبوعة</p></div>${icon("building")}</header><form id="settings-form"><div class="form-grid">${[
    { key: "company_name", label: "اسم الشركة", required: true },
    { key: "company_address", label: "عنوان الشركة" },
    { key: "company_phone", label: "هاتف الشركة" },
    { key: "tax_number", label: "الرقم الضريبي" },
    { key: "tax_rate", label: "الضريبة الافتراضية %", type: "number" },
    { key: "discount_limit", label: "أقصى خصم مسموح %", type: "number" },
    { key: "leave_days", label: "رصيد إجازة الموظف الجديد", type: "number" },
    {
      key: "work_hours",
      label: "ساعات العمل اليومية (إرشادي)",
      type: "number",
    },
  ]
    .map((f) => inputField(f, s[f.key]) + (f.key === "company_name" ? currencyField() : ""))
    .join(
      "",
    )}</div><div class="form-error"></div><button class="btn primary" type="submit">${icon("check")} حفظ الإعدادات</button></form></section><aside><section class="panel settings-links"><h3>التحكم والوصول</h3><a href="#/users">${icon("users")} المستخدمون والصلاحيات ${icon("arrow")}</a><a href="#/audit">${icon("shield")} سجل النشاط ${icon("arrow")}</a><button data-action="profile">${icon("settings")} تغيير كلمة المرور ${icon("arrow")}</button></section><section class="panel backup-card"><span class="icon-tile green">${icon("download")}</span><h3>نسخة من بياناتك، دائمًا</h3><p>نزّل نسخة متسقة من قاعدة البيانات، واحتفظ بها في مكان آمن. تحتوي النسخة على كل بيانات الشركة.</p>${button(`${icon("download")} تنزيل نسخة احتياطية`, "backup", "secondary block")}<small>${state.boot.serverless ? "على Vercel: تنزيل يدوي للنسخ الصغيرة. استخدم نسخ وتصدير Turso للبيانات الكبيرة؛ عامل النسخ المحلي لا يعمل على هذه الاستضافة." : "نسخ تلقائي كل 24 ساعة أثناء تشغيل الخادم، مع الاحتفاظ بآخر 14 نسخة تلقائية. احفظ نسخة خارج هذه البيئة."}</small></section></aside></div>`;
}
async function posPage() {
  state.catalog = await api("catalog");
  return `${pageHeader("نقطة البيع", "بيع سريع بالباركود، مع تسجيل السداد وتحديث المخزون والحسابات.", button(`${icon("cart")} بدء عملية بيع`, "new-doc", "primary", 'data-kind="sale"'))}<section class="inline-note">${icon("info")} اضغط على أي صنف لبدء فاتورة، أو استخدم قارئ الباركود داخل الفاتورة. البطاقة والتحويل طرق لتسجيل سداد تم خارج النظام.</section><section class="pos-grid">${state.catalog.products.map((p) => `<button class="pos-product" data-action="pos-product" data-id="${p.id}" data-search="${esc(p.name + " " + p.sku + " " + p.barcode)}"><div class="product-illustration">${icon("box")}</div><small>${esc(p.sku)}</small><h3>${esc(p.name)}</h3><b>${money(p.price)}</b><span class="round-plus">${icon("plus")}</span></button>`).join("") || empty("أضف أصنافك أولًا", "تظهر هنا المنتجات المسجلة في المخزون.")}</section>`;
}
function filterTable(query) {
  const q = query.toLocaleLowerCase(window.I18n.language);
  $$("[data-search]").forEach((row) => {
    const text = (row.dataset.search + " " + row.textContent).toLocaleLowerCase(
      window.I18n.language,
    );
    const status = $("#status-filter")?.value;
    const match =
      (!q || text.includes(q)) &&
      (!status ||
        state.rows.find(
          (r) =>
            String(r.number) &&
            row.dataset.search.includes(String(r.number).toLowerCase()),
        )?.status === status);
    row.classList.toggle("hidden", !match);
  });
  const no = $(".no-search-results");
  if (no) no.classList.toggle("hidden", $$("tbody tr:not(.hidden)").length > 0);
}
function confirmAction(titleText, message, action) {
  modal(
    titleText,
    `<div class="modal-body"><p class="confirm-message">${esc(t(message))}</p></div><footer class="modal-footer">${button("تأكيد", "confirmed", "primary")}${button("إلغاء", "close", "secondary")}</footer>`,
  );
  state.confirm = action;
}
async function download(path) {
  const response = await fetch(`/api/${path}`, {
    headers: { "X-ERP-Request": "1", "Accept-Language": window.I18n.language },
  });
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {}
    const error = new Error(data?.error || t("تعذر تنزيل الملف"));
    error.localized = Boolean(data?.error);
    throw error;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  const disposition = response.headers.get("Content-Disposition") || "";
  link.download =
    disposition.match(/filename="([^"]+)"/)?.[1] ||
    decodeURIComponent(
      disposition.match(/filename\*=UTF-8''(.+)/)?.[1] || "export.csv",
    );
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function printContent(selector, titleText) {
  const source = $(selector);
  if (!source) return;
  let print = $("#print-area");
  if (!print) {
    print = document.createElement("section");
    print.id = "print-area";
    document.body.append(print);
  }
  print.lang = window.I18n.language;
  print.dir = window.I18n.language === "ar" ? "rtl" : "ltr";
  setHTML(print, `<header class="print-report-header"><h1>${esc(state.boot.settings.company_name)}</h1><h2>${esc(t(titleText))}</h2><p>${esc(dateLabel(dateNow()))}</p></header>`);
  // Clone already-rendered rows: translating serialized DOM would translate customer names.
  for (const child of source.childNodes) print.append(child.cloneNode(true));
  window.print();
  print.replaceChildren();
}
const code39Patterns = [
  "nnnwwnwnn",
  "wnnwnnnnw",
  "nnwwnnnnw",
  "wnwwnnnnn",
  "nnnwwnnnw",
  "wnnwwnnnn",
  "nnwwwnnnn",
  "nnnwnnwnw",
  "wnnwnnwnn",
  "nnwwnnwnn",
  "wnnnnwnnw",
  "nnwnnwnnw",
  "wnwnnwnnn",
  "nnnnwwnnw",
  "wnnnwwnnn",
  "nnwnwwnnn",
  "nnnnnwwnw",
  "wnnnnwwnn",
  "nnwnnwwnn",
  "nnnnwwwnn",
  "wnnnnnnww",
  "nnwnnnnww",
  "wnwnnnnwn",
  "nnnnwnnww",
  "wnnnwnnwn",
  "nnwnwnnwn",
  "nnnnnnwww",
  "wnnnnnwwn",
  "nnwnnnwwn",
  "nnnnwnwwn",
  "wwnnnnnnw",
  "nwwnnnnnw",
  "wwwnnnnnn",
  "nwnnwnnnw",
  "wwnnwnnnn",
  "nwwnwnnnn",
  "nwnnnnwnw",
  "wwnnnnwnn",
  "nwwnnnwnn",
  "nwnwnwnnn",
  "nwnwnnnwn",
  "nwnnnwnwn",
  "nnnwnwnwn",
  "nwnnwnwnn",
];
function barcodeSvg(text) {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%*",
    value = `*${text.toUpperCase()}*`;
  if ([...value].some((c) => !alphabet.includes(c)))
    return "<p>الباركود يدعم الحروف الإنجليزية والأرقام وعلامات Code 39 فقط.</p>";
  let x = 16,
    rects = "";
  for (const ch of value) {
    const pattern = code39Patterns[alphabet.indexOf(ch)];
    [...pattern].forEach((v, i) => {
      const w = v === "w" ? 5 : 2;
      if (i % 2 === 0)
        rects += `<rect x="${x}" y="8" width="${w}" height="70"/>`;
      x += w;
    });
    x += 2;
  }
  return `<svg class="barcode-svg" viewBox="0 0 ${x + 16} 104" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${esc(text)}">${rects}<text x="${(x + 16) / 2}" y="98" text-anchor="middle" font-family="monospace" font-size="12">${esc(text)}</text></svg>`;
}

async function employeeFilesModal(id) {
  const files = await api(`employees/${id}/files`);
  modal(
    "ملف الموظف والعقود",
    `<div class="modal-body"><p class="muted">صور المستندات والعقود والملفات الشخصية، محفوظة ضمن النسخة الاحتياطية.</p>${files.length ? table(files, ["name", "size", "created_at"], (r) => button(icon("download"), "download-file", "icon-button", `data-id="${r.id}" aria-label="تنزيل الملف"`) + (allowed("hr", true) ? button(icon("trash"), "delete-file", "icon-button danger-text", `data-id="${r.id}" aria-label="حذف الملف"`) : "")) : empty("لا توجد مرفقات بعد", "أضف عقد العمل أو مستند الموظف.")}${allowed("hr", true) ? `<form id="file-form" data-id="${id}"><label class="field"><span>ملف PDF أو صورة PNG / JPEG — حتى 2 ميجابايت</span><input type="file" name="upload" accept="application/pdf,image/png,image/jpeg" required></label><div class="form-error"></div><button class="btn primary" type="submit">${icon("plus")} حفظ المرفق</button></form>` : ""}</div>`,
  );
}

document.addEventListener("click", async (event) => {
  const link = event.target.closest('a[href^="#/"]');
  if (link) document.body.classList.remove("menu-open");
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action,
    id = Number(el.dataset.id),
    resource = el.dataset.resource;
  try {
    if (action === "language") {
      const form = $("#auth-form");
      const authValues = form ? formData(form) : null;
      const hasEdits = !form && ($("#modal-root form") || $("#settings-form[data-dirty=true], #currency-form[data-dirty=true]"));
      if (hasEdits && !window.confirm(t("سيتم إغلاق النموذج وفقد التعديلات غير المحفوظة. هل تريد تغيير اللغة؟"))) return;
      window.I18n.setLanguage(window.I18n.language === "ar" ? "en" : "ar");
      closeModal();
      if (state.boot) return await renderPage();
      renderAuth(state.auth?.setup || false, state.auth?.setupTokenRequired || false);
      for (const [key, value] of Object.entries(authValues || {})) {
        const field = $("#auth-form").elements.namedItem(key);
        if (field) field.value = value;
      }
      return;
    }
    if (action === "close") return closeModal();
    if (action === "menu") return document.body.classList.toggle("menu-open");
    if (action === "new-resource") return resourceModal(resource);
    if (action === "edit-resource") return resourceModal(resource, id);
    if (action === "view-resource") {
      const r = state.rows.find((r) => r.id === id),
        spec = state.boot.resources[resource];
      return modal(
        spec.label,
        `<div class="modal-body"><div class="detail-grid">${spec.fields.map((f) => `<div><small>${esc(t(f.label))}</small><b>${display(r[f.key], f.key, spec, r)}</b></div>`).join("")}</div></div>`,
      );
    }
    if (action === "delete-resource")
      return confirmAction(
        "حذف السجل",
        "سيُحذف السجل إذا لم يكن مرتبطًا بعمليات. هل تريد المتابعة؟",
        async () => {
          await api(`resources/${resource}/${id}`, { method: "DELETE" });
          await refreshBoot();
          await renderPage();
          toast("تم حذف السجل");
        },
      );
    if (action === "new-doc") return await documentModal(el.dataset.kind);
    if (action === "add-line") {
      addLine($("#line-product").value);
      $("#line-product").value = "";
      return;
    }
    if (action === "remove-line") {
      state.documentLines.splice(Number(el.dataset.index), 1);
      return renderDocLines();
    }
    if (action === "quotation-pdf") return await download(`documents/${id}/pdf?lang=${window.I18n.language}`);
    if (action === "quotation-whatsapp") return await shareQuotation(id, el);
    if (action === "view-doc") return await viewDocument(id);
    if (action === "post-doc")
      return confirmAction(
        "ترحيل المستند",
        "سيتم تحديث الأرصدة والحسابات. لن يمكن حذف المستند بعد الترحيل.",
        async () => {
          await api(`documents/${id}/post`, { method: "POST", body: {} });
          await renderPage();
          toast("تم ترحيل المستند");
        },
      );
    if (action === "delete-doc")
      return confirmAction(
        "حذف المسودة",
        "هل تريد حذف هذه المسودة؟",
        async () => {
          await api(`documents/${id}`, { method: "DELETE" });
          await renderPage();
          toast("تم حذف المسودة");
        },
      );
    if (action === "convert-doc") {
      const d = await api(`documents/${id}`),
        kind = {
          inspection: "sale",
          purchase_order: "purchase",
          sale: "sale_return",
          purchase: "purchase_return",
        }[d.kind];
      if (!canPage(`doc_${kind}`))
        throw new Error("لا توجد صلاحية لنوع المستند الناتج");
      return await documentModal(kind, d);
    }
    if (action === "pay-doc")
      return await paymentModal(await api(`documents/${id}`));
    if (action === "new-payment") return await paymentModal();
    if (action === "new-journal") return journalModal();
    if (action === "add-journal-line")
      return $("#journal-lines").insertAdjacentHTML("beforeend", window.I18n.html(journalLine()));
    if (action === "remove-journal-line")
      return el.closest(".journal-line").remove();
    if (action === "view-journal") {
      const d = await api(`journal/${id}`);
      return modal(
        `قيد #${id}`,
        `<div class="modal-body printable" id="print-content"><h3>${esc(journalDescription(d.journal))}</h3><p>${esc(d.journal.date)}</p>${table(d.lines, ["code", "name", "party", "debit", "credit"])}</div><footer class="modal-footer">${d.kind === "inspection" ? inspectionActions(id) : ""}${button(`${icon("print")} طباعة`, "print", d.kind === "inspection" ? "secondary" : "primary")}</footer>`,
        true,
      );
    }
    if (action === "new-payroll") return simpleModal("payroll");
    if (action === "new-loan") return simpleModal("loans");
    if (action === "depreciate") return simpleModal("depreciate");
    if (action === "new-user") return userModal();
    if (action === "edit-user") return userModal(id);
    if (action === "export-report")
      return await download(
        `reports/${state.page.slice(7)}?${new URLSearchParams({ ...reportParams(), format: "csv", lang: window.I18n.language })}`,
      );
    if (action === "print-report")
      return printContent("#report-content", title(state.page));
    if (action === "print")
      return printContent("#print-content", $("#modal-title").textContent);
    if (action === "backup") {
      await download("backup");
      return toast("تم تنزيل النسخة الاحتياطية");
    }
    if (action === "confirmed") {
      el.disabled = true;
      const fn = state.confirm;
      await fn();
      closeModal();
      return;
    }
    if (action === "demo")
      return confirmAction(
        "تحميل بيانات تجريبية",
        "ستُضاف بيانات تجريبية فعلية لقاعدة البيانات الحالية. استخدمها للاستكشاف، وقاعدة بيانات جديدة عند بدء أعمالك الحقيقية.",
        async () => {
          await api("demo", { method: "POST", body: {} });
          await refreshBoot();
          await renderPage();
          toast("أُضيفت البيانات التجريبية بنجاح");
        },
      );
    if (action === "profile")
      return modal(
        "حسابي",
        `<div class="modal-body"><div class="profile-info"><span class="avatar">${esc(state.boot.user.name[0])}</span><div><h3>${esc(state.boot.user.name)}</h3><p>${esc(t(state.boot.roles[state.boot.user.role]))}</p></div></div><form id="password-form"><div class="form-grid one">${inputField({ key: "current", label: "كلمة المرور الحالية", type: "password", required: true })}${inputField({ key: "password", label: "كلمة المرور الجديدة", type: "password", required: true })}</div><div class="form-error"></div><button class="btn secondary block" type="submit">تغيير كلمة المرور</button></form></div><footer class="modal-footer">${button(`${icon("logout")} تسجيل الخروج`, "logout", "danger")}</footer>`,
      );
    if (action === "logout") {
      await api("logout", { method: "POST", body: {} });
      closeModal();
      state.boot = null;
      return renderAuth(false);
    }
    if (action === "notifications") {
      const d = await api("dashboard");
      return modal(
        "تنبيهات مساحة العمل",
        `<div class="modal-body"><div class="notification-list">${d.low_stock?.map((p) => `<a href="#/report_stock" data-action="close">${icon("box")}<span>رصيد ${esc(p.name)}: <b>${numeric(p.quantity)}</b> / حد الطلب ${numeric(p.min_stock)}</span></a>`).join("") || ""}${d.expiring?.map((p) => `<a href="#/products" data-action="close">${icon("clock")}<span>${esc(p.name)} — الصلاحية ${esc(p.expiry_date)}</span></a>`).join("") || ""}${d.pending_leaves ? `<a href="#/leaves" data-action="close">${icon("users")} ${d.pending_leaves} طلبات إجازة للمراجعة</a>` : ""}${!d.low_stock?.length && !d.expiring?.length && !d.pending_leaves ? empty("كل شيء هادئ", "لا توجد تنبيهات حاليًا.") : ""}</div></div>`,
      );
    }
    if (action === "pos-product") {
      await documentModal("sale");
      addLine(id);
      return;
    }
    if (action === "employee-files") return await employeeFilesModal(id);
    if (action === "download-file") return await download(`files/${id}`);
    if (action === "delete-file")
      return confirmAction(
        "حذف الملف",
        "هل تريد حذف هذا الملف من ملف الموظف؟",
        async () => {
          await api(`files/${id}`, { method: "DELETE" });
          toast("تم حذف الملف");
        },
      );
    if (action === "qr") {
      const data = await api(`products/${id}/qr`);
      return modal(
        "رمز QR للصنف",
        `<div class="modal-body"><div id="print-content" class="barcode-label"><img class="qr-image" src="data:image/svg+xml,${encodeURIComponent(data.svg)}" alt="رمز QR للصنف"><p>امسح الرمز لقراءة باركود الصنف</p></div></div><footer class="modal-footer">${button("طباعة", "print", "primary")}</footer>`,
      );
    }
    if (action === "inspection-progress") {
      const d = await api(`documents/${id}`);
      return modal(
        "متابعة المعاينة",
        `<form id="progress-form" data-id="${id}"><div class="modal-body"><p class="muted">${esc(d.number)} — ${esc(d.customer)}</p>${inputField({ key: "progress", label: "مرحلة المتابعة", type: "select", required: true, options: ["جديدة", "مجدولة", "تمت المعاينة", "عرض مرسل", "مقبولة", "مرفوضة"] }, d.progress)}<div class="form-error"></div></div>${modalFooter()}</form>`,
      );
    }
    if (action === "barcode") {
      const p = state.rows.find((p) => p.id === id);
      return modal(
        "ملصق الصنف",
        `<div class="modal-body"><div id="print-content" class="barcode-label printable"><h3>${esc(p.name)}</h3>${barcodeSvg(p.barcode || p.sku)}<p>${money(p.price)}</p><small>Code 39</small></div></div><footer class="modal-footer">${button(`${icon("print")} طباعة الملصق`, "print", "primary")}${button("رمز QR", "qr", "secondary", `data-id="${id}"`)}</footer>`,
      );
    }
  } catch (error) {
    toast(errorText(error), true);
    el.disabled = false;
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!form.id) return;
  event.preventDefault();
  const buttons = $$("button[type=submit]", form);
  buttons.forEach((b) => (b.disabled = true));
  const err = $(".form-error", form);
  if (err) err.textContent = "";
  try {
    const data = formData(form);
    if (form.id === "auth-form") {
      await api(form.dataset.setup === "true" ? "setup" : "login", {
        method: "POST",
        body: data,
      });
      await refreshBoot();
      return await renderPage();
    }
    if (form.id === "resource-form") {
      await api(
        `resources/${form.dataset.resource}${form.dataset.id ? "/" + form.dataset.id : ""}`,
        { method: form.dataset.id ? "PUT" : "POST", body: data },
      );
      await refreshBoot();
    } else if (form.id === "document-form") {
      if (
        ["sale_return", "purchase_return"].includes(state.docKind) &&
        !state.source
      )
        throw new Error("اختر الفاتورة الأصلية أولًا");
      await api("documents", {
        method: "POST",
        body: {
          ...data,
          kind: state.docKind,
          lines: state.documentLines,
          source_id: state.source?.id,
          post: event.submitter?.value !== "draft",
        },
      });
    } else if (form.id === "payment-form")
      await api("payments", { method: "POST", body: data });
    else if (form.id === "journal-form") {
      data.lines = $$(".journal-line", form).map((line) =>
        Object.fromEntries(
          $$("input,select", line).map((i) => [i.name, i.value]),
        ),
      );
      await api("journal", { method: "POST", body: data });
    } else if (form.id === "progress-form")
      await api(`documents/${form.dataset.id}/progress`, {
        method: "PUT",
        body: data,
      });
    else if (form.id === "file-form") {
      const file = $("[name=upload]", form).files[0];
      if (!file) throw new Error("اختر الملف");
      if (file.size > 2 * 1024 * 1024)
        throw new Error("الحد الأقصى 2 ميجابايت");
      const encoded = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("تعذّر قراءة الملف"));
        reader.readAsDataURL(file);
      });
      await api(`employees/${form.dataset.id}/files`, {
        method: "POST",
        body: { name: file.name, content: encoded },
      });
      await employeeFilesModal(Number(form.dataset.id));
      toast("تم حفظ الملف");
      return;
    } else if (form.id === "simple-form")
      await api(form.dataset.endpoint, { method: "POST", body: data });
    else if (form.id === "user-form") {
      if (form.dataset.id) data.active = data.active === "1";
      await api(`users${form.dataset.id ? "/" + form.dataset.id : ""}`, {
        method: form.dataset.id ? "PUT" : "POST",
        body: data,
      });
    } else if (form.id === "currency-form") {
      await api("settings", { method: "PUT", body: { currency: data.currency } });
      await refreshBoot();
      await renderPage();
      toast("تم حفظ العملة الأساسية");
      return;
    } else if (form.id === "settings-form") {
      await api("settings", { method: "PUT", body: data });
      await refreshBoot();
      delete form.dataset.dirty;
      await renderPage();
      toast("تم حفظ إعدادات الشركة");
      return;
    } else if (form.id === "password-form") {
      await api("password", { method: "POST", body: data });
      closeModal();
      toast("تم تغيير كلمة المرور");
      return;
    } else if (form.id === "report-filter") {
      state.reportRows = await api(
        `reports/${state.page.slice(7)}?${new URLSearchParams(data)}`,
      );
      setHTML($("#report-content"), renderReport(
        state.page.slice(7),
        state.reportRows,
      ));
      return;
    } else return;
    closeModal();
    await renderPage();
    toast("تم الحفظ بنجاح");
  } catch (error) {
    if (err) err.textContent = errorText(error);
    else toast(errorText(error), true);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
});
document.addEventListener("input", (event) => {
  const el = event.target;
  if (el.closest("#settings-form, #currency-form")) el.closest("form").dataset.dirty = "true";
  if (["table-search", "global-search"].includes(el.id)) {
    state.search = el.value;
    filterTable(el.value);
  }
  if (el.dataset.line !== undefined) {
    const index = Number(el.dataset.line);
    state.documentLines[index][el.dataset.field] = Number(el.value);
    const l = state.documentLines[index];
    setHTML($(`.line-total[data-index="${index}"]`), money(
      l.quantity * l.price,
    ));
    updateDocSummary();
  }
  if (["discount", "tax_rate", "paid"].includes(el.name)) updateDocSummary();
});
document.addEventListener("change", async (event) => {
  const el = event.target;
  try {
    if (el.id === "status-filter") filterTable(state.search);
    if (el.name === "warehouse_id") renderDocLines();
    if (el.name === "original_document" && el.value) {
      const d = await api(`documents/${el.value}`);
      await documentModal(state.docKind, d);
    }
    if (el.name === "party_type") {
      const sel = $("[name=party_id]");
      setHTML(sel, '<option value="">اختر الطرف</option>' +
        state.boot.refs[el.value === "customer" ? "customers" : "suppliers"]
          .map((o) => `<option value="${o.id}">${esc(o.name)}</option>`)
          .join(""));
    }
  } catch (error) {
    toast(errorText(error), true);
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModal();
    document.body.classList.remove("menu-open");
  }
  if (
    event.key === "/" &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)
  ) {
    event.preventDefault();
    $("#global-search")?.focus();
  }
  if (event.key === "Enter" && event.target.id === "barcode-input") {
    event.preventDefault();
    const p = state.catalog.products.find(
      (p) =>
        p.barcode === event.target.value.trim() ||
        p.sku === event.target.value.trim(),
    );
    if (p) addLine(p.id);
    else toast(t("لم يتم العثور على هذا الباركود"), true);
    event.target.value = "";
  }
  if (event.key === "Tab" && $(".modal")) {
    const elements = $$(
      "button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled)",
      $(".modal"),
    ).filter((e) => e.offsetParent !== null);
    const first = elements[0],
      last = elements.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
});
window.addEventListener("hashchange", () => {
  closeModal();
  renderPage();
});
async function start() {
  try {
    await window.I18n.ready;
    const auth = await api("auth");
    if (auth.user) {
      await refreshBoot();
      await renderPage();
    } else renderAuth(auth.setup_required, auth.setup_token_required);
  } catch (error) {
    setHTML($("#app"), empty("تعذّر الاتصال بالخادم", errorText(error), true));
  }
}
start();
