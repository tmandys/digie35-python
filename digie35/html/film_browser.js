/* Compact, film-scoped capture browser. All filenames are rendered as text. */
const filmBrowser = {
    selected: new Set(), files: [], context: '', signature: '', pending: null,
    sortKey: 'name', sortDirection: 'asc',
    el(id) { return document.getElementById(id); },
    size(value) { return value == null ? 'Camera only' : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`; },
    info(file) {
        return `${file.name}\n${this.size(file.size)}\n${file.modified ? new Date(file.modified * 1000).toLocaleString() : ''}\nRAW XMP: ${file.xmp ? 'Yes' : 'No'} · Preview JSON: ${file.preview_json ? 'Yes' : 'No'}\nPreview: ${file.preview ? 'Yes' : 'No'}`;
    },
    imageName(file) { return `${this.project}/${this.film}/${file.name}`; },
    update(files) {
        if (this.pending && window.control_socket?.readyState !== 1) {
            const action = this.pending.action || 'delete';
            this.pending = null;
            this.el(`film-${action}-status`).textContent = 'Connection lost. The result is unknown; refresh the film before trying again.';
        }
        const project = this.el('project_id').value, film = this.el('film_id').value;
        const context = JSON.stringify([window.current_volume, project, film]);
        if (context !== this.context) this.selected.clear();
        this.context = context; this.project = project; this.film = film; this.files = files;
        this.selected = new Set([...this.selected].filter(name => files.some(file => file.name === name)));
        if (!this.initialized) {
            try { this.el('film-view').value = localStorage.getItem('film.view') || 'thumbnails'; } catch (_) {}
            if (!this.el('film-view').value) this.el('film-view').value = 'thumbnails';
            try {
                const key = localStorage.getItem('film.sort.key'), direction = localStorage.getItem('film.sort.direction');
                if (['name', 'modified'].includes(key)) this.sortKey = key;
                if (['asc', 'desc'].includes(direction)) this.sortDirection = direction;
            } catch (_) {}
            this.initialized = true;
        }
        const signature = JSON.stringify([context, files]);
        if (signature !== this.signature) { this.signature = signature; this.render(); }
        this.actions();
    },
    actions() {
        this.el('film-selection').textContent = `${this.files.length} images · ${this.selected.size} selected`;
        this.el('film-delete').disabled = !this.selected.size || !!this.pending || !!window.camera_capture_in_progress || !!window.download_in_progress || window.control_socket?.readyState !== 1;
        this.el('film-move').disabled = this.el('film-delete').disabled;
        this.el('film-clear').disabled = !this.selected.size;
    },
    clear() { this.selected.clear(); this.render(); },
    changeView() {
        try { localStorage.setItem('film.view', this.el('film-view').value); } catch (_) {}
        this.render();
    },
    sortBy(key) {
        this.sortDirection = this.sortKey === key ? (this.sortDirection === 'asc' ? 'desc' : 'asc') : (key === 'modified' ? 'desc' : 'asc');
        this.sortKey = key;
        try {
            localStorage.setItem('film.sort.key', key);
            localStorage.setItem('film.sort.direction', this.sortDirection);
        } catch (_) {}
        this.render();
    },
    orderedFiles() {
        const direction = this.sortDirection === 'desc' ? -1 : 1;
        return [...this.files].sort((a, b) => {
            const name = a.name.localeCompare(b.name, undefined, {numeric: true});
            if (this.sortKey === 'name') return direction * name;
            const aValid = Number.isFinite(a.modified), bValid = Number.isFinite(b.modified);
            if (aValid !== bValid) return aValid ? -1 : 1;
            return (aValid ? direction * (a.modified - b.modified) : 0) || name;
        });
    },
    render() {
        const view = this.el('film-view').value, container = this.el('capture-list');
        container.replaceChildren(); container.className = `film-files film-${view}`;
        const make = (tag, text, cls) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; };
        let parent = container;
        if (view === 'details') {
            const table = make('table'), header = make('tr'), head = make('thead');
            for (const [label, key] of [['', null], ['Filename', 'name'], ['Size / location', null], ['Modified', 'modified'], ['XMP', null], ['Preview JSON', null]]) {
                const cell = make('th');
                if (key) {
                    const active = this.sortKey === key;
                    cell.setAttribute('aria-sort', active ? (this.sortDirection === 'asc' ? 'ascending' : 'descending') : 'none');
                    const button = make('button', label + (active ? (this.sortDirection === 'asc' ? ' ↑' : ' ↓') : ' ↕'), 'film-sort');
                    button.type = 'button'; button.dataset.sort = key;
                    button.title = key === 'modified' ? 'Sort by file modification date; click again to reverse' : 'Sort by filename; click again to reverse';
                    button.onclick = () => this.sortBy(key); cell.append(button);
                } else cell.textContent = label;
                header.append(cell);
            }
            head.append(header); parent = make('tbody'); table.append(head, parent); container.append(table);
        }
        for (const file of this.orderedFiles()) {
            const row = make(view === 'details' ? 'tr' : 'div', null, 'film-item');
            row.classList.toggle('selected', this.selected.has(file.name)); row.title = this.info(file);
            const checkbox = make('input'); checkbox.type = 'checkbox'; checkbox.checked = this.selected.has(file.name);
            checkbox.setAttribute('aria-label', `Select ${file.name}`);
            checkbox.onchange = () => { if (checkbox.checked) this.selected.add(file.name); else this.selected.delete(file.name); row.classList.toggle('selected', checkbox.checked); this.actions(); };
            const open = make(file.preview ? 'button' : 'span', view === 'thumbnails' ? null : file.name, 'film-open');
            if (file.preview) {
                open.type = 'button';
                open.setAttribute('aria-label', `Open ${file.name}`);
                open.onclick = () => show_lightbox(this.imageName(file));
            }
            if (view === 'thumbnails') {
                const placeholder = make('span', '▧ No preview', 'film-placeholder'); open.append(placeholder);
                if (file.preview) {
                    const img = make('img'); img.alt = ''; img.loading = 'lazy';
                    img.src = get_stream_url(true, `preview/archive/${this.imageName(file).split('/').map(encodeURIComponent).join('/')}`);
                    img.onload = () => { placeholder.hidden = true; }; img.onerror = () => { img.remove(); placeholder.hidden = false; };
                    open.append(img);
                }
            }
            const info = make('button', 'ⓘ', 'film-info'); info.type = 'button'; info.title = this.info(file);
            info.setAttribute('aria-label', `Details for ${file.name}`); info.onclick = () => this.details(file);
            if (view === 'details') {
                const selectCell = make('td'); selectCell.append(checkbox); const nameCell = make('td'); nameCell.append(open);
                row.append(selectCell, nameCell, make('td', this.size(file.size)), make('td', file.modified ? new Date(file.modified * 1000).toLocaleString() : '—'), make('td', file.xmp ? '✓' : '—'), make('td', file.preview_json ? '✓' : '—'));
            } else {
                row.append(checkbox, open);
                if (view === 'list') row.append(make('span', `${this.size(file.size)}${file.xmp ? ' · XMP' : ''}${file.preview_json ? ' · JSON' : ''}`, 'film-summary'));
                row.append(info);
            }
            parent.append(row);
        }
        if (!this.files.length) container.append(make('p', 'No images in this film.'));
        this.actions();
    },
    details(file) { this.el('film-file-info').textContent = this.info(file); show_modal('film-file-info-modal'); },
    askDelete() {
        this.deleteContext = {project_id: this.project, film_id: this.film, volume: window.current_volume, names: [...this.selected]};
        this.el('film-delete-names').textContent = this.deleteContext.names.join('\n');
        this.el('film-delete-status').textContent = '';
        this.el('film-delete-confirm').disabled = false;
        show_modal('film-delete-modal');
    },
    confirmDelete() {
        if (this.pending) return;
        if (window.control_socket?.readyState !== 1) { this.el('film-delete-status').textContent = 'Disconnected. Reconnect before deleting.'; return; }
        this.pending = {...this.deleteContext, request_id: `${Date.now()}-${Math.random().toString(36).slice(2)}`};
        this.el('film-delete-confirm').disabled = true;
        this.el('film-delete-status').textContent = 'Deleting…';
        sendCommand('DELETE_CAPTURES', [], this.pending); this.actions();
    },
    askMove() {
        this.moveContext = {project_id: this.project, film_id: this.film, volume: window.current_volume, names: [...this.selected]};
        const projects = this.el('film-move-project');
        projects.replaceChildren();
        this.moveProjects = [...this.el('project-list').options].filter(option => option.value && option._custom_data)
            .map(option => ({id: option.value, films: option._custom_data.film_list || []}));
        for (const project of this.moveProjects) projects.add(new Option(project.id, project.id));
        projects.value = this.project;
        this.el('film-move-names').textContent = this.moveContext.names.join('\n');
        this.el('film-move-status').textContent = '';
        this.moveProjectChanged();
        show_modal('film-move-modal');
    },
    moveProjectChanged() {
        const project = this.el('film-move-project').value, films = this.el('film-move-film');
        films.replaceChildren();
        films.add(new Option('Choose a film…', ''));
        for (const film of this.moveProjects.find(item => item.id === project)?.films || []) {
            if (project !== this.moveContext.project_id || film.id !== this.moveContext.film_id) films.add(new Option(film.id, film.id));
        }
        this.moveTargetChanged();
    },
    moveTargetChanged() { this.el('film-move-confirm').disabled = !!this.pending || !this.el('film-move-film').value; },
    confirmMove() {
        if (this.pending || !this.el('film-move-film').value) return;
        if (window.control_socket?.readyState !== 1) { this.el('film-move-status').textContent = 'Disconnected. Reconnect before moving.'; return; }
        this.pending = {...this.moveContext, action: 'move', target_project: this.el('film-move-project').value,
            target_film: this.el('film-move-film').value, request_id: `${Date.now()}-${Math.random().toString(36).slice(2)}`};
        this.el('film-move-confirm').disabled = true;
        this.el('film-move-status').textContent = 'Moving…';
        sendCommand('MOVE_CAPTURES', [], this.pending); this.actions();
    },
    receive(data) {
        if (data.cmd === 'GET_PROJECT' && data.payload?.id !== this.el('project_id').value) {
            const option = [...this.el('project-list').options].find(option => option.value === data.payload?.id);
            if (option && data.payload.film_list) option._custom_data = data.payload;
        }
        if (!['DELETE_CAPTURES', 'MOVE_CAPTURES'].includes(data.cmd)) return false;
        if (!this.pending || data.payload?.request_id !== this.pending.request_id) return true;
        const pending = this.pending; this.pending = null;
        if (!pending) return true;
        const action = pending.action || 'delete';
        const result = data.payload || {}, deleted = new Set(result.deleted || result.moved || []);
        if (this.context === JSON.stringify([pending.volume, pending.project_id, pending.film_id])) {
            const list = this.el('film-list');
            if (list.selectedIndex > 0) list.options[list.selectedIndex]._custom_data.captured = this.files.filter(file => !deleted.has(file.name));
            for (const name of deleted) this.selected.delete(name);
            adjust();
        }
        const errors = [result.error, ...Object.entries(result.errors || {}).map(([name, error]) => `${name}: ${error}`)].filter(Boolean);
        this.el(`film-${action}-status`).textContent = errors.join('\n');
        // Retry requires a fresh selection and confirmation after any partial deletion.
        if (!errors.length && get_modal()?.id === `film-${action}-modal`) close_modal();
        if (action === 'move') this.moveTargetChanged();
        if (pending.volume === window.current_volume) sendCommand('GET_PROJECT', [], {project_id: pending.project_id});
        if (action === 'move' && pending.target_project !== pending.project_id && pending.volume === window.current_volume) {
            // Refresh destination data without changing the user's active project.
            sendCommand('GET_PROJECT', [], {project_id: pending.target_project});
        }
        this.actions(); return true;
    },
    navigate(delta) {
        const available = this.orderedFiles().filter(file => file.preview);
        const index = available.findIndex(file => this.imageName(file) === this.el('archived-image-name').textContent);
        if (index + delta >= 0 && index + delta < available.length) show_lightbox(this.imageName(available[index + delta]));
    },
    navigation(imageName) {
        const available = this.orderedFiles().filter(file => file.preview), index = available.findIndex(file => this.imageName(file) === imageName);
        this.el('film-image-position').textContent = index < 0 ? '' : `${index + 1} / ${available.length}`;
        this.el('film-prev').disabled = index <= 0; this.el('film-next').disabled = index < 0 || index >= available.length - 1;
    }
};
document.addEventListener('keydown', event => {
    if (get_modal()?.id !== 'lightbox-modal' || event.altKey || event.ctrlKey || event.metaKey || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); event.stopImmediatePropagation(); filmBrowser.navigate(event.key === 'ArrowLeft' ? -1 : 1); }
}, true);
