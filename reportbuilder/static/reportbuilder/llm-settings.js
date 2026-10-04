(() => {
  'use strict';
  const form = document.getElementById('llm-settings-form');
  if (!form) return;
  const provider = form.elements.provider, base = form.elements.base_url, key = form.elements.api_key;
  const model = form.elements.model, ticket = form.elements.model_ticket;
  const button = document.getElementById('llm-load-models');
  const status = document.getElementById('llm-model-status');
  const defaults = JSON.parse(document.getElementById('llm-provider-base-urls').textContent);
  const submit = form.querySelector('button[type="submit"]');
  let controller, generation = 0;
  const option = (value, text) => {
    const node = document.createElement('option');
    node.value = value; node.textContent = text; return node;
  };
  function reset() {
    generation++; controller?.abort();
    ticket.value = '';
    model.replaceChildren(option('', '모델 불러오기 후 선택하세요'));
    status.textContent = '연결 정보가 변경되었습니다. 현재 API 키로 모델을 다시 불러오세요.';
    button.disabled = false; submit.disabled = false; button.removeAttribute('aria-busy');
  }
  provider.addEventListener('change', () => {
    base.value = defaults[provider.value] || '';
    reset();
  });
  base.addEventListener('input', reset);
  key.addEventListener('input', reset);
  button.addEventListener('click', async () => {
    if (!provider.reportValidity() || !base.reportValidity()) return;
    if (!key.value.trim() && form.dataset.savedKey !== 'true') {
      status.textContent = '먼저 API 키를 입력하세요.'; key.focus(); return;
    }
    const current = ++generation;
    controller?.abort(); controller = new AbortController();
    const activeController = controller;
    const timer = setTimeout(() => activeController.abort(), 55000);
    const selected = model.value;
    ticket.value = ''; button.disabled = true; submit.disabled = true;
    button.setAttribute('aria-busy', 'true'); status.textContent = '모델 목록을 불러오는 중입니다…';
    try {
      const response = await fetch(form.dataset.modelsUrl, {
        method: 'POST', credentials: 'same-origin', signal: activeController.signal,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.elements.csrfmiddlewaretoken.value},
        body: JSON.stringify({provider: provider.value, base_url: base.value,
          api_key: key.value.trim(), configuration_id: form.dataset.configurationId || null})
      });
      if (current !== generation) return;
      const result = await response.json();
      if (current !== generation) return;
      if (!response.ok) throw new Error(result.message || '모델 목록을 불러오지 못했습니다.');
      model.replaceChildren(option('', '모델을 선택하세요'), ...result.models.map(item =>
        option(item.id, item.label === item.id ? item.id : `${item.label} · ${item.id}`)));
      if (result.models.some(item => item.id === selected)) model.value = selected;
      else if (result.models.length === 1) model.value = result.models[0].id;
      ticket.value = result.model_ticket;
      status.textContent = `${result.models.length}개 모델을 불러왔습니다. 사용할 모델을 선택하세요.`;
    } catch (error) {
      if (current === generation) {
        model.replaceChildren(option('', '모델 불러오기 후 선택하세요'));
        status.textContent = error.name === 'AbortError' ? '조회 시간이 초과되었습니다. 다시 시도하세요.' :
          error instanceof SyntaxError ? '서버 응답을 확인할 수 없습니다. 로그인 상태를 확인하세요.' : error.message;
      }
    } finally {
      clearTimeout(timer);
      if (current === generation) {
        button.disabled = false; submit.disabled = false; button.removeAttribute('aria-busy');
      }
    }
  });
})();
