/** token must be obtained by your authenticated host SERVER, never a long-lived API key. */
export function showReport({ container, runtimeUrl, token }) {
  const url = new URL(runtimeUrl);
  if (url.protocol !== 'https:') throw new Error('Use HTTPS for the reporting runtime');
  const iframe = document.createElement('iframe');
  iframe.name = 'report-' + crypto.randomUUID();
  iframe.title = 'Report';
  iframe.style.cssText = 'width:100%;height:900px;border:0';
  const form = document.createElement('form');
  form.method = 'post';
  form.action = new URL('/embed/', url).href;
  form.target = iframe.name;
  const input = document.createElement('input');
  input.type = 'hidden'; input.name = 'token'; input.value = token;
  form.append(input); container.append(iframe, form);
  form.submit(); form.remove();
  return iframe;
}
