(() => {
  document.querySelectorAll('[data-add-form]').forEach(button => {
    button.addEventListener('click', () => {
      const prefix = button.dataset.addForm;
      const total = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
      const template = document.getElementById(`${prefix}-empty`);
      const fragment = template.content.cloneNode(true);
      fragment.querySelectorAll('[name], [id], [for]').forEach(node => {
        ['name', 'id', 'for'].forEach(attr => {
          if (node.hasAttribute(attr)) node.setAttribute(attr, node.getAttribute(attr).replaceAll('__prefix__', total.value));
        });
      });
      document.querySelector(`[data-formset="${prefix}"]`).append(fragment);
      total.value = String(Number(total.value) + 1);
    });
  });
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
})();
