// Saved radio stations + Radio-Browser search (web UI).
// Permanent stations are stored server-side (settings DB) and are usable
// via the !radio <name> chat command.

function postForm(url, data) {
  return fetch(url, {method: 'POST', body: new URLSearchParams(data)});
}

function sanitizeStationName(name, fallback) {
  // Unicode-aware: keep letters (äöü...), numbers, spaces and punctuation.
  // Only strip control characters and angle brackets (which would break
  // Mumble chat HTML), then truncate to the server-side 64-char limit.
  const clean = (name || '')
      .replace(/[\x00-\x1f\x7f<>]/g, '')
      .trim()
      .slice(0, 64);
  if (clean) return clean;
  return fallback || 'station';
}

export function initRadio() {
  const savedList = document.getElementById('radio-saved-list');
  const savedEmpty = document.getElementById('radio-saved-empty');
  const saveName = document.getElementById('radio-save-name');
  const saveUrl = document.getElementById('radio-save-url');
  const saveBtn = document.getElementById('radio-save-btn');
  const saveError = document.getElementById('radio-save-error');
  const playUrlInput = document.getElementById('radio-url-input');
  const queryInput = document.getElementById('radiobrowser-query');
  const searchBtn = document.getElementById('radiobrowser-search-btn');
  const resultsDiv = document.getElementById('radiobrowser-results');

  if (!savedList || !saveBtn) return; // radio card not present

  function showSaveError(msg) {
    if (!saveError) return;
    saveError.textContent = msg;
    saveError.style.display = msg ? '' : 'none';
  }

  function playUrl(url, name) {
    const data = {add_radio: url};
    if (name) data.add_radio_name = name;
    postForm('post', data);
  }

  function renderEditForm(li, st) {
    li.textContent = '';
    li.className = 'list-group-item';

    const form = document.createElement('div');
    form.className = 'd-flex flex-column gap-2 w-100';

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'form-control form-control-sm';
    nameInput.value = st.name;
    nameInput.maxLength = 64;
    nameInput.setAttribute('aria-label', 'Station name');
    form.appendChild(nameInput);

    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.className = 'form-control form-control-sm';
    urlInput.value = st.url;
    urlInput.setAttribute('aria-label', 'Station URL');
    form.appendChild(urlInput);

    const btnRow = document.createElement('div');
    btnRow.className = 'btn-group btn-group-sm';
    const okBtn = document.createElement('button');
    okBtn.type = 'button';
    okBtn.className = 'btn btn-success';
    okBtn.textContent = '✓ Save';
    okBtn.addEventListener('click', () => {
      renameStation(st.name, nameInput.value.trim(), urlInput.value.trim());
    });
    btnRow.appendChild(okBtn);
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => refreshSaved());
    btnRow.appendChild(cancelBtn);
    form.appendChild(btnRow);

    li.appendChild(form);
    nameInput.focus();
    nameInput.select();
  }

  function renderSaved(stations) {
    savedList.textContent = '';
    if (!stations || !stations.length) {
      if (savedEmpty) savedEmpty.style.display = '';
      return;
    }
    if (savedEmpty) savedEmpty.style.display = 'none';
    for (const st of stations) {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-center';

      const info = document.createElement('div');
      const nameEl = document.createElement('strong');
      nameEl.textContent = st.name;
      info.appendChild(nameEl);
      const badge = document.createElement('span');
      badge.className = 'badge ms-2 ' + (st.source === 'db' ? 'bg-success' : 'bg-secondary');
      badge.textContent = st.source;
      info.appendChild(badge);
      const urlEl = document.createElement('div');
      urlEl.className = 'text-muted small';
      urlEl.textContent = st.comment ? st.comment + ' (' + st.url + ')' : st.url;
      info.appendChild(urlEl);
      li.appendChild(info);

      const btnGroup = document.createElement('div');
      btnGroup.className = 'btn-group btn-group-sm';
      const playBtn = document.createElement('button');
      playBtn.type = 'button';
      playBtn.className = 'btn btn-info';
      playBtn.textContent = '▶';
      playBtn.title = 'Play';
      playBtn.setAttribute('aria-label', 'Play ' + st.name);
      playBtn.addEventListener('click', () => playUrl(st.url, st.name));
      btnGroup.appendChild(playBtn);
      if (st.source === 'db') {
        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'btn btn-secondary';
        editBtn.textContent = '✎';
        editBtn.title = 'Rename';
        editBtn.setAttribute('aria-label', 'Rename ' + st.name);
        editBtn.addEventListener('click', () => renderEditForm(li, st));
        btnGroup.appendChild(editBtn);
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-danger';
        delBtn.textContent = '✕';
        delBtn.title = 'Delete';
        delBtn.setAttribute('aria-label', 'Delete ' + st.name);
        delBtn.addEventListener('click', () => deleteStation(st.name));
        btnGroup.appendChild(delBtn);
      }
      li.appendChild(btnGroup);
      savedList.appendChild(li);
    }
  }

  function refreshSaved() {
    fetch('radio')
        .then((r) => (r.status === 200 ? r.json() : null))
        .then((data) => {
          if (data && data.stations) renderSaved(data.stations);
        });
  }

  function saveStation(name, url) {
    showSaveError('');
    return postForm('radio', {action: 'add', name, url})
        .then((r) => r.json().then((data) => ({status: r.status, data})))
        .then(({status, data}) => {
          if (status !== 200) {
            showSaveError((data && data.error) || 'Could not save station.');
            return;
          }
          if (saveName) saveName.value = '';
          if (saveUrl) saveUrl.value = '';
          renderSaved(data.stations);
        });
  }

  function renameStation(oldName, newName, url) {
    showSaveError('');
    if (!newName) {
      showSaveError('Name is required.');
      return Promise.resolve();
    }
    return postForm('radio', {action: 'rename', old_name: oldName, new_name: newName, url})
        .then((r) => r.json().then((data) => ({status: r.status, data})))
        .then(({status, data}) => {
          if (status !== 200) {
            showSaveError((data && data.error) || 'Could not rename station.');
            return;
          }
          renderSaved(data.stations);
        });
  }

  function deleteStation(name) {
    showSaveError('');
    postForm('radio', {action: 'delete', name})
        .then((r) => r.json().then((data) => ({status: r.status, data})))
        .then(({status, data}) => {
          if (status !== 200) {
            showSaveError((data && data.error) || 'Could not delete station.');
            return;
          }
          renderSaved(data.stations);
        });
  }

  saveBtn.addEventListener('click', () => {
    const url = (saveUrl && saveUrl.value.trim()) ||
        (playUrlInput && playUrlInput.value.trim()) || '';
    saveStation(saveName.value.trim(), url);
  });

  function renderBrowserResults(stations) {
    resultsDiv.textContent = '';
    if (!stations.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = 'No matches.';
      resultsDiv.appendChild(empty);
      return;
    }
    for (const st of stations) {
      const item = document.createElement('div');
      item.className = 'list-group-item';
      const title = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = st.name || '(unknown)';
      title.appendChild(strong);
      const meta = document.createElement('span');
      meta.className = 'text-muted small ms-2';
      meta.textContent = [st.codec, st.bitrate, st.countrycode].filter(Boolean).join(' / ');
      title.appendChild(meta);
      item.appendChild(title);
      if (st.tags) {
        const tags = document.createElement('div');
        tags.className = 'text-muted small';
        tags.textContent = st.tags;
        item.appendChild(tags);
      }
      const btnGroup = document.createElement('div');
      btnGroup.className = 'btn-group btn-group-sm mt-1';
      const playBtn = document.createElement('button');
      playBtn.type = 'button';
      playBtn.className = 'btn btn-info';
      playBtn.textContent = '▶ Play';
      playBtn.disabled = !st.url;
      playBtn.addEventListener('click', () => playUrl(st.url, st.name));
      btnGroup.appendChild(playBtn);
      const saveBtnEl = document.createElement('button');
      saveBtnEl.type = 'button';
      saveBtnEl.className = 'btn btn-secondary';
      saveBtnEl.textContent = '+ Save';
      saveBtnEl.disabled = !st.url;
      saveBtnEl.addEventListener('click', () => {
        const suggestion = sanitizeStationName(st.name, (st.stationuuid || 'station').slice(0, 8));
        // Prefill the save form so the user can adjust the name, then save.
        if (saveName) saveName.value = suggestion;
        if (saveUrl) saveUrl.value = st.url;
        if (saveName) saveName.focus();
        saveStation(suggestion, st.url);
      });
      btnGroup.appendChild(saveBtnEl);
      item.appendChild(btnGroup);
      resultsDiv.appendChild(item);
    }
  }

  function searchBrowser() {
    const q = (queryInput.value || '').trim();
    if (!q) return;
    searchBtn.disabled = true;
    resultsDiv.textContent = '';
    const loading = document.createElement('div');
    loading.className = 'text-muted small';
    loading.textContent = 'Searching...';
    resultsDiv.appendChild(loading);
    fetch('radiobrowser/search?' + new URLSearchParams({q, limit: '20'}))
        .then((r) => r.json().then((data) => ({status: r.status, data})))
        .then(({status, data}) => {
          searchBtn.disabled = false;
          if (status !== 200) {
            resultsDiv.textContent = '';
            const err = document.createElement('div');
            err.className = 'text-danger small';
            err.textContent = (data && data.error) || 'Search failed.';
            resultsDiv.appendChild(err);
            return;
          }
          renderBrowserResults(data.stations || []);
        })
        .catch(() => {
          searchBtn.disabled = false;
          resultsDiv.textContent = '';
          const err = document.createElement('div');
          err.className = 'text-danger small';
          err.textContent = 'Search failed.';
          resultsDiv.appendChild(err);
        });
  }

  if (searchBtn) {
    searchBtn.addEventListener('click', searchBrowser);
  }
  if (queryInput) {
    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        searchBrowser();
      }
    });
  }

  refreshSaved();
}
