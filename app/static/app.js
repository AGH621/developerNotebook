/* CSRF token injection for HTMX and fetch requests. */
window.devNotebookCsrfHeaders = function () {
  var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
  if (!m) return {};
  return { "x-csrftoken": decodeURIComponent(m[1]) };
};
document.addEventListener("htmx:configRequest", function (evt) {
  var h = window.devNotebookCsrfHeaders();
  if (h["x-csrftoken"]) evt.detail.headers["x-csrftoken"] = h["x-csrftoken"];
});

/* Reset inline “add” forms after successful HTMX POST (hx-on would require CSP unsafe-eval). */
document.body.addEventListener("htmx:afterRequest", function (evt) {
  if (!evt.detail.successful) return;
  var elt = evt.detail.elt;
  if (!elt || elt.tagName !== "FORM" || !elt.classList.contains("add-form")) return;
  elt.reset();
});

/* Theme toggle. */
(function () {
  var STORAGE_KEY = "developer-notebook-theme";
  var toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

  function applyLabel(theme) {
    var dark = theme === "dark";
    toggle.setAttribute("aria-label", dark ? "Use light theme" : "Use dark theme");
    toggle.setAttribute("title", dark ? "Light mode" : "Dark mode");
  }

  applyLabel(document.documentElement.getAttribute("data-theme") || "light");

  toggle.addEventListener("click", function () {
    var next =
      document.documentElement.getAttribute("data-theme") === "dark"
        ? "light"
        : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (e) {}
    applyLabel(next);
  });
})();

/* Copy-to-clipboard. */
(function () {
  var COPIED_MS = 1600;

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        if (document.execCommand("copy")) resolve();
        else reject(new Error("execCommand copy failed"));
      } catch (err) {
        reject(err);
      }
      document.body.removeChild(ta);
    });
  }

  document.body.addEventListener("click", function (evt) {
    var btn = evt.target && evt.target.closest && evt.target.closest(".entry-copy");
    if (!btn || btn.disabled) return;
    var row = btn.closest(".entry-row");
    var code = row && row.querySelector(".entry-row__code");
    var text = code
      ? (code.textContent || "").replace(/\u00a0/g, " ").trim()
      : (btn.getAttribute("data-command") || "").replace(/\u00a0/g, " ").trim();
    if (text === null || text === "") return;

    evt.preventDefault();
    var prevTitle = btn.getAttribute("title");
    if (prevTitle === null) prevTitle = "";
    var prevAria = btn.getAttribute("aria-label");
    if (prevAria === null) prevAria = "";
    btn.disabled = true;

    function setFeedback(titleText, ariaText) {
      btn.setAttribute("title", titleText);
      if (ariaText) btn.setAttribute("aria-label", ariaText);
      else btn.removeAttribute("aria-label");
    }

    copyText(text)
      .then(function () {
        btn.classList.add("is-copied");
        setFeedback("Copied!", "Command copied to clipboard");
        window.setTimeout(function () {
          btn.classList.remove("is-copied");
          btn.setAttribute("title", prevTitle);
          if (prevAria) btn.setAttribute("aria-label", prevAria);
          else btn.removeAttribute("aria-label");
          btn.disabled = false;
        }, COPIED_MS);
      })
      .catch(function () {
        setFeedback("Failed", "Copy failed");
        window.setTimeout(function () {
          btn.setAttribute("title", prevTitle);
          if (prevAria) btn.setAttribute("aria-label", prevAria);
          else btn.removeAttribute("aria-label");
          btn.disabled = false;
        }, 1800);
      });
  });
})();

/* Fixed-position tooltips; escape overflow clipping from .entry-table-wrap. */
(function () {
  var GAP = 6;
  var MARGIN = 10;
  var MAX_TOOLTIP_W = 352;
  var activeWrap = null;

  function clamp(n, lo, hi) {
    return Math.round(Math.min(Math.max(n, lo), hi));
  }

  function dismissAll() {
    if (!activeWrap) return;
    var tip = activeWrap.querySelector(".entry-row__ellipsis-tooltip");
    if (tip) {
      tip.classList.remove("entry-row__ellipsis-tooltip--open");
      tip.style.removeProperty("--entry-tip-left");
      tip.style.removeProperty("--entry-tip-top");
      tip.style.opacity = "";
    }
    activeWrap = null;
  }

  function hideLeaving(wrap) {
    if (wrap && activeWrap === wrap) dismissAll();
  }

  function placeTip(wrap) {
    var tip = wrap.querySelector(".entry-row__ellipsis-tooltip");
    var btn = wrap.querySelector(".entry-row__ellipsis-btn");
    if (!tip || !btn) return;

    dismissAll();

    var maxW = Math.min(MAX_TOOLTIP_W, Math.max(120, window.innerWidth - 2 * MARGIN));
    tip.style.maxWidth = maxW + "px";

    tip.style.setProperty("--entry-tip-top", "0px");
    tip.classList.add("entry-row__ellipsis-tooltip--open");
    tip.style.opacity = "0";
    activeWrap = wrap;

    requestAnimationFrame(function () {
      if (activeWrap !== wrap) return;

      function positionOnce() {
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var rr = btn.getBoundingClientRect();
        var tw = tip.getBoundingClientRect().width;
        var th = tip.getBoundingClientRect().height;
        var left = clamp(rr.left, MARGIN, vw - MARGIN - tw);
        var top = rr.bottom + GAP;

        if (top + th > vh - MARGIN) {
          top = rr.top - th - GAP;
        }
        top = clamp(top, MARGIN, Math.max(MARGIN, vh - MARGIN - th));
        left = clamp(left, MARGIN, vw - MARGIN - tw);

        tip.style.setProperty("--entry-tip-left", left + "px");
        tip.style.setProperty("--entry-tip-top", top + "px");
      }

      positionOnce();

      requestAnimationFrame(function () {
        if (activeWrap !== wrap) return;

        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var rr = btn.getBoundingClientRect();
        var tr = tip.getBoundingClientRect();
        var tw = tr.width;
        var th = tr.height;

        if (tr.bottom > vh - MARGIN || tr.top < MARGIN) {
          var top = rr.top - th - GAP;
          top = clamp(top, MARGIN, Math.max(MARGIN, vh - MARGIN - th));
          tip.style.setProperty("--entry-tip-top", top + "px");
        }

        var left = clamp(rr.left, MARGIN, vw - MARGIN - tw);
        tip.style.setProperty("--entry-tip-left", left + "px");

        tip.style.opacity = "";
      });
    });
  }

  document.body.addEventListener(
    "mouseover",
    function (evt) {
      var wrap = evt.target && evt.target.closest && evt.target.closest(".entry-row__ellipsis-wrap");
      if (!wrap) return;
      var rel = evt.relatedTarget;
      if (rel && wrap.contains(rel)) return;
      placeTip(wrap);
    },
    true,
  );

  document.body.addEventListener(
    "mouseout",
    function (evt) {
      var wrap = evt.target && evt.target.closest && evt.target.closest(".entry-row__ellipsis-wrap");
      if (!wrap) return;
      var rel = evt.relatedTarget;
      if (rel && wrap.contains(rel)) return;
      hideLeaving(wrap);
    },
    true,
  );

  document.body.addEventListener(
    "focusin",
    function (evt) {
      var wrap = evt.target && evt.target.closest && evt.target.closest(".entry-row__ellipsis-wrap");
      if (!wrap) return;
      placeTip(wrap);
    },
    true,
  );

  document.body.addEventListener(
    "focusout",
    function () {
      window.setTimeout(function () {
        if (!activeWrap) return;
        if (activeWrap.contains(document.activeElement)) return;
        try {
          if (activeWrap.matches(":hover")) return;
        } catch (ignore) {}
        dismissAll();
      }, 0);
    },
    true,
  );

  document.body.addEventListener(
    "scroll",
    function () {
      dismissAll();
    },
    true,
  );

  window.addEventListener("resize", dismissAll);

  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape" || evt.key === "Esc") dismissAll();
  });

  document.addEventListener(
    "pointerdown",
    function (evt) {
      if (!activeWrap) return;
      var t = evt.target;
      if (!t || typeof t.closest !== "function") return;
      var w = t.closest(".entry-row__ellipsis-wrap");
      if (w && w === activeWrap) return;
      dismissAll();
    },
    true,
  );

  document.body.addEventListener("htmx:afterSwap", dismissAll);
})();

/* Nav search dismiss. */
(function () {
  var slot = document.querySelector(".site-nav__search-slot");
  if (!slot) return;
  var input = slot.querySelector("input[name='q']");
  var live = document.getElementById("nav-search-live");
  if (!input || !live) return;

  function dismiss() {
    live.innerHTML = "";
  }

  input.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape" || evt.key === "Esc") {
      dismiss();
      input.blur();
    }
  });

  document.addEventListener(
    "pointerdown",
    function (evt) {
      if (!live.innerHTML.trim()) return;
      if (slot.contains(evt.target)) return;
      dismiss();
    },
    true,
  );

  slot.addEventListener("focusout", function () {
    window.setTimeout(function () {
      if (slot.contains(document.activeElement)) return;
      dismiss();
    }, 200);
  });
})();
