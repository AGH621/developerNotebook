(function () {
  var root = document.querySelector("[data-index-root]");
  if (!root) return;
  var input = root.querySelector("[data-index-filter]");
  if (!input) return;

  var jumpNav = root.querySelector("[data-index-jump]");
  if (jumpNav) {
    jumpNav.addEventListener(
      "click",
      function (e) {
        var a = e.target.closest("a.index-jump-nav__link");
        if (!a || !jumpNav.contains(a)) return;
        if (a.classList.contains("index-jump-nav__link--inactive")) {
          e.preventDefault();
        }
      },
      true,
    );
  }

  function norm(text) {
    return (text || "").toLowerCase();
  }

  function apply(filterText) {
    var q = norm(filterText).trim();
    var sections = root.querySelectorAll(".index-letter-block");

    sections.forEach(function (sectionBlock) {
      var rows = sectionBlock.querySelectorAll("[data-index-search]");
      var visibleSectionCount = 0;

      rows.forEach(function (row) {
        var hay = norm(row.getAttribute("data-index-search"));
        var show = q === "" || hay.indexOf(q) !== -1;
        row.style.display = show ? "" : "none";
        if (show) visibleSectionCount += 1;
      });

      sectionBlock.style.display = visibleSectionCount > 0 ? "" : "none";

      var bid = sectionBlock.id;
      if (jumpNav && bid) {
        var link = jumpNav.querySelector('a[href="#' + bid + '"]');
        if (link) {
          var showLink = visibleSectionCount > 0;
          link.classList.toggle("index-jump-nav__link--inactive", !showLink);
          link.tabIndex = showLink ? 0 : -1;
          link.setAttribute("aria-disabled", showLink ? "false" : "true");
        }
      }
    });
  }

  input.addEventListener("input", function () {
    apply(input.value);
  });

  apply(input.value || "");
})();
