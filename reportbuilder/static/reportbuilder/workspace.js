/* Workspace preferences are UI state only; report paper and definitions are untouched. */
(function () {
  'use strict';
  const root = document.documentElement;
  const keys = { theme: 'webreport.theme', sidebar: 'webreport.sidebar' };
  const read = key => { try { return window.localStorage.getItem(key); } catch (_) { return null; } };
  const write = (key, value) => { try { window.localStorage.setItem(key, value); } catch (_) { /* Private-mode storage may be unavailable. */ } };
  const media = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let selectedTheme = ['light', 'dark'].includes(read(keys.theme)) ? read(keys.theme) : null;
  let collapsed = read(keys.sidebar) === 'collapsed';
  let designer, fullscreenButton, fallback = false, wasFullscreen = false, busy = false;

  function applyTheme(theme) {
    root.dataset.theme = theme;
    const button = document.getElementById('theme-toggle');
    if (button) {
      const dark = theme === 'dark';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? '라이트 모드 사용' : '다크 모드 사용');
      button.title = button.getAttribute('aria-label');
      const label = button.querySelector('[data-theme-label]');
      if (label) label.textContent = dark ? '라이트 모드' : '다크 모드';
    }
  }
  function applySidebar() {
    root.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
    const button = document.getElementById('sidebar-toggle');
    if (button) {
      button.setAttribute('aria-expanded', String(!collapsed));
      button.setAttribute('aria-label', collapsed ? '사이드바 펼치기' : '사이드바 접기');
      button.title = button.getAttribute('aria-label');
    }
  }
  function announce(message) {
    const status = document.getElementById('workspace-status');
    if (status) status.textContent = message;
  }
  function refreshFullscreen() {
    if (!designer) return;
    if (document.fullscreenElement === designer) fallback = false;
    const active = document.fullscreenElement === designer || fallback;
    designer.classList.toggle('is-fullscreen', active);
    document.body.classList.toggle('workspace-fullscreen-fallback', fallback);
    fullscreenButton.setAttribute('aria-pressed', String(active));
    fullscreenButton.title = active ? '전체화면 종료 (Esc)' : '전체화면으로 작업';
    fullscreenButton.setAttribute('aria-label', fullscreenButton.title);
    const label = fullscreenButton.querySelector('[data-fullscreen-label]');
    if (label) label.textContent = active ? '전체화면 종료' : '전체화면';
    if (wasFullscreen && !active && !designer.querySelector('dialog[open]')) fullscreenButton.focus({ preventScroll: true });
    wasFullscreen = active;
  }
  async function toggleFullscreen() {
    if (!designer || busy) return;
    busy = true;
    fullscreenButton.disabled = true;
    try {
      if (fallback) {
        fallback = false;
        announce('전체화면 작업을 종료했습니다.');
      } else if (document.fullscreenElement === designer) {
        await document.exitFullscreen();
        announce('전체화면 작업을 종료했습니다.');
      } else if (typeof designer.requestFullscreen === 'function') {
        try {
          await designer.requestFullscreen();
          announce('전체화면으로 작업합니다. Esc 키로 종료할 수 있습니다.');
        } catch (_) {
          fallback = true;
          announce('화면을 가득 채워 작업합니다. Esc 키로 종료할 수 있습니다.');
        }
      } else {
        fallback = true;
        announce('화면을 가득 채워 작업합니다. Esc 키로 종료할 수 있습니다.');
      }
    } catch (_) {
      announce('전체화면을 종료하지 못했습니다. Esc 키를 사용해 주세요.');
    } finally {
      busy = false;
      fullscreenButton.disabled = false;
      refreshFullscreen();
    }
  }
  function init() {
    applyTheme(selectedTheme || (media && media.matches ? 'dark' : 'light'));
    applySidebar();
    const themeButton = document.getElementById('theme-toggle');
    if (themeButton) themeButton.addEventListener('click', () => {
      selectedTheme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      write(keys.theme, selectedTheme);
      applyTheme(selectedTheme);
    });
    const sidebarButton = document.getElementById('sidebar-toggle');
    if (sidebarButton) sidebarButton.addEventListener('click', () => {
      collapsed = !collapsed;
      write(keys.sidebar, collapsed ? 'collapsed' : 'expanded');
      applySidebar();
    });
    designer = document.getElementById('designer');
    fullscreenButton = document.getElementById('workspace-fullscreen');
    if (designer && fullscreenButton) {
      fullscreenButton.addEventListener('click', toggleFullscreen);
      document.addEventListener('fullscreenchange', refreshFullscreen);
      document.addEventListener('keydown', event => {
        // Let the native dialog consume its own Escape before exiting the fallback workspace.
        if (event.key === 'Escape' && fallback && !designer.querySelector('dialog[open]')) {
          fallback = false;
          refreshFullscreen();
          announce('전체화면 작업을 종료했습니다.');
        }
      });
      refreshFullscreen();
    }
  }
  applyTheme(selectedTheme || (media && media.matches ? 'dark' : 'light'));
  applySidebar();
  if (media && typeof media.addEventListener === 'function') media.addEventListener('change', event => {
    if (!selectedTheme) applyTheme(event.matches ? 'dark' : 'light');
  });
  window.addEventListener('storage', event => {
    if (event.key === keys.theme) {
      selectedTheme = ['light', 'dark'].includes(event.newValue) ? event.newValue : null;
      applyTheme(selectedTheme || (media && media.matches ? 'dark' : 'light'));
    } else if (event.key === keys.sidebar) {
      collapsed = event.newValue === 'collapsed';
      applySidebar();
    }
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
}());
