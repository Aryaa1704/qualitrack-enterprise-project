(function () {
  function setSubmitting(form) {
    const submitter = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!submitter || submitter.dataset.loading === 'true') return;
    submitter.dataset.originalText = submitter.textContent.trim();
    submitter.dataset.loading = 'true';
    submitter.disabled = true;
    submitter.classList.add('is-loading');
    submitter.setAttribute('aria-busy', 'true');
  }

  document.addEventListener('submit', function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }
    setSubmitting(form);
  });

  document.addEventListener('invalid', function (event) {
    const field = event.target;
    if (field instanceof HTMLElement) {
      field.classList.add('field-invalid');
      const form = field.closest('form');
      if (form) form.classList.add('was-validated');
    }
  }, true);

  document.addEventListener('input', function (event) {
    const field = event.target;
    if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement) {
      if (field.checkValidity()) field.classList.remove('field-invalid');
    }
  });
}());
