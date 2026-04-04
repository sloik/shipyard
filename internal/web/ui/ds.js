/* ==========================================================================
   Shipyard Design System — ds.js
   SPEC-005: Design System Runtime Library
   ========================================================================== */

(function() {
  'use strict';

  var DS = {};

  /* ========================================================================
     Theme Switching
     ======================================================================== */

  DS.theme = {
    /** Get the current theme ('dark' | 'light'). */
    current: function() {
      var explicit = document.documentElement.getAttribute('data-theme');
      if (explicit) return explicit;
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        return 'light';
      }
      return 'dark';
    },

    /** Set theme explicitly. */
    set: function(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      try { localStorage.setItem('ds-theme', theme); } catch(e) { /* ignore */ }
    },

    /** Toggle between dark and light. */
    toggle: function() {
      var next = DS.theme.current() === 'dark' ? 'light' : 'dark';
      DS.theme.set(next);
      return next;
    },

    /** Initialize theme from localStorage or system preference. */
    init: function() {
      var saved;
      try { saved = localStorage.getItem('ds-theme'); } catch(e) { /* ignore */ }
      if (saved === 'dark' || saved === 'light') {
        DS.theme.set(saved);
      }
      // else: no data-theme set, CSS prefers-color-scheme handles auto-detect
    }
  };

  /* ========================================================================
     Toast System
     ======================================================================== */

  var toastContainer = null;

  function ensureToastContainer() {
    if (toastContainer && toastContainer.parentNode) return toastContainer;
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
    return toastContainer;
  }

  /**
   * Show a toast notification.
   * @param {string} message - Text to display.
   * @param {string} [type='info'] - 'success' | 'error' | 'info'
   * @param {number} [duration=3000] - Auto-dismiss time in ms.
   */
  DS.toast = function(message, type, duration) {
    type = type || 'info';
    duration = duration || 3000;

    var container = ensureToastContainer();
    var el = document.createElement('div');
    el.className = 'toast toast-' + type;

    var icons = { success: '\u2713', error: '\u2716', info: '\u24D8' };
    el.textContent = (icons[type] || '') + ' ' + message;

    el.addEventListener('click', function() { dismiss(el); });

    container.appendChild(el);

    var timer = setTimeout(function() { dismiss(el); }, duration);

    function dismiss(toast) {
      clearTimeout(timer);
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(8px)';
      toast.style.transition = 'opacity 0.15s, transform 0.15s';
      setTimeout(function() {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 150);
    }
  };

  /* ========================================================================
     Modal System
     ======================================================================== */

  /**
   * Show a modal dialog.
   * @param {string} title - Modal title.
   * @param {string} body - Modal body (HTML string or plain text).
   * @param {Array<{label: string, value: string, className?: string}>} actions - Buttons.
   * @returns {Promise<string>} Resolves with the clicked action's value, or '' on dismiss.
   */
  DS.modal = function(title, body, actions) {
    return new Promise(function(resolve) {
      var backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop';

      var modal = document.createElement('div');
      modal.className = 'modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');

      var header = document.createElement('div');
      header.className = 'modal-header';
      header.textContent = title;

      var bodyEl = document.createElement('div');
      bodyEl.className = 'modal-body';
      bodyEl.innerHTML = body;

      var actionsEl = document.createElement('div');
      actionsEl.className = 'modal-actions';

      (actions || []).forEach(function(action) {
        var btn = document.createElement('button');
        btn.className = 'btn ' + (action.className || 'btn-default');
        btn.textContent = action.label;
        btn.addEventListener('click', function() { close(action.value); });
        actionsEl.appendChild(btn);
      });

      modal.appendChild(header);
      modal.appendChild(bodyEl);
      modal.appendChild(actionsEl);
      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);

      // Focus trap
      var focusableSelector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
      var firstFocusable = modal.querySelector(focusableSelector);
      if (firstFocusable) firstFocusable.focus();

      function trapFocus(e) {
        if (e.key !== 'Tab') return;
        var focusable = modal.querySelectorAll(focusableSelector);
        if (focusable.length === 0) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }

      function onKeydown(e) {
        if (e.key === 'Escape') { close(''); }
        trapFocus(e);
      }

      backdrop.addEventListener('click', function(e) {
        if (e.target === backdrop) close('');
      });

      document.addEventListener('keydown', onKeydown);

      function close(value) {
        document.removeEventListener('keydown', onKeydown);
        if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
        resolve(value);
      }
    });
  };

  /* ========================================================================
     Copy to Clipboard
     ======================================================================== */

  function handleCopy(el) {
    var text = el.getAttribute('data-copy');
    if (!text) {
      // Try to find sibling .json-viewer content
      var viewer = el.closest('.code-block, .json-viewer, .split-view');
      if (!viewer) viewer = el.parentNode;
      var jv = viewer ? viewer.querySelector('.json-viewer') : null;
      if (jv) text = jv.textContent;
    }
    if (!text) return;

    navigator.clipboard.writeText(text).then(function() {
      var origClass = el.className;
      el.className = el.className.replace(/\bbtn-copy\b/, 'btn-copied');
      if (el.className === origClass) {
        // btn-copy wasn't present, just add btn-copied
        el.classList.add('btn-copied');
      }
      setTimeout(function() {
        el.className = origClass;
      }, 2000);
    }).catch(function() {
      /* clipboard write failed — silently ignore */
    });
  }

  /* ========================================================================
     Segmented Toggle
     ======================================================================== */

  function handleSegToggle(el, target) {
    var siblings = el.querySelectorAll('.seg-active, .seg-inactive, [role="tab"]');
    for (var i = 0; i < siblings.length; i++) {
      siblings[i].classList.remove('seg-active');
      siblings[i].classList.add('seg-inactive');
    }
    target.classList.remove('seg-inactive');
    target.classList.add('seg-active');

    var event = new CustomEvent('change', {
      bubbles: true,
      detail: { value: target.getAttribute('data-value') || target.textContent.trim() }
    });
    el.dispatchEvent(event);
  }

  /* ========================================================================
     Switch Toggle
     ======================================================================== */

  function handleSwitch(el) {
    el.classList.toggle('is-on');
    var event = new CustomEvent('change', {
      bubbles: true,
      detail: { value: el.classList.contains('is-on') }
    });
    el.dispatchEvent(event);
  }

  /* ========================================================================
     Row Expand/Collapse
     ======================================================================== */

  function handleRowChevron(chevron) {
    var isExpanded = chevron.classList.toggle('is-expanded');
    var row = chevron.closest('.table-row');
    if (row) {
      row.classList.toggle('row-expanded', isExpanded);
      // Find the next sibling detail panel
      var next = row.nextElementSibling;
      if (next && next.classList.contains('detail-panel')) {
        next.classList.toggle('is-visible', isExpanded);
      }
    }
  }

  /* ========================================================================
     Resize Handle
     ======================================================================== */

  function initResizeHandle(handle) {
    handle.addEventListener('mousedown', function(e) {
      e.preventDefault();
      var panel = handle.previousElementSibling;
      if (!panel) return;

      var startY = e.clientY;
      var startHeight = panel.offsetHeight;
      var maxH = window.innerHeight * 0.8;
      var minH = 100;

      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';

      function onMove(ev) {
        var delta = ev.clientY - startY;
        var newH = Math.min(maxH, Math.max(minH, startHeight + delta));
        panel.style.height = newH + 'px';
      }

      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  /* ========================================================================
     Tool Group Collapse
     ======================================================================== */

  function handleToolGroupClick(header) {
    var group = header.closest('.tool-group');
    if (!group) return;
    group.classList.toggle('is-collapsed');
  }

  /* ========================================================================
     JSON Filter
     ======================================================================== */

  function handleJsonFilter(filterInput) {
    var container = filterInput.closest('.json-filter');
    if (!container) return;

    // Find associated viewer(s)
    var scope = container.closest('.split-view') || container.parentNode;
    var viewers = scope ? scope.querySelectorAll('.json-viewer') : [];

    var query = filterInput.value.trim();
    var isPanelFilter = container.classList.contains('panel-filter');
    var isJqMode = false;

    // Check for JQ mode toggle sibling
    var modeToggle = container.parentNode ? container.parentNode.querySelector('.mode-toggle .is-active') : null;
    if (modeToggle && modeToggle.textContent.trim().toLowerCase() === 'jq') {
      isJqMode = true;
    }

    for (var v = 0; v < viewers.length; v++) {
      var viewer = viewers[v];
      if (!query) {
        // Restore original content
        if (viewer._dsOriginal) {
          viewer.innerHTML = viewer._dsOriginal;
          viewer._dsOriginal = null;
        }
        continue;
      }

      // Save original HTML on first filter
      if (!viewer._dsOriginal) {
        viewer._dsOriginal = viewer.innerHTML;
      }

      if (isJqMode) {
        // Basic JQ path evaluation: .key.subkey
        try {
          var rawText = viewer.textContent;
          var obj = JSON.parse(rawText);
          var path = query.replace(/^\./, '').split('.');
          var result = obj;
          for (var p = 0; p < path.length; p++) {
            if (path[p] === '') continue;
            if (result == null) break;
            result = result[path[p]];
          }
          viewer.textContent = JSON.stringify(result, null, 2);
        } catch(e) {
          // Invalid path — show error inline
          viewer.textContent = 'Error: ' + e.message;
        }
      } else {
        // Text search: highlight matching substrings
        var original = viewer._dsOriginal;
        var escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        var re = new RegExp('(' + escaped + ')', 'gi');
        // Work on text content to avoid breaking HTML tags
        var text = viewer.textContent;
        viewer.innerHTML = text.replace(re, '<mark style="background:var(--warning-subtle);color:var(--warning-fg)">$1</mark>');
      }
    }
  }

  /* ========================================================================
     Search Bar
     ======================================================================== */

  function handleSearchBar(input) {
    var bar = input.closest('.search-bar');
    if (!bar) return;
    var hasValue = input.value.trim().length > 0;
    bar.classList.toggle('is-active', hasValue);
  }

  function handleSearchClear(btn) {
    var bar = btn.closest('.search-bar');
    if (!bar) return;
    var input = bar.querySelector('input');
    if (input) {
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }
    bar.classList.remove('is-active');
  }

  /* ========================================================================
     Event Delegation (single listener on document)
     ======================================================================== */

  document.addEventListener('click', function(e) {
    var target = e.target;

    // Copy to clipboard: [data-copy] or .btn-copy
    var copyEl = target.closest('[data-copy], .btn-copy');
    if (copyEl) {
      e.preventDefault();
      handleCopy(copyEl);
      return;
    }

    // Segmented toggle
    var segParent = target.closest('.seg-toggle');
    if (segParent) {
      var segChild = target.closest('.seg-active, .seg-inactive, [role="tab"], button');
      if (segChild && segParent.contains(segChild)) {
        handleSegToggle(segParent, segChild);
        return;
      }
    }

    // Switch toggle
    var switchEl = target.closest('.switch');
    if (switchEl) {
      handleSwitch(switchEl);
      return;
    }

    // Row chevron
    var chevron = target.closest('.row-chevron');
    if (chevron) {
      e.stopPropagation();
      handleRowChevron(chevron);
      return;
    }

    // Tool group header
    var toolHeader = target.closest('.tool-group-header');
    if (toolHeader) {
      handleToolGroupClick(toolHeader);
      return;
    }

    // Theme toggle
    var themeBtn = target.closest('.theme-toggle');
    if (themeBtn) {
      DS.theme.toggle();
      return;
    }

    // Search clear
    var clearBtn = target.closest('.search-clear');
    if (clearBtn) {
      handleSearchClear(clearBtn);
      return;
    }
  });

  // Input events (for filters and search)
  document.addEventListener('input', function(e) {
    var target = e.target;

    // JSON filter
    var jsonFilter = target.closest('.json-filter');
    if (jsonFilter && target.tagName === 'INPUT') {
      handleJsonFilter(target);
      return;
    }

    // Search bar
    var searchBar = target.closest('.search-bar');
    if (searchBar && target.tagName === 'INPUT') {
      handleSearchBar(target);
      return;
    }
  });

  // Initialize resize handles
  function initResizeHandles() {
    var handles = document.querySelectorAll('.resize-handle');
    for (var i = 0; i < handles.length; i++) {
      if (!handles[i]._dsInit) {
        initResizeHandle(handles[i]);
        handles[i]._dsInit = true;
      }
    }
  }

  /* ========================================================================
     Initialization
     ======================================================================== */

  function init() {
    DS.theme.init();
    initResizeHandles();

    // Observe DOM for dynamically added resize handles
    if (typeof MutationObserver !== 'undefined') {
      var observer = new MutationObserver(function() {
        initResizeHandles();
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  // Run init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose DS namespace
  window.DS = DS;

})();
