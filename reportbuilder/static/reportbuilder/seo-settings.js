(() => {
  const pairs = [['title', 'seo-preview-title'], ['description', 'seo-preview-description'], ['site_url', 'seo-preview-url']];
  pairs.forEach(([name, target]) => {
    const input = document.getElementById(`id_${name}`), output = document.getElementById(target);
    if (!input || !output) return;
    const fallback = output.textContent;
    const update = () => { output.textContent = input.value.trim() ? (name === 'site_url' ? input.value.trim().replace(/\/+$/, '') + '/intro' : input.value.trim()) : fallback; };
    input.addEventListener('input', update);
    update();
  });
})();
