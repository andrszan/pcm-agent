(() => {
  const drawer = document.querySelector('#main-drawer');
  const drawerTrigger = document.querySelector('#menu-trigger');
  const drawerClose = document.querySelector('#menu-close');
  const tabs = [...document.querySelectorAll('[role="tab"]')];

  const activateTab = (tab) => {
    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute('aria-selected', String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      document.getElementById(candidate.getAttribute('aria-controls')).hidden = !selected;
    });
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', (event) => {
      let nextIndex = null;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') nextIndex = 0;
      if (event.key === 'End') nextIndex = tabs.length - 1;

      if (nextIndex !== null) {
        event.preventDefault();
        tabs[nextIndex].focus();
        activateTab(tabs[nextIndex]);
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        activateTab(tab);
      }
    });
  });

  document.querySelectorAll('[data-primary-nav]').forEach((item) => {
    item.addEventListener('click', (event) => {
      event.preventDefault();
      const selected = item.dataset.primaryNav;
      document.querySelectorAll('[data-primary-nav]').forEach((link) => {
        link.toggleAttribute('aria-current', link.dataset.primaryNav === selected);
        if (link.dataset.primaryNav === selected) link.setAttribute('aria-current', 'page');
      });
      if (drawer.open) drawer.close();
    });
  });

  drawerTrigger.addEventListener('click', () => {
    drawerTrigger.setAttribute('aria-expanded', 'true');
    drawer.showModal();
  });

  drawerClose.addEventListener('click', () => drawer.close());
  drawer.addEventListener('click', (event) => {
    if (event.target === drawer) drawer.close();
  });
  drawer.addEventListener('close', () => {
    drawerTrigger.setAttribute('aria-expanded', 'false');
    drawerTrigger.focus();
  });
})();
