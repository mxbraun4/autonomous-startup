/**
 * Startup-VC Marketplace - Client-side form validation
 */

(function () {
  "use strict";

  /**
   * Validate that all required fields in a form have non-empty values.
   * Returns an array of field names that are missing or empty.
   */
  function getEmptyRequiredFields(form) {
    var requiredInputs = form.querySelectorAll("input[required]");
    var empty = [];
    requiredInputs.forEach(function (input) {
      if (!input.value || input.value.trim() === "") {
        empty.push(input.name || input.id || "unknown");
      }
    });
    return empty;
  }

  /**
   * Attach a submit listener to a form that checks required fields
   * before allowing submission.
   */
  function attachValidation(form) {
    form.addEventListener("submit", function (event) {
      var emptyFields = getEmptyRequiredFields(form);

      if (emptyFields.length > 0) {
        event.preventDefault();
        alert(
          "Please fill in the following required fields: " +
            emptyFields.join(", ")
        );
        // Focus the first empty required field
        var firstEmpty = form.querySelector(
          'input[name="' + emptyFields[0] + '"]'
        );
        if (firstEmpty) {
          firstEmpty.focus();
        }
        return;
      }

      // Prevent actual navigation for the stub (action="#")
      event.preventDefault();
      alert("Form submitted successfully. Thank you for signing up!");
    });
  }

  /**
   * Initialise validation on all forms once the DOM is ready.
   */
  document.addEventListener("DOMContentLoaded", function () {
    var forms = document.querySelectorAll("form");
    forms.forEach(function (form) {
      attachValidation(form);
    });
  });
})();
