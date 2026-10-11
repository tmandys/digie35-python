// Resolve preset selections to a hardware mode before controlling the light.
const ledPresets = {
    key: "control.backlight.ledPresets", modes: {
        "red+green+blue": "RGB", "white+red+green+blue": "RGB+White", "amber+white+red+green+blue": "RGBAW",
    },
    records: [], states: {}, state: null, light: null, lightKey: null, ready: false, epoch: 0,
    init() {
        const select = document.getElementById("backlight-color-list");
        this.baseOptions = Array.from(select.options);
        for (const option of this.baseOptions) option.dataset.baseLabel = option.text;
        try {this.states = JSON.parse(localStorage.getItem(this.key) || "{}");} catch {this.states = {};}
        if (!this.states || typeof this.states !== "object" || Array.isArray(this.states)) this.states = {};
    },
    identity(light) {
        return JSON.stringify(["adapter_class", "adapter_id", "board_id", "version", "serial_number"].map(k => light[k] ?? null));
    },
    readSettings(mode) {
        const gains = {}, enabled = {};
        if (this.modes[mode]) for (const channel of mode.split("+")) {
            gains[channel] = Number(document.getElementById(`backlight-${channel}-num`).value);
            enabled[channel] = document.getElementById(`backlight-${channel}-switch`).checked;
        }
        return {mode, gains, enabled};
    },
    validState(state) {
        return state && typeof state.on === "boolean" && this.baseOptions.some(o => o.value === state.mode && state.mode)
            && (!this.modes[state.mode] || state.mode.split("+").every(c =>
                Number.isFinite(state.gains?.[c]) && state.gains[c] >= 0.1 && state.gains[c] <= 10 && typeof state.enabled?.[c] === "boolean"));
    },
    store() {
        if (!this.ready || !this.state) return;
        this.states[this.lightKey] = this.state;
        const json = JSON.stringify(this.states);
        localStorage.setItem(this.key, json);
        document.getElementById("led-preset-state").value = json;
    },
    selected() {return this.records.find(p => p.id === this.state?.selected && p.mode === this.state.mode);},
    mode() {
        const value = document.getElementById("backlight-color-list").value;
        return value.startsWith("preset:") ? (this.records.find(p => p.id === value.slice(7))?.mode || "") : value;
    },
    toggle() {
        const select = document.getElementById("backlight-color-list");
        if (this.mode() && this.state) this.changedBeforeOff();
        select.value = this.mode() ? "" : window.last_backlight_color;
        adjust_backlight(true);
    },
    dirty() {
        const preset = this.selected();
        return !!preset && preset.mode.split("+").some(c => preset.gains[c] !== this.state.gains[c] || preset.enabled[c] !== this.state.enabled[c]);
    },
    setUI(state) {
        const select = document.getElementById("backlight-color-list");
        select.value = state.on ? state.mode : "";
        window.last_backlight_color = state.mode;
        if (this.modes[state.mode]) for (const channel of state.mode.split("+")) {
            document.getElementById(`backlight-${channel}-num`).value = state.gains[channel];
            document.getElementById(`backlight-${channel}-switch`).checked = state.enabled[channel];
        }
    },
    changed() {
        if (!this.ready) return;
        if (backlightProfiles.running) {this.renderLabels(); return;}
        const mode = this.mode();
        if (mode && !this.baseOptions.some(o => o.value === mode)) return;
        if (mode) {
            const selected = this.state?.mode === mode ? this.state.selected : null;
            this.state = {...this.readSettings(mode), on: true, selected};
        } else if (this.state) {
            this.state.on = false;
            this.setUI(this.state);
        }
        else this.state = {...this.readSettings(window.last_backlight_color || "white"), on: false, selected: null};
        this.store();
        this.renderLabels();
    },
    renderLabels() {
        if (!this.baseOptions) return;
        const preset = this.selected(), suffix = preset ? ` · ${preset.name}${this.dirty() ? " *" : ""}` : "";
        for (const option of this.baseOptions) option.text = option.dataset.baseLabel;
        const select = document.getElementById("backlight-color-list");
        if (!backlightProfiles.running && this.ready && this.state) {
            const value = preset && Array.from(select.options).some(o => o.value === `preset:${preset.id}`)
                ? `preset:${preset.id}` : this.state.mode;
            select.value = this.state.on ? value : "";
        }
        const current = this.baseOptions.find(o => o.value === this.mode());
        if (current) document.getElementById("header-backlight-color").textContent = current.text + (current.value && !backlightProfiles.running ? suffix : "");
        const canManage = this.ready && !backlightProfiles.running && this.state?.on
            && this.availableModes?.includes(this.state.mode) && this.modes[this.state.mode];
        const actions = canManage ? (preset ? "save,update,delete" : "save") : "";
        if (actions !== this.managementActions) {
            this.managementGroup?.remove();
            this.managementGroup = null;
            this.managementActions = actions;
            if (actions) {
                const group = document.createElement("optgroup");
                group.label = "Manage LED presets"; group.dataset.ledPresets = "true";
                for (const [action, label] of [["save", "Save current gains…"], ["update", "Update selected preset"], ["delete", "Delete selected preset…"]]) {
                    if (!actions.split(",").includes(action)) continue;
                    const option = new Option(label, `action:${action}`);
                    option.dataset.ledAction = action; group.appendChild(option);
                }
                select.appendChild(group);
                this.managementGroup = group;
            }
        }
    },
    rebuild() {
        const select = document.getElementById("backlight-color-list"), value = select.value;
        select.querySelectorAll('optgroup[data-led-presets]').forEach(group => group.remove());
        this.managementGroup = null;
        this.managementActions = null;
        for (const [mode, label] of Object.entries(this.modes)) {
            if (!this.ready || !this.availableModes?.includes(mode)) continue;
            const items = this.records.filter(p => p.mode === mode);
            if (!items.length) continue;
            const group = document.createElement("optgroup");
            group.label = `Presets ${label}`; group.dataset.ledPresets = "true";
            for (const preset of items) group.appendChild(new Option(preset.name, `preset:${preset.id}`));
            select.appendChild(group);
        }
        select.value = value;
        this.renderLabels();
    },
    async refresh(restore = false) {
        const epoch = ++this.epoch;
        const data = await backlightProfiles.request("LED_PRESET_LIST");
        if (epoch !== this.epoch) return;
        const key = this.identity(data.light), different = this.lightKey !== key;
        this.light = data.light; this.lightKey = key;
        this.records = data.presets; this.availableModes = data.modes;
        if (different || !this.ready) {
            const saved = this.states[key];
            this.state = this.validState(saved) ? {...saved, gains:{...saved.gains}, enabled:{...saved.enabled}} : null;
            this.ready = true;
            if (restore && this.state && this.baseOptions.some(o => o.value === this.state.mode && !o.disabled)) {
                this.setUI(this.state);
                window.last_backlight = null;
                adjust_backlight(true);
            } else {
                // Other clients may have changed the light: ask for authoritative state.
                if (this.state && !this.state.on) this.setUI(this.state);
                sendCommand2("GET");
            }
        }
        if (this.state?.selected && !this.selected()) this.state.selected = null;
        this.rebuild(); this.store();
    },
    async choose() {
        const select = document.getElementById("backlight-color-list"), value = select.value;
        if (value.startsWith("action:") || value.startsWith("preset:")) {
            select.value = this.state?.on ? this.state.mode : "";
            if (backlightProfiles.running) return;
            try {
                if (value.startsWith("preset:")) {
                    // Refresh before applying to avoid stale/deleted presets or hotplug.
                    const id = value.slice(7), key = this.lightKey;
                    await this.refresh();
                    const preset = this.records.find(p => p.id === id);
                    if (key !== this.lightKey || !preset) throw new Error("Preset is no longer available for this light.");
                    this.state = {mode:preset.mode,gains:{...preset.gains},enabled:{...preset.enabled},on:true,selected:id};
                    this.setUI(this.state);
                    window.last_backlight = null;
                    adjust_backlight(true);
                } else if (value === "action:delete") await this.remove();
                else if (value === "action:update") await this.update();
                else this.openEditor();
            } catch (error) {update_status_info(error.message, "BACKLIGHT");}
            finally {this.renderLabels();}
        } else {
            if (!value && this.state?.on) this.changedBeforeOff();
            if (value && this.state) this.state.selected = null;
            adjust_backlight(true);
        }
    },
    changedBeforeOff() {
        const mode = this.state.mode;
        this.state = {...this.state,...this.readSettings(mode)};
    },
    async update() {
        const preset = this.selected();
        if (!preset || !this.state?.on) return;
        await backlightProfiles.request("LED_PRESET_SAVE", {
            id:preset.id, name:preset.name, settings:this.readSettings(this.state.mode), light:this.light,
        });
        await this.refresh();
    },
    openEditor() {
        if (!this.state?.on || !this.modes[this.state.mode]) return;
        this.editing = {id:null, settings:this.readSettings(this.state.mode), light:this.light};
        document.getElementById("led-preset-name").value = "";
        document.getElementById("led-preset-status").textContent = "";
        document.getElementById("led-preset-save").disabled = false;
        show_modal("led-preset-modal");
    },
    async save() {
        if (!this.editing) return;
        const button = document.getElementById("led-preset-save");
        button.disabled = true;
        const editing = this.editing;
        try {
            const saved = await backlightProfiles.request("LED_PRESET_SAVE", {...editing,name:document.getElementById("led-preset-name").value});
            if (this.state?.mode === saved.mode && this.identity(saved.light) === this.lightKey) this.state.selected = saved.id;
            await this.refresh();
            this.editing = null;
            if (get_modal()?.id === "led-preset-modal") close_modal();
            screen_notification(`Preset “${saved.name}” saved.`, true);
        } catch (error) {document.getElementById("led-preset-status").textContent = error.message; button.disabled = false;}
    },
    remove() {
        const preset = this.selected();
        if (!preset) return;
        this.deleting = {id:preset.id, name:preset.name, lightKey:this.lightKey};
        document.getElementById("led-preset-delete-question").textContent = `Delete LED preset “${preset.name}”?`;
        document.getElementById("led-preset-delete-status").textContent = "";
        document.getElementById("led-preset-delete-confirm").disabled = false;
        show_modal("led-preset-delete-modal");
    },
    async confirmRemove() {
        const pending = this.deleting;
        const button = document.getElementById("led-preset-delete-confirm");
        if (!pending || button.disabled) return;
        button.disabled = true;
        try {
            if (!this.ready || pending.lightKey !== this.lightKey) throw new Error("The connected light has changed. Select the preset again.");
            await backlightProfiles.request("LED_PRESET_DELETE", {id:pending.id});
            if (this.state?.selected === pending.id) this.state.selected = null;
            await this.refresh();
            if (this.deleting === pending) {
                this.deleting = null;
                if (get_modal()?.id === "led-preset-delete-modal") close_modal();
            }
            screen_notification(`Preset “${pending.name}” deleted.`, true);
        } catch (error) {
            document.getElementById("led-preset-delete-status").textContent = error.message;
            button.disabled = false;
        }
    },
    disconnected() {
        this.ready = false; ++this.epoch;
        this.records = [];
        if (this.baseOptions) this.rebuild();
    },
};
