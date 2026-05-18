(function () {
  function bindTopicSortable() {
    var grid = document.getElementById("topic-grid");
    if (!grid || typeof Sortable === "undefined") return;
    if (grid._sortableTopic) {
      try { grid._sortableTopic.destroy(); } catch (e) {}
    }
    grid._sortableTopic = new Sortable(grid, {
      animation: 150,
      handle: ".topic-card__drag",
      draggable: ".topic-card",
      onEnd: function () {
        var ids = [].map.call(grid.querySelectorAll(".topic-card"), function (el) {
          return el.getAttribute("data-topic-id");
        });
        if (!ids.length) return;
        var body = new URLSearchParams();
        body.set("topic_order", ids.join(","));
        fetch("/topics/reorder", {
          method: "PUT",
          body: body,
          credentials: "same-origin",
          headers: Object.assign(
            { Accept: "application/json" },
            window.devNotebookCsrfHeaders ? window.devNotebookCsrfHeaders() : {},
          ),
        }).catch(function () {});
      },
    });
  }
  document.addEventListener("DOMContentLoaded", bindTopicSortable);
  document.body.addEventListener("htmx:afterSwap", bindTopicSortable);

  document.body.addEventListener(
    "toggle",
    function (e) {
      var t = e.target;
      if (
        !t ||
        !t.classList ||
        !t.classList.contains("topic-card__menu") ||
        !t.open
      ) {
        return;
      }
      document.querySelectorAll(".topic-card__menu").forEach(function (menu) {
        if (menu !== t) menu.open = false;
      });
    },
    true,
  );
})();
