(() => {
  const shell = document.querySelector('#app-shell');
  const sidebarToggle = document.querySelector('#sidebar-toggle');
  const filterToggle = document.querySelector('#filter-toggle');
  const filterPanel = document.querySelector('#filter-panel');
  const drawer = document.querySelector('#sidebar-drawer');
  const drawerTrigger = document.querySelector('#drawer-trigger');
  const drawerClose = document.querySelector('#drawer-close');

  const toggleSection = (button) => {
    const section = document.getElementById(button.getAttribute('aria-controls'));
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    section.hidden = expanded;
  };

  sidebarToggle.addEventListener('click', () => {
    const collapsed = shell.classList.toggle('sidebar-collapsed');
    sidebarToggle.setAttribute('aria-pressed', String(collapsed));
    sidebarToggle.setAttribute('aria-label', collapsed ? '退出紧凑侧边栏' : '使用紧凑侧边栏');
  });

  [document.querySelector('#library-toggle'), document.querySelector('#drawer-library-toggle')]
    .forEach((button) => button.addEventListener('click', () => toggleSection(button)));

  filterToggle.addEventListener('click', () => {
    const expanded = filterToggle.getAttribute('aria-expanded') === 'true';
    filterToggle.setAttribute('aria-expanded', String(!expanded));
    filterToggle.textContent = expanded ? '展开筛选' : '收起筛选';
    filterPanel.hidden = expanded;
  });

  document.querySelectorAll('[data-nav-item]').forEach((item) => {
    item.addEventListener('click', (event) => {
      event.preventDefault();
      const selected = item.dataset.navItem;
      document.querySelectorAll('[data-nav-item]').forEach((link) => {
        link.toggleAttribute('aria-current', link.dataset.navItem === selected);
        if (link.dataset.navItem === selected) link.setAttribute('aria-current', 'page');
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
