(() => {
  const panel = document.getElementById('database-panel');
  if (!panel) return;
  const table = document.getElementById('db-table');
  const size = document.getElementById('db-page-size');
  const refresh = document.getElementById('db-refresh');
  const previous = document.getElementById('db-previous');
  const next = document.getElementById('db-next');
  const status = document.getElementById('db-status');
  const grid = document.getElementById('db-grid');
  const summary = document.getElementById('db-summary');
  const pageLabel = document.getElementById('db-page');
  let page = 1, pages = 1, controller;

  async function request(url, signal) {
    const response = await fetch(url, {signal, cache: 'no-store'});
    if (response.redirected) throw new Error('Your session has expired. Please sign in again.');
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Unable to load database. Please check your access and try again.');
    return data;
  }
  function setStatus(message, error = false) {
    status.textContent = message;
    status.dataset.error = String(error);
    status.hidden = !message;
  }
  function cell(tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  async function load(target = 1) {
    if (!table.value) return;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    previous.disabled = next.disabled = refresh.disabled = true;
    grid.setAttribute('aria-busy', 'true');
    grid.hidden = true;
    summary.textContent = pageLabel.textContent = '';
    setStatus('Loading records…');
    const url = new URL(panel.dataset.tableUrl, location.origin);
    url.search = new URLSearchParams({name: table.value, page: target, page_size: size.value});
    try {
      const data = await request(url, signal);
      if (signal.aborted) return;
      const head = document.createElement('tr');
      for (const column of data.columns) {
        const th = cell('th', column.name);
        th.scope = 'col';
        th.append(cell('span', [column.type || 'ANY', column.primary_key ? 'PK' : ''].filter(Boolean).join(' · '), 'db-column-type'));
        head.append(th);
      }
      document.getElementById('db-head').replaceChildren(head);
      const body = document.createDocumentFragment();
      for (const row of data.rows) {
        const tr = document.createElement('tr');
        row.forEach((value, index) => {
          const td = document.createElement('td');
          const hidden = data.columns[index].hidden;
          let text = hidden ? 'Hidden' : value === null ? 'NULL' : String(value);
          if (typeof value === 'string' && text.length > data.cell_limit) text = text.slice(0, data.cell_limit) + '…';
          td.append(cell('span', text, 'db-value' + (hidden || value === null ? ' db-muted' : '')));
          tr.append(td);
        });
        body.append(tr);
      }
      document.getElementById('db-body').replaceChildren(body);
      page = data.page;
      pages = data.pages;
      grid.hidden = false;
      grid.scrollTop = grid.scrollLeft = 0;
      summary.textContent = data.total ? `${(page - 1) * data.page_size + 1}–${Math.min(page * data.page_size, data.total)} of ${data.total} rows` : '0 rows';
      pageLabel.textContent = `${page} / ${pages}`;
      previous.disabled = page <= 1;
      next.disabled = page >= pages;
      setStatus(data.rows.length ? '' : 'This table is empty.');
    } catch (error) {
      if (!signal.aborted) setStatus(error.message, true);
    } finally {
      if (!signal.aborted) {
        refresh.disabled = false;
        grid.setAttribute('aria-busy', 'false');
      }
    }
  }
  table.addEventListener('change', () => load());
  size.addEventListener('change', () => load());
  previous.addEventListener('click', () => load(page - 1));
  next.addEventListener('click', () => load(page + 1));
  refresh.addEventListener('click', async () => {
    if (table.options.length) return load(page);
    await initialize();
  });
  async function initialize() {
    try {
      refresh.disabled = true;
      setStatus('Loading tables…');
      const data = await request(panel.dataset.tablesUrl);
      table.replaceChildren(...data.tables.map(name => new Option(name, name)));
      table.disabled = !data.tables.length;
      if (data.tables.length) await load();
      else setStatus('No tables found.');
    } catch (error) {
      table.replaceChildren();
      setStatus(error.message, true);
    } finally {
      refresh.disabled = false;
    }
  }
  initialize();
})();
