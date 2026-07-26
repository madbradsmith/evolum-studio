/* ============================================================
   EVOLUM — slate render helpers. Reads window.EVOLUM_PROJECTS.
   Poster-dominant cards, shared across Catalog / Home / Supporter.
   ============================================================ */
window.EVOLUM = (function () {
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Poster inner: <img> with vignette fallback (tone), plus status + stamp overlay
  function posterInner(p, opts) {
    opts = opts || {};
    const tone = p.tone || 'ember';
    const vignette =
      '<div class="ev-pa ev-pa-' + tone + '"></div>' +
      '<div class="ev-pa-grain"></div>' +
      '<div class="ev-pa-typeset">' + esc(p.title) +
        '<small>' + esc(p.kind) + (p.genre ? ' · ' + esc(p.genre) : '') + '</small></div>';

    let media;
    if (p.poster) {
      media =
        '<img class="ev-poster-img" src="' + esc(p.poster) + '" alt="' + esc(p.title) + ' poster" loading="lazy" ' +
        'onerror="this.style.display=\'none\';this.parentNode.classList.add(\'ev-poster-fallback\')">' +
        '<div class="ev-poster-vig">' + vignette + '</div>';
    } else {
      media = '<div class="ev-poster-vig show">' + vignette + '</div>';
    }

    const stamp = '<div class="ev-pa-stamp">EV / ' + esc(p.num) + '</div>';
    const statusKey = p.statusLabel === 'Seeking Support' ? 'status.seeking'
                    : p.statusLabel === 'Pitching' ? 'status.pitching'
                    : p.statusLabel === 'In Development' ? 'status.dev' : '';
    const status = opts.hideStatus ? '' :
      '<div class="ev-pa-status"><span class="mono-tag ' + esc(p.statusTag) + '"' + (statusKey ? ' data-i18n="' + statusKey + '"' : '') + '>' + esc(p.statusLabel) + '</span></div>';
    return media + stamp + status;
  }

  // Full catalog card
  function catalogCard(p) {
    return (
      '<a class="cat-card acc-' + esc(p.accent) + '" href="/project-room?id=' + esc(p.id) + '" data-type="' + esc(p.type) + '" data-portal="' + esc(p.statusLabel) + '">' +
        '<div class="cat-poster">' + posterInner(p) + '</div>' +
        '<div class="cat-body">' +
          '<div class="cat-title">' + esc(p.title) + '</div>' +
          '<div class="cat-meta"><span>' + esc(p.kind) + '</span>' + (p.genre ? '<span>' + esc(p.genre) + '</span>' : '') + '</div>' +
          (p.logline ? '<div class="cat-logline">' + esc(p.logline) + '</div>' : '<div class="cat-logline cat-logline-muted">Logline in development.</div>') +
        '</div>' +
      '</a>'
    );
  }

  // Compact poster card (Home scroller / Supporter grid)
  function posterCard(p, extraClass) {
    return (
      '<a class="slate-card acc-' + esc(p.accent) + ' ' + (extraClass || '') + '" href="/project-room?id=' + esc(p.id) + '" data-id="' + esc(p.id) + '">' +
        '<div class="slate-poster">' + posterInner(p) + '</div>' +
        '<div class="slate-card-body">' +
          '<div class="slate-card-title">' + esc(p.title) + '</div>' +
          '<div class="slate-card-meta">' + esc(p.kind) + (p.genre ? ' · ' + esc(p.genre) : '') + '</div>' +
        '</div>' +
      '</a>'
    );
  }

  function render(selector, builder, list) {
    const el = document.querySelector(selector);
    if (!el) return;
    const items = list || window.EVOLUM_PROJECTS || [];
    el.innerHTML = items.map(builder).join('');
    return items.length;
  }

  return {
    projects: function () { return window.EVOLUM_PROJECTS || []; },
    count: function () { return (window.EVOLUM_PROJECTS || []).length; },
    catalogCard, posterCard, posterInner, esc,
    renderCatalog: function (sel, list) { return render(sel, catalogCard, list); },
    renderPosters: function (sel, list) { return render(sel, function (p) { return posterCard(p); }, list); },
  };
})();
