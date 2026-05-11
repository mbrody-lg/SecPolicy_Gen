(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    var element = byId(id);
    if (element) {
      element.textContent = value || "";
    }
  }

  function setGenerateState(ready) {
    document.querySelectorAll("[data-generate-policy-button]").forEach(function (button) {
      button.disabled = !ready;
      button.className = ready
        ? "bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded"
        : "bg-gray-400 cursor-not-allowed text-white px-4 py-2 rounded";
    });
  }

  function renderStatus(payload) {
    if (!payload) {
      return;
    }
    var ready = payload.status === "ready";
    setText("system-status-value", payload.status || "unknown");
    if (payload.rag) {
      setText("rag-status-value", payload.rag.status || "unknown");
      setText("rag-action-value", payload.rag.action || "");
      var job = payload.rag.refresh_job;
      setText("rag-refresh-job-value", job && job.status ? job.status : "idle");
    }
    setGenerateState(ready);
  }

  function loadStatus() {
    return fetch("/system/status", { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json();
      })
      .then(renderStatus)
      .catch(function () {
        setText("system-status-value", "unreachable");
      });
  }

  function bindRefreshForms() {
    document.querySelectorAll("[data-system-refresh-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var button = form.querySelector("button[type='submit']");
        if (button) {
          button.disabled = true;
          button.textContent = "Updating...";
        }
        setText("rag-refresh-job-value", "starting");
        fetch(form.action, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
        })
          .then(function (response) {
            return response.json();
          })
          .then(function (payload) {
            renderStatus(payload.status);
            if (payload.response && payload.response.job) {
              setText("rag-refresh-job-value", payload.response.job.status);
            }
          })
          .finally(function () {
            if (button) {
              button.disabled = false;
              button.textContent = "Update state";
            }
          });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!byId("system-readiness-panel")) {
      return;
    }
    bindRefreshForms();
    loadStatus();
    window.setInterval(loadStatus, 3000);
  });
})();
