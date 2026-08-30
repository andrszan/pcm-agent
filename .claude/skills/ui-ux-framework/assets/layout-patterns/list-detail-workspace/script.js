(() => {
  const shell = document.querySelector('#workspace-shell');
  const listPane = document.querySelector('#list-pane');
  const detailPane = document.querySelector('#detail-pane');
  const items = [...document.querySelectorAll('.request-item[aria-controls]')];
  const details = [...document.querySelectorAll('.detail-view')];
  const mobileView = window.matchMedia('(max-width: 760px)');

  const getControlledDetail = (item) => {
    const detail = document.getElementById(item.getAttribute('aria-controls'));
    const titleId = detail?.getAttribute('aria-labelledby');
    const title = titleId ? document.getElementById(titleId) : null;

    if (!detail?.matches('.detail-view') || !title || !detail.contains(title) || title.getAttribute('tabindex') !== '-1') {
      return null;
    }

    return { detail, title };
  };

  const selectItem = (item) => {
    const target = getControlledDetail(item);
    if (!target) return;

    shell.dataset.listScrollTop = String(listPane.scrollTop);
    items.forEach((candidate) => candidate.setAttribute('aria-pressed', String(candidate === item)));
    details.forEach((detail) => { detail.hidden = detail !== target.detail; });
    shell.dataset.mobileView = 'detail';
    detailPane.scrollTop = 0;

    if (mobileView.matches) target.title.focus({ preventScroll: true });
  };

  const returnToList = () => {
    const selectedItem = items.find((item) => item.getAttribute('aria-pressed') === 'true');
    const storedScrollTop = Number(shell.dataset.listScrollTop);
    const scrollTop = Number.isFinite(storedScrollTop) && storedScrollTop >= 0 ? storedScrollTop : 0;

    shell.dataset.mobileView = 'list';
    listPane.scrollTop = scrollTop;
    if (selectedItem) selectedItem.focus({ preventScroll: true });
  };

  items.forEach((item) => item.addEventListener('click', () => selectItem(item)));
  document.querySelectorAll('[data-return-to-list]')
    .forEach((button) => button.addEventListener('click', returnToList));
})();
