(function () {
  "use strict";

  function token() {
    var meta = document.querySelector("meta[name='csrf-token']");
    return meta ? meta.content : "";
  }

  function addFormTokens() {
    document.querySelectorAll("form[method='post'], form[method='POST']").forEach(function (form) {
      if (form.querySelector("input[name='csrf_token']")) {
        return;
      }
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      input.value = token();
      form.appendChild(input);
    });
  }

  window.secPolicyCsrfToken = token;
  document.addEventListener("DOMContentLoaded", addFormTokens);
}());
