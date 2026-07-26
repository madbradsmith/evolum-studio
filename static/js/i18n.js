/* ============================================================
   EVOLUM — i18n engine + language switcher
   Top 10 worldwide languages. Auto-detect + manual override.
   Translates the INTERFACE. Project loglines come translated
   from the server (per-language) — see projects.js logline_i18n.
   ============================================================ */
(function () {
  const LANGS = [
    { c: 'en', n: 'English',    native: 'English',  d: 'ltr' },
    { c: 'es', n: 'Spanish',    native: 'Español',  d: 'ltr' },
    { c: 'zh', n: 'Chinese',    native: '中文',      d: 'ltr' },
    { c: 'hi', n: 'Hindi',      native: 'हिन्दी',    d: 'ltr' },
    { c: 'ar', n: 'Arabic',     native: 'العربية',   d: 'rtl' },
    { c: 'pt', n: 'Portuguese', native: 'Português', d: 'ltr' },
    { c: 'fr', n: 'French',     native: 'Français',  d: 'ltr' },
    { c: 'ja', n: 'Japanese',   native: '日本語',     d: 'ltr' },
    { c: 'de', n: 'German',     native: 'Deutsch',   d: 'ltr' },
    { c: 'ru', n: 'Russian',    native: 'Русский',   d: 'ltr' },
  ];
  const CODES = LANGS.map(l => l.c);

  // ── translation dictionary: key → { lang: string } ──
  // Strings may contain <em> for accent words (applied via data-i18n-html).
  const T = window.EVOLUM_I18N_STRINGS || {};

  function detect() {
    const saved = localStorage.getItem('evolum_lang');
    if (saved && CODES.includes(saved)) return saved;
    const navs = navigator.languages || [navigator.language || 'en'];
    for (const l of navs) {
      const base = (l || '').toLowerCase().split('-')[0];
      if (CODES.includes(base)) return base;
    }
    return 'en';
  }

  let lang = detect();

  function t(key) {
    const e = T[key];
    if (!e) return null;
    return (e[lang] != null ? e[lang] : e.en);
  }

  function apply(root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(el => {
      const v = t(el.getAttribute('data-i18n'));
      if (v != null) el.textContent = v;
    });
    root.querySelectorAll('[data-i18n-html]').forEach(el => {
      const v = t(el.getAttribute('data-i18n-html'));
      if (v != null) el.innerHTML = v;
    });
    root.querySelectorAll('[data-i18n-ph]').forEach(el => {
      const v = t(el.getAttribute('data-i18n-ph'));
      if (v != null) el.setAttribute('placeholder', v);
    });
  }

  function setDir() {
    const meta = LANGS.find(l => l.c === lang) || LANGS[0];
    document.documentElement.lang = lang;
    document.documentElement.dir = meta.d;
    document.documentElement.classList.toggle('rtl', meta.d === 'rtl');
  }

  function setLang(code) {
    if (!CODES.includes(code)) return;
    lang = code;
    localStorage.setItem('evolum_lang', code);
    setDir();
    apply(document);
    buildSwitchers();
    window.dispatchEvent(new CustomEvent('evolum:langchange', { detail: { lang } }));
  }

  // ── switcher UI ──
  function buildSwitchers() {
    document.querySelectorAll('[data-lang-mount]').forEach(mount => {
      const cur = LANGS.find(l => l.c === lang) || LANGS[0];
      mount.innerHTML =
        '<button class="lang-btn" aria-haspopup="true" aria-expanded="false">' +
          '<svg class="lang-globe" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">' +
            '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18"/></svg>' +
          '<span class="lang-cur">' + cur.native + '</span>' +
          '<span class="lang-caret">▾</span>' +
        '</button>' +
        '<div class="lang-menu" role="menu">' +
          LANGS.map(l =>
            '<button class="lang-opt' + (l.c === lang ? ' on' : '') + '" data-lang="' + l.c + '" role="menuitem">' +
              '<span class="lang-opt-native">' + l.native + '</span>' +
              '<span class="lang-opt-name">' + l.n + '</span>' +
            '</button>'
          ).join('') +
        '</div>';

      const btn = mount.querySelector('.lang-btn');
      const menu = mount.querySelector('.lang-menu');
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const open = mount.classList.toggle('open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      menu.querySelectorAll('.lang-opt').forEach(opt => {
        opt.addEventListener('click', () => { mount.classList.remove('open'); setLang(opt.dataset.lang); });
      });
    });
  }

  document.addEventListener('click', () => {
    document.querySelectorAll('[data-lang-mount].open').forEach(m => m.classList.remove('open'));
  });

  // expose
  window.I18N = { get lang() { return lang; }, t, apply, setLang, langs: LANGS };

  function init() { setDir(); apply(document); buildSwitchers(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
