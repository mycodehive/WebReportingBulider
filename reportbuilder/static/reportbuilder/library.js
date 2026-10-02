(() => {
  const form = document.getElementById('demo-bootstrap');
  if (!form) return;
  const status = form.querySelector('[data-demo-status]');
  const retry = form.querySelector('[data-demo-retry]');
  let busy = false;
  async function createDemo(event) {
    if (event) event.preventDefault();
    if (busy) return;
    busy = true;
    retry.hidden = true;
    status.textContent = 'Demo 보고서 생성중';
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
      if (!response.ok || !(await response.json()).ready) throw new Error('Demo creation failed');
      window.location.reload();
    } catch (_) {
      status.textContent = 'Demo 보고서를 생성하지 못했습니다. 다시 시도해 주세요.';
      retry.hidden = false;
    } finally { busy = false; }
  }
  form.addEventListener('submit', createDemo);
  createDemo();
})();
