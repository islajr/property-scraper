/* Shared by Next, Astro, and sibling subdomains. Dark is the default; explicit preferences take priority. */
(function () {
  var key = 'akinmokun-theme';
  function savedTheme() {
    // The parent-domain cookie keeps a preference consistent between subdomains.
    var match = document.cookie.match(/(?:^|; )akinmokun-theme=(light|dark)(?:;|$)/);
    if (match) return match[1];
    try {
      var stored = localStorage.getItem(key);
      return stored === 'light' || stored === 'dark' ? stored : 'dark';
    } catch (_) { return 'dark'; }
  }
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
      button.setAttribute('aria-checked', String(theme === 'dark'));
      button.setAttribute('aria-label', 'Dark appearance');
    });
  }
  apply(savedTheme());
  document.addEventListener('DOMContentLoaded', function () { apply(savedTheme()); });
  document.addEventListener('click', function (event) {
    if (!(event.target instanceof Element) || !event.target.closest('[data-theme-toggle]')) return;
    var theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, theme); } catch (_) { /* Cookie still works. */ }
    var domain = /(^|\.)akinmokun\.com$/.test(location.hostname) ? '; Domain=akinmokun.com' : '';
    document.cookie = key + '=' + theme + '; Path=/; Max-Age=31536000; SameSite=Lax' + domain + (location.protocol === 'https:' ? '; Secure' : '');
    apply(theme);
  });
  // Native disclosure navigation works without JavaScript; these are keyboard conveniences.
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('[data-site-disclosure][open]').forEach(function (menu) {
      menu.removeAttribute('open');
      menu.querySelector('summary').focus();
    });
  });
  document.addEventListener('click', function (event) {
    document.querySelectorAll('[data-site-disclosure][open]').forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });
  document.addEventListener('toggle', function (event) {
    var opened = event.target;
    if (!(opened instanceof HTMLDetailsElement) || !opened.matches('[data-site-disclosure]') || !opened.open) return;
    document.querySelectorAll('[data-site-disclosure][open]').forEach(function (other) { if (other !== opened) other.open = false; });
  }, true);
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'ArrowDown' || !(event.target instanceof Element)) return;
    var menu = event.target.closest('[data-site-disclosure]');
    if (!menu || event.target.tagName !== 'SUMMARY') return;
    event.preventDefault();
    menu.open = true;
    var first = menu.querySelector('a');
    if (first) first.focus();
  });
  window.addEventListener('storage', function (event) { if (event.key === key) apply(savedTheme()); });
})();
