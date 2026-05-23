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
  var STORAGE_KEY = "developer-memory-garden-theme";
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

  function bindCopyButton(btn, text, feedback) {
    if (!text) return;
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
        setFeedback(feedback.successTitle, feedback.successAria);
        var menu = btn.closest(".entry-row__menu");
        window.setTimeout(function () {
          btn.classList.remove("is-copied");
          btn.setAttribute("title", prevTitle);
          if (prevAria) btn.setAttribute("aria-label", prevAria);
          else btn.removeAttribute("aria-label");
          btn.disabled = false;
          if (menu) menu.open = false;
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
  }

  document.body.addEventListener("click", function (evt) {
    var copyBtn = evt.target && evt.target.closest && evt.target.closest(".copy-btn[data-copy-text]");
    if (copyBtn && !copyBtn.disabled) {
      var copyTextValue = (copyBtn.getAttribute("data-copy-text") || "").trim();
      if (!copyTextValue) return;
      evt.preventDefault();
      bindCopyButton(copyBtn, copyTextValue, {
        successTitle: "Copied!",
        successAria: "Invitation link copied to clipboard",
      });
      return;
    }

    var btn = evt.target && evt.target.closest && evt.target.closest(".entry-copy");
    if (!btn || btn.disabled) return;
    var row = btn.closest(".entry-row");
    var code = row && row.querySelector(".entry-row__code");
    var text = code
      ? (code.textContent || "").replace(/\u00a0/g, " ").trim()
      : (btn.getAttribute("data-command") || "").replace(/\u00a0/g, " ").trim();
    if (text === null || text === "") return;

    evt.preventDefault();
    bindCopyButton(btn, text, {
      successTitle: "Copied!",
      successAria: "Command copied to clipboard",
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

/* Action menus: single open at a time; fixed dropdown in entry tables. */
(function () {
  var MENU_SELECTOR = ".topic-card__menu, .entry-row__menu";
  var GAP = 6;

  function clearEntryMenuPosition(menu) {
    var dropdown = menu && menu.querySelector(".entry-row__menu-dropdown");
    if (!dropdown) return;
    dropdown.classList.remove("entry-row__menu-dropdown--fixed");
    dropdown.style.removeProperty("top");
    dropdown.style.removeProperty("left");
  }

  function placeEntryMenu(menu) {
    var trigger = menu.querySelector(".entry-row__menu-trigger");
    var dropdown = menu.querySelector(".entry-row__menu-dropdown");
    if (!trigger || !dropdown) return;

    dropdown.classList.add("entry-row__menu-dropdown--fixed");
    var rr = trigger.getBoundingClientRect();
    dropdown.style.opacity = "0";
    dropdown.style.left = "0px";
    dropdown.style.top = "0px";

    requestAnimationFrame(function () {
      if (!menu.open) return;
      var dr = dropdown.getBoundingClientRect();
      var left = rr.right - dr.width;
      var top = rr.bottom + GAP;
      dropdown.style.left = Math.round(left) + "px";
      dropdown.style.top = Math.round(top) + "px";
      dropdown.style.opacity = "";
    });
  }

  function repositionOpenEntryMenus() {
    document.querySelectorAll(".entry-row__menu[open]").forEach(placeEntryMenu);
  }

  document.body.addEventListener(
    "toggle",
    function (e) {
      var t = e.target;
      if (!t || !t.classList) return;

      var isTopic = t.classList.contains("topic-card__menu");
      var isEntry = t.classList.contains("entry-row__menu");
      if (!isTopic && !isEntry) return;

      if (t.open) {
        document.querySelectorAll(MENU_SELECTOR).forEach(function (menu) {
          if (menu !== t) {
            menu.open = false;
            if (menu.classList.contains("entry-row__menu")) clearEntryMenuPosition(menu);
          }
        });
        if (isEntry) placeEntryMenu(t);
      } else if (isEntry) {
        clearEntryMenuPosition(t);
      }
    },
    true,
  );

  window.addEventListener("resize", function () {
    repositionOpenEntryMenus();
  });

  document.body.addEventListener(
    "scroll",
    function () {
      repositionOpenEntryMenus();
    },
    true,
  );

  document.body.addEventListener("htmx:afterSwap", function () {
    document.querySelectorAll(".entry-row__menu").forEach(clearEntryMenuPosition);
  });
})();

/* Nav search dismiss. */
(function () {
  var slot = document.querySelector(".site-nav__search-slot");
  if (!slot) return;
  var input = slot.querySelector("input[name='q']");
  var results = document.getElementById("nav-search-results");
  if (!input || !results) return;

  function clearResults() {
    results.innerHTML = "";
  }

  function dismiss() {
    clearResults();
    input.blur();
  }

  input.addEventListener("input", function () {
    if (!input.value.trim()) clearResults();
  });

  input.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape" || evt.key === "Esc") {
      dismiss();
      input.blur();
    }
  });

  document.addEventListener(
    "pointerdown",
    function (evt) {
      if (!slot.matches(":focus-within") && !results.innerHTML.trim()) return;
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

/* Page search: clear results when the query is cleared. */
(function () {
  var input = document.getElementById("page-search-q");
  var results = document.getElementById("page-search-results");
  if (!input || !results) return;

  input.addEventListener("input", function () {
    if (!input.value.trim()) results.innerHTML = "";
  });
})();

/* Custom confirm dialog (replaces native confirm() for hx-confirm and data-confirm forms). */
(function () {
  var dialog = document.getElementById("confirm-dialog");
  if (!dialog) return;

  var msgEl = document.getElementById("confirm-dialog-msg");
  var cancelBtn = dialog.querySelector(".confirm-dialog__btn--cancel");
  var confirmBtn = document.getElementById("confirm-dialog-ok");
  var pendingResolve = null;

  function finish(result) {
    if (!pendingResolve) return;
    var resolve = pendingResolve;
    pendingResolve = null;
    resolve(result);
  }

  function closeDialog(result) {
    finish(result);
    if (dialog.open) dialog.close();
  }

  window.confirmModal = function (message, options) {
    options = options || {};
    if (msgEl) msgEl.textContent = message;
    if (confirmBtn) {
      confirmBtn.textContent = options.confirmLabel || "Delete";
    }
    return new Promise(function (resolve) {
      pendingResolve = resolve;
      dialog.showModal();
      if (confirmBtn) confirmBtn.focus();
    });
  };

  if (cancelBtn) {
    cancelBtn.addEventListener("click", function () {
      closeDialog(false);
    });
  }

  if (confirmBtn) {
    confirmBtn.addEventListener("click", function () {
      closeDialog(true);
    });
  }

  dialog.addEventListener("cancel", function (evt) {
    evt.preventDefault();
    closeDialog(false);
  });

  dialog.addEventListener("close", function () {
    finish(false);
  });

  document.body.addEventListener("htmx:confirm", function (evt) {
    if (!evt.detail || !evt.detail.question) return;
    evt.preventDefault();
    window.confirmModal(evt.detail.question).then(function (ok) {
      if (ok) evt.detail.issueRequest(true);
    });
  });

  document.body.addEventListener("submit", function (evt) {
    var form = evt.target;
    if (!form || form.tagName !== "FORM") return;
    var msg = form.getAttribute("data-confirm");
    if (!msg) return;
    if (form.dataset.confirmBypass) {
      delete form.dataset.confirmBypass;
      return;
    }
    evt.preventDefault();
    var okLabel = form.getAttribute("data-confirm-ok") || "Delete";
    window.confirmModal(msg, { confirmLabel: okLabel }).then(function (ok) {
      if (!ok) return;
      form.dataset.confirmBypass = "1";
      form.requestSubmit();
    });
  });
})();

/* Admin starter catalog: guest visibility checkbox (background save — no page reload). */
document.body.addEventListener("change", function (evt) {
  var input = evt.target;
  if (!input || !input.matches || !input.matches("[data-guest-visible-toggle]")) return;
  var form = input.form;
  if (!form) return;
  var hidden = form.querySelector('input[type="hidden"][name="guest_visible"]');
  if (hidden) hidden.disabled = input.checked;

  var intendedChecked = input.checked;
  var errorEl = form.querySelector("[data-guest-visible-error]");
  if (errorEl) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  var headers = Object.assign(
    { Accept: "application/json" },
    window.devNotebookCsrfHeaders ? window.devNotebookCsrfHeaders() : {},
  );

  fetch(form.action, {
    method: "POST",
    body: new FormData(form),
    credentials: "same-origin",
    headers: headers,
  })
    .then(function (res) {
      if (res.ok) return;
      throw new Error("save failed");
    })
    .catch(function () {
      input.checked = !intendedChecked;
      if (hidden) hidden.disabled = input.checked;
      if (errorEl) {
        errorEl.textContent = "Could not update guest visibility. Try again.";
        errorEl.hidden = false;
      }
    });
});
