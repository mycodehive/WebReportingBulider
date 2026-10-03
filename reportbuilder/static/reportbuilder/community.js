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
  document.querySelectorAll('[data-user-picker]').forEach(root => {
    const input = root.querySelector('.user-picker-search');
    const results = root.querySelector('.user-picker-results');
    const selected = root.querySelector('.user-picker-selected');
    const select = root.querySelector('[data-user-select]');
    let timer;
    let controller;

    const renderSelected = () => {
      selected.replaceChildren();
      Array.from(select.selectedOptions).forEach(option => {
        const chip = document.createElement('span');
        chip.className = 'user-picker-chip';
        const label = document.createElement('span');
        label.textContent = option.dataset.label || option.textContent;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'user-picker-remove';
        remove.textContent = '×';
        remove.setAttribute('aria-label', label.textContent + ' 선택 해제');
        remove.addEventListener('click', () => {
          option.selected = false;
          renderSelected();
        });
        chip.append(label, remove);
        selected.append(chip);
      });
    };

    const addUser = user => {
      let option = Array.from(select.options).find(item => item.value === user.id);
      if (!option) {
        option = document.createElement('option');
        option.value = user.id;
        select.add(option);
      }
      option.textContent = user.username;
      option.dataset.label = [user.name, user.username, user.email].filter(Boolean).join(' · ');
      option.selected = true;
      renderSelected();
      input.value = '';
      results.replaceChildren();
      input.focus();
    };

    input.addEventListener('input', () => {
      clearTimeout(timer);
      if (controller) controller.abort();
      const query = input.value.trim();
      results.replaceChildren();
      if (query.length < 2) return;
      timer = setTimeout(async () => {
        controller = new AbortController();
        const url = new URL(root.dataset.searchUrl, window.location.origin);
        url.searchParams.set('q', query);
        if (root.dataset.board) url.searchParams.set('board', root.dataset.board);
        try {
          const response = await fetch(url, {headers: {'Accept': 'application/json'}, signal: controller.signal});
          if (!response.ok) throw new Error('검색 실패');
          const data = await response.json();
          const options = data.results.filter(user => !Array.from(select.selectedOptions).some(option => option.value === user.id));
          if (!options.length) {
            const empty = document.createElement('div');
            empty.className = 'user-picker-empty';
            empty.textContent = '검색 결과가 없습니다.';
            results.append(empty);
          }
          options.forEach(user => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'user-picker-option';
            button.setAttribute('role', 'option');
            const main = document.createElement('strong');
            main.textContent = user.name;
            const meta = document.createElement('small');
            meta.textContent = [user.username, user.email].filter(Boolean).join(' · ');
            button.append(main, meta);
            button.addEventListener('click', () => addUser(user));
            results.append(button);
          });
        } catch (error) {
          if (error.name !== 'AbortError') {
            const message = document.createElement('div');
            message.className = 'user-picker-empty';
            message.textContent = '사용자 검색 중 오류가 발생했습니다.';
            results.append(message);
          }
        }
      }, 220);
    });
    renderSelected();
  });
})();
