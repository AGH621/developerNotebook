(function () {
  function postForm(url, field, ids) {
    if (!ids.length) return;
    var body = new URLSearchParams();
    body.set(field, ids.join(","));
    return fetch(url, {
      method: "PUT",
      body: body,
      credentials: "same-origin",
      headers: Object.assign(
        { Accept: "application/json" },
        window.devNotebookCsrfHeaders ? window.devNotebookCsrfHeaders() : {},
      ),
    }).catch(function () {});
  }

  function bindTopicPageSortables() {
    if (typeof Sortable === "undefined") return;

    var sectionList = document.getElementById("section-list");
    if (sectionList) {
      if (sectionList._sortableSections) {
        try { sectionList._sortableSections.destroy(); } catch (e) {}
      }
      sectionList._sortableSections = new Sortable(sectionList, {
        animation: 150,
        handle: ".topic-section__drag",
        draggable: ".topic-section",
        filter: ".topic-section--editing",
        preventOnFilter: false,
        ghostClass: "sortable-ghost",
        dragClass: "sortable-drag",
        onEnd: function () {
          var ids = [].map.call(sectionList.querySelectorAll(".topic-section"), function (el) {
            return el.getAttribute("data-section-id");
          }).filter(Boolean);
          postForm("/sections/reorder", "section_order", ids);
        },
      });
    }

    [].forEach.call(document.querySelectorAll(".entry-tbody"), function (tbody) {
      if (tbody._sortableEntries) {
        try { tbody._sortableEntries.destroy(); } catch (e) {}
      }
      tbody._sortableEntries = new Sortable(tbody, {
        animation: 150,
        handle: ".entry-row__drag",
        draggable: "tr.entry-row",
        filter: ".entry-row--editing",
        preventOnFilter: false,
        ghostClass: "sortable-ghost",
        dragClass: "sortable-drag",
        onEnd: function () {
          var ids = [].map.call(tbody.querySelectorAll("tr.entry-row"), function (el) {
            return el.getAttribute("data-entry-id");
          }).filter(Boolean);
          postForm("/entries/reorder", "entry_order", ids);
        },
      });
    });
  }

  document.addEventListener("DOMContentLoaded", bindTopicPageSortables);
  document.body.addEventListener("htmx:afterSwap", bindTopicPageSortables);
})();
