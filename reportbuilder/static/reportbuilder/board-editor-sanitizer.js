(() => {
  const purify = window.DOMPurify;
  if (!purify) return;
  const videoURL = value => {
    try {
      const url = new URL(value.startsWith('//') ? `https:${value}` : value);
      if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
      if (['www.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname)
          && /^\/embed\/[A-Za-z0-9_-]+$/.test(url.pathname)) return url.href;
      if (url.hostname === 'player.vimeo.com' && /^\/video\/[0-9]+$/.test(url.pathname)) return url.href;
    } catch (_) { /* An invalid embed is removed. */ }
    return null;
  };
  const imageURL = value => {
    if (/^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 90000) return value;
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
    } catch (_) { return null; }
  };
  purify.addHook('uponSanitizeAttribute', (node, data) => {
    if (data.attrName === 'style') {
      const style = document.createElement('span').style;
      style.cssText = data.attrValue;
      const allowed = ['color', 'background-color', 'font-weight', 'font-style', 'text-decoration', 'text-align', 'font-size'];
      data.attrValue = allowed.filter(name => style.getPropertyValue(name)).map(
        name => `${name}:${style.getPropertyValue(name)}`).join(';');
    }
    if (data.attrName === 'src') {
      const value = node.tagName === 'IFRAME' ? videoURL(data.attrValue) : imageURL(data.attrValue);
      data.keepAttr = Boolean(value);
      if (value) data.attrValue = value;
    }
    if (data.attrName === 'href') {
      try { if (!['http:', 'https:', 'mailto:'].includes(new URL(data.attrValue, location.href).protocol)) data.keepAttr = false; }
      catch (_) { data.keepAttr = false; }
    }
  });
  purify.addHook('afterSanitizeAttributes', node => {
    if (['IMG', 'IFRAME'].includes(node.tagName) && !node.hasAttribute('src')) { node.remove(); return; }
    if (node.tagName === 'IFRAME') {
      node.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
      node.setAttribute('allowfullscreen', '');
      node.setAttribute('title', node.getAttribute('title') || '동영상');
    }
    if (['IMG', 'IFRAME'].includes(node.tagName)) {
      node.setAttribute('loading', 'lazy');
      node.setAttribute('referrerpolicy', 'no-referrer');
    }
  });
  window.boardEditorSafety = {
    imageURL,
    sanitize: html => purify.sanitize(html, {
      ALLOWED_TAGS: ['p', 'br', 'h2', 'h3', 'h4', 'strong', 'em', 'b', 'i', 'u', 's', 'blockquote',
        'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'div', 'a', 'code', 'pre', 'hr', 'img', 'iframe'],
      ALLOWED_ATTR: ['style', 'href', 'title', 'colspan', 'rowspan', 'src', 'alt', 'width', 'height',
        'sandbox', 'allowfullscreen', 'loading', 'referrerpolicy'],
      ALLOW_DATA_ATTR: false,
    }),
  };
})();
