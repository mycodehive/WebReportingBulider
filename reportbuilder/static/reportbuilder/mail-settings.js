(() => {
  const provider = document.getElementById('id_provider');
  if (!provider) return;
  const update = () => {
    document.querySelectorAll('[data-mail-provider]').forEach(group => {
      // Keep all values available for saving and preserve credentials across switches.
      group.hidden = group.dataset.mailProvider !== provider.value && !group.querySelector('.errorlist');
    });
  };
  provider.addEventListener('change', update);
  update();
  const test = document.getElementById('mail-test-form');
  test?.addEventListener('submit', () => {
    test.querySelector('button').disabled = true;
    test.querySelector('.mail-send-status').hidden = false;
  });
})();
