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
      var domainReady = button.dataset.domainReady !== "0";
      var enabled = ready && domainReady && !activeJob;
      button.disabled = !enabled;
      button.className = enabled
        ? "bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded"
        : "bg-gray-400 cursor-not-allowed text-white px-4 py-2 rounded";
    });
  }

  function setRefreshButtonsRunning(running) {
    document.querySelectorAll("[data-system-refresh-button]").forEach(function (button) {
      button.disabled = running;
      button.textContent = running ? "Updating..." : "Update state";
      button.className = running
        ? "bg-gray-400 cursor-not-allowed text-white px-4 py-2 rounded"
        : "bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700";
    });
  }

  function formatTimestamp(value) {
    if (!value) {
      return "";
    }
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString();
  }

  function formatElapsed(startedAt, completedAt) {
    if (!startedAt) {
      return "";
    }
    var started = new Date(startedAt);
    if (Number.isNaN(started.getTime())) {
      return "";
    }
    var ended = completedAt ? new Date(completedAt) : new Date();
    if (Number.isNaN(ended.getTime())) {
      return "";
    }
    var seconds = Math.max(0, Math.round((ended.getTime() - started.getTime()) / 1000));
    if (seconds < 60) {
      return seconds + "s";
    }
    return Math.floor(seconds / 60) + "m " + (seconds % 60) + "s";
  }

  function renderRefreshJob(job) {
    var status = job && job.status ? job.status : "idle";
    var running = status === "running";
    setText("rag-refresh-job-value", status);
    setText("rag-refresh-id-value", job && job.id ? job.id : "");
    setText("rag-refresh-correlation-value", job && job.correlation_id ? job.correlation_id : "");
    setText("rag-refresh-started-value", job ? formatTimestamp(job.started_at) : "");
    setText("rag-refresh-completed-value", job ? formatTimestamp(job.completed_at) : "");
    setText("rag-refresh-elapsed-value", job ? formatElapsed(job.started_at, job.completed_at) : "");
    var result = job && job.result ? job.result : {};
    var message = result.message || result.error_code || "";
    setText("rag-refresh-message-value", message);
    setRefreshButtonsRunning(running);
  }

  function isTerminalPipelineStatus(status) {
    return status === "completed" || status === "failed" || status === "cancelled";
  }

  function isTerminalContextPlanStatus(status) {
    return status === "completed" || status === "context_task_completed" || status === "failed" || status === "cancelled";
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
        var parts = [error.safe_message || "Policy pipeline failed."];
        if (error.error_code) {
          parts.push("Error code: " + error.error_code);
        }
        if (error.failed_stage) {
          parts.push("Failed stage: " + error.failed_stage);
        }
        errorBox.textContent = parts.join("\n");
        errorBox.classList.remove("hidden");
      } else {
        errorBox.textContent = "";
        errorBox.classList.add("hidden");
      }
    }
    var diagnostics = byId("pipeline-job-diagnostics");
    var diagnosticLink = byId("pipeline-job-diagnostic-link");
    var diagnosticsEnabled = panel && panel.dataset.developerDiagnostics === "1";
    if (diagnostics) {
      var showDiagnostics = diagnosticsEnabled && Boolean(job.correlation_id);
      diagnostics.classList.toggle("hidden", !showDiagnostics);
      if (diagnosticLink && showDiagnostics) {
        diagnosticLink.href = job.diagnostic_url || "/diagnostics/" + encodeURIComponent(job.correlation_id);
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

  function setContextPlanButtonRunning(running) {
    document.querySelectorAll("[data-context-plan-execute-button]").forEach(function (button) {
      button.disabled = running;
      button.textContent = running ? "Executing..." : "Execute approved plan";
      button.className = running
        ? "bg-gray-400 cursor-not-allowed text-white px-4 py-2 rounded"
        : "bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded";
    });
  }

  function renderContextPlanJob(job) {
    if (!job) {
      return;
    }
    var panel = byId("context-plan-execution-panel");
    if (panel) {
      panel.dataset.contextPlanJobId = isTerminalContextPlanStatus(job.status) ? "" : job.job_id;
      panel.dataset.contextPlanActive = isTerminalContextPlanStatus(job.status) ? "0" : "1";
    }
    var progress = job.progress || {};
    var current = Number.isFinite(Number(progress.current)) ? Number(progress.current) : 0;
    var total = Number.isFinite(Number(progress.total)) ? Number(progress.total) : 0;
    var percent = Number.isFinite(Number(progress.percent)) ? Number(progress.percent) : 0;
    setText("context-plan-job-status", job.status || "unknown");
    setText("context-plan-job-stage", job.current_stage || "unknown");
    setText("context-plan-progress", current + " / " + total);
    setText("context-plan-current-task", progress.current_task_title || progress.current_task_id || "idle");
    setText("context-plan-last-message", progress.last_message || "");
    var progressBar = byId("context-plan-progress-bar");
    if (progressBar) {
      progressBar.style.width = Math.max(0, Math.min(100, percent)) + "%";
    }
    setContextPlanButtonRunning(!isTerminalContextPlanStatus(job.status));
    if (isTerminalContextPlanStatus(job.status) && job.status === "completed") {
      window.setTimeout(function () {
        window.location.reload();
      }, 800);
    }
  }

  function pollContextPlanJob(jobId) {
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
        renderContextPlanJob(payload.job);
        if (!isTerminalContextPlanStatus(payload.job.status)) {
          window.setTimeout(function () {
            pollContextPlanJob(payload.job.job_id);
          }, 2000);
        }
      })
      .catch(function () {
        setText("context-plan-job-status", "unreachable");
      });
  }

  function bindContextPlanExecutionForms() {
    document.querySelectorAll("[data-context-plan-execute-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        setContextPlanButtonRunning(true);
        setText("context-plan-job-status", "starting");
        setText("context-plan-last-message", "Starting context plan execution.");
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
              renderContextPlanJob(payload.job);
              pollContextPlanJob(payload.job.job_id);
            } else if (payload.message) {
              setText("context-plan-job-status", "blocked");
              setText("context-plan-job-stage", payload.error_code || "request");
              setText("context-plan-last-message", payload.message);
              setContextPlanButtonRunning(false);
            }
          })
          .catch(function () {
            setText("context-plan-job-status", "unreachable");
            setText("context-plan-last-message", "Context plan execution could not be started.");
            setContextPlanButtonRunning(false);
          });
      });
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
      renderRefreshJob(payload.rag.refresh_job);
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
              renderRefreshJob(payload.response.job);
            }
          })
          .finally(function () {
            loadStatus();
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
    bindContextPlanExecutionForms();
    loadStatus();
    var contextPlanPanel = byId("context-plan-execution-panel");
    if (contextPlanPanel && contextPlanPanel.dataset.contextPlanJobId) {
      pollContextPlanJob(contextPlanPanel.dataset.contextPlanJobId);
    }
    var panel = byId("pipeline-job-panel");
    if (panel && panel.dataset.activeJobId) {
      pollPipelineJob(panel.dataset.activeJobId);
    }
    window.setInterval(loadStatus, 3000);
  });
})();
