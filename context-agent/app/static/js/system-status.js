(function () {
  var runtimeReady = false;

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
    var panel = byId("pipeline-job-panel");
    var activeJob = panel && panel.dataset.activeJobId;
    document.querySelectorAll("[data-generate-policy-button]").forEach(function (button) {
      button.disabled = !ready || Boolean(activeJob);
      button.className = ready && !activeJob
        ? "bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded"
        : "bg-gray-400 cursor-not-allowed text-white px-4 py-2 rounded";
    });
  }

  function isTerminalPipelineStatus(status) {
    return status === "completed" || status === "failed" || status === "cancelled";
  }

  function setPipelinePanelVisible(visible) {
    var panel = byId("pipeline-job-panel");
    if (panel) {
      panel.classList.toggle("hidden", !visible);
    }
  }

  function renderPipelineJob(job) {
    if (!job) {
      return;
    }
    var panel = byId("pipeline-job-panel");
    if (panel) {
      panel.dataset.activeJobId = isTerminalPipelineStatus(job.status) ? "" : job.job_id;
    }
    setPipelinePanelVisible(true);
    setText("pipeline-job-status", job.status || "unknown");
    setText("pipeline-job-stage", job.current_stage || "unknown");
    setText("pipeline-job-correlation", job.correlation_id || "");
    var errorBox = byId("pipeline-job-error");
    if (errorBox) {
      var error = job.last_error;
      if (error && (error.safe_message || error.error_code)) {
        errorBox.textContent = error.safe_message || error.error_code;
        errorBox.classList.remove("hidden");
      } else {
        errorBox.textContent = "";
        errorBox.classList.add("hidden");
      }
    }
    setGenerateState(runtimeReady);
  }

  function pollPipelineJob(jobId) {
    if (!jobId) {
      return;
    }
    fetch("/pipeline/jobs/" + encodeURIComponent(jobId), { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        if (!payload.success || !payload.job) {
          return;
        }
        renderPipelineJob(payload.job);
        if (!isTerminalPipelineStatus(payload.job.status)) {
          window.setTimeout(function () {
            pollPipelineJob(payload.job.job_id);
          }, 2000);
        }
      })
      .catch(function () {
        setText("pipeline-job-status", "unreachable");
      });
  }

  function bindGenerateForms() {
    document.querySelectorAll("[data-generate-policy-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var button = form.querySelector("button[type='submit']");
        if (button) {
          button.disabled = true;
          button.textContent = "Starting...";
        }
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
            if (payload.job) {
              renderPipelineJob(payload.job);
              pollPipelineJob(payload.job.job_id);
            } else if (payload.message) {
              var errorBox = byId("pipeline-job-error");
              setPipelinePanelVisible(true);
              setText("pipeline-job-status", "blocked");
              setText("pipeline-job-stage", payload.error_code || "request");
              if (errorBox) {
                errorBox.textContent = payload.message;
                errorBox.classList.remove("hidden");
              }
            }
          })
          .finally(function () {
            if (button) {
              button.textContent = "Generate and validate";
            }
          });
      });
    });
  }

  function renderStatus(payload) {
    if (!payload) {
      return;
    }
    var ready = payload.status === "ready";
    runtimeReady = ready;
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
    bindGenerateForms();
    loadStatus();
    var panel = byId("pipeline-job-panel");
    if (panel && panel.dataset.activeJobId) {
      pollPipelineJob(panel.dataset.activeJobId);
    }
    window.setInterval(loadStatus, 3000);
  });
})();
