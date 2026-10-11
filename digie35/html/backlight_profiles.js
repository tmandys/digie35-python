// Profile management and camera-side measurement; LED ownership stays on the server.
const backlightProfiles = {
    pending: new Map(), serial: 0, profiles: [], running: false, run: null,

    status(message, calibration = false) {
        document.getElementById(calibration ? "backlight-calibration-status" : "backlight-profile-status").textContent = message;
    },

    request(cmd, params = {}) {
        return new Promise((resolve, reject) => {
            const socket = window.control_socket;
            if (!socket || socket.readyState !== 1) {
                reject(new Error("Connect to the server first."));
                return;
            }
            const id = ++this.serial;
            const timer = setTimeout(() => {
                this.pending.delete(id);
                reject(new Error(`${cmd}: server response timed out.`));
            }, 15000);
            this.pending.set(id, {resolve, reject, timer, cmd});
            try {
                socket.send(cmd + ":" + JSON.stringify({...params, client_context: {profile_request: id}}));
            } catch (error) {
                clearTimeout(timer);
                this.pending.delete(id);
                reject(error);
            }
        });
    },

    receive(data) {
        const id = data?.payload?.client_context?.profile_request;
        if (id === undefined) return false;
        const pending = this.pending.get(id);
        if (pending && pending.cmd === data.cmd) {
            this.pending.delete(id);
            clearTimeout(pending.timer);
            if (data.payload.error) pending.reject(new Error(data.payload.error));
            else pending.resolve(data.payload);
        }
        return true;
    },

    disconnected() {
        if (this.run) this.run.cancelled = true;
        for (const pending of this.pending.values()) {
            clearTimeout(pending.timer);
            pending.reject(new Error("Server connection lost; calibration was cancelled."));
        }
        this.pending.clear();
        this.status("Connect to the server to load profiles.");
    },

    async refresh(selected) {
        const data = await this.request("COLOR_PROFILE_LIST");
        const select = document.getElementById("backlight-profile-list");
        const value = selected ?? (select.value || localStorage.getItem("control.backlight.profile") || "");
        this.profiles = data.profiles;
        select.replaceChildren(new Option("No profile", ""));
        for (const profile of this.profiles) {
            const light = profile.light ? ` — ${profile.light.name}` : "";
            const option = new Option(`${profile.name}${light} (${profile.source === "builtin" ? "built-in" : "user"})`, profile.id);
            option.title = profile.light ? `${profile.light.adapter_class}; S/N ${profile.light.serial_number || "not assigned"}` : "";
            select.add(option);
        }
        select.value = this.profiles.some(p => p.id === value) ? value : "";
        this.selectionChanged();
        this.status(this.profiles.length ? "Select a measured light/camera response profile." : "No profiles installed. Create a calibration to add one.");
    },

    selectionChanged() {
        const select = document.getElementById("backlight-profile-list");
        const profile = this.profiles.find(p => p.id === select.value);
        document.getElementById("backlight-profile-delete").disabled = this.running || profile?.source !== "user";
    },

    async remove() {
        const id = document.getElementById("backlight-profile-list").value;
        const profile = this.profiles.find(p => p.id === id);
        if (this.running || profile?.source !== "user" || !confirm(`Delete profile “${profile.name}”?`)) return;
        try {
            await this.request("COLOR_PROFILE_DELETE", {id});
            localStorage.setItem("control.backlight.profile", "");
            await this.refresh("");
            this.status("Profile deleted.");
        } catch (error) {
            this.status(error.message);
        }
    },

    openCalibration() {
        this.status("", true);
        this.updateCalibrationLight();
        show_modal("backlight-calibration-modal");
    },

    calibrationMode() {
        const caps = window.capabilities || {};
        if (caps.rgbaw_backlight) return "amber+white+red+green+blue";
        if (caps.rgb_backlight) return (caps.white_backlight ? "white+" : "") + "red+green+blue";
        if (caps.white_backlight) return "white";
        throw new Error("The connected light has no supported visible calibration channels.");
    },

    async updateCalibrationLight() {
        const label = document.getElementById("backlight-calibration-light");
        label.textContent = "Reading connected light…";
        try {
            const {light, channels} = await this.request("CALIBRATION_INFO");
            label.textContent = `${light.name} (${light.adapter_class}) · ${light.serial_number ? "S/N " + light.serial_number : "S/N not assigned"} · Channels: ${channels.join(", ")}`;
        } catch (error) {label.textContent = error.message;}
    },

    check(run) {
        if (run.cancelled) throw new Error("Calibration cancelled.");
        if (!window.snapshot_canvas_ctx || !document.getElementById("stream-analyze-cb").checked) {
            throw new Error("Enable Analyze in Preview before calibration.");
        }
        if (this.calibrationMode() !== run.mode || window.current_usbpreview !== run.usbpreview) {
            throw new Error("The preview source or light capabilities changed. Repeat calibration.");
        }
    },

    sampleFrame(ctx) {
        const {width, height} = ctx.canvas;
        if (!width || !height) throw new Error("No source snapshot available.");
        const sums = [0, 0, 0];
        let clipped = 0;
        // Read strips to bound temporary memory even for large snapshots.
        for (let y = 0; y < height; y += 64) {
            const pixels = ctx.getImageData(0, y, width, Math.min(64, height - y)).data;
            for (let i = 0; i < pixels.length; i += 4) {
                const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
                sums[0] += r; sums[1] += g; sums[2] += b;
                if (r <= 1 || g <= 1 || b <= 1 || r >= 254 || g >= 254 || b >= 254) clipped++;
            }
        }
        return {rgb: sums.map(sum => sum / (width * height)), clipped_fraction: clipped / (width * height), width, height};
    },

    async wait(run, milliseconds) {
        const until = performance.now() + milliseconds;
        do {
            this.check(run);
            await new Promise(resolve => setTimeout(resolve, Math.min(100, Math.max(0, until - performance.now()))));
        } while (performance.now() < until);
        this.check(run);
    },

    async measure(run) {
        // Discard requests started before the acknowledged LED step.
        stop_snapshot_requests();
        clear_snapshot_sample();
        await this.wait(run, run.settings.wb_delay);
        stop_snapshot_requests();
        const after = performance.now();
        refresh_snapshot();
        const deadline = after + Math.min(90000, Math.max(15000, 4 * (run.settings.timeout + run.settings.interval)));
        let previous = null;
        let stable = [];
        while (performance.now() < deadline) {
            await this.wait(run, 50);
            const frame = window.snapshot_frame;
            if (!window.snapshot_sample_ctx || !frame || frame.started_at < after) continue;
            const identity = frame.timestamp || frame.sequence;
            if (identity === previous) continue;
            previous = identity;
            const sample = this.sampleFrame(window.snapshot_sample_ctx);
            if (run.dimensions && (run.dimensions[0] !== sample.width || run.dimensions[1] !== sample.height)) {
                throw new Error("Snapshot dimensions changed during calibration.");
            }
            run.dimensions = [sample.width, sample.height];
            if (sample.rgb.some(v => !Number.isFinite(v) || v < 5 || v > 245) || sample.clipped_fraction > 0.05) {
                throw new Error("The sample is too dark or clipped. Adjust camera exposure or light and repeat.");
            }
            if (stable.length && sample.rgb.some((v, c) => Math.abs(v - stable[0][c]) > 2)) stable = [];
            stable.push([...sample.rgb]);
            if (stable.length >= 3) return stable[0].map((_, c) => stable.reduce((sum, rgb) => sum + rgb[c], 0) / stable.length);
        }
        throw new Error("No stable new snapshots arrived. Check the preview and increase its settling delay if needed.");
    },

    responseMatrix(baseline, samples, channels) {
        return [0, 1, 2].map(c => channels.map(channel => {
            const {low, high, low_level, high_level} = samples[channel];
            if (Math.max(...high.map((v, i) => Math.abs(v - low[i]))) < 2) {
                throw new Error(`No measurable response from ${channel}. Check channel levels and preview delay.`);
            }
            const dominant = high.map((v, i) => Math.abs(v - low[i])).indexOf(Math.max(...high.map((v, i) => Math.abs(v - low[i]))));
            const lower = baseline[dominant] - low[dominant];
            const upper = high[dominant] - baseline[dominant];
            if (lower * upper <= 0 || Math.min(Math.abs(lower), Math.abs(upper)) < 0.25 * Math.max(Math.abs(lower), Math.abs(upper))) {
                throw new Error(`Uneven response from ${channel}. Leave more light headroom or increase the settling delay.`);
            }
            return (high[c] - low[c]) / (high_level - low_level);
        }));
    },

    cancel() {
        if (this.run) {
            this.run.cancelled = true;
            this.status("Cancelling and restoring the original light…", true);
            // Restore promptly even if a measurement or an earlier RPC is still waiting.
            this.request("CALIBRATION_END").catch(() => {});
        }
    },

    async start() {
        if (this.running) return;
        const nameInput = document.getElementById("backlight-profile-name");
        const name = nameInput.value.trim();
        if (!name) {this.status("Enter a profile name.", true); return;}
        const run = {cancelled: false,
            usbpreview: window.current_usbpreview, settings: preview_settings()};
        try {run.mode = this.calibrationMode(); this.check(run);} catch (error) {this.status(error.message, true); return;}
        this.running = true;
        this.run = run;
        document.getElementById("backlight-calibration-start").disabled = true;
        document.getElementById("backlight-calibration-cancel").disabled = false;
        nameInput.disabled = true;
        this.selectionChanged();
        let profile = null;
        let failure = null;
        let beginAttempted = false;
        try {
            this.status("Checking profile name…", true);
            await this.request("COLOR_PROFILE_CHECK", {name});
            this.check(run);
            beginAttempted = true;
            const session = await this.request("CALIBRATION_BEGIN", {name});
            run.token = session.token;
            if (session.base.color !== run.mode) throw new Error("Light capabilities changed. Reconnect and repeat calibration.");
            this.check(run);
            const step = async (channel = null, factor = 1) => {
                this.check(run);
                return this.request("CALIBRATION_STEP", {token: session.token, channel, factor});
            };
            this.status("Measuring baseline…", true);
            await step();
            const baseline = await this.measure(run);
            const samples = {};
            for (const channel of session.channels) {
                this.status(`Measuring ${channel}: lower level…`, true);
                const lowStep = await step(channel, 0.8);
                const low = await this.measure(run);
                this.status(`Measuring ${channel}: higher level…`, true);
                const highStep = await step(channel, 1.2);
                const high = await this.measure(run);
                samples[channel] = {low, high, low_level: lowStep.settings.gain[channel], high_level: highStep.settings.gain[channel]};
            }
            this.status("Verifying the original light…", true);
            await step();
            const verification = await this.measure(run);
            if (verification.some((v, i) => Math.abs(v - baseline[i]) > 6)) {
                throw new Error("Baseline changed during calibration. Check automatic camera settings and repeat.");
            }
            profile = {schema_version: 1, name, channels: session.channels,
                matrix: this.responseMatrix(baseline, samples, session.channels),
                units: "preview_rgb_per_channel_gain", baseline: {settings: session.base, rgb: baseline},
                samples, verification, sampling: {method: "full_frame_mean", dimensions: run.dimensions},
                preview: {source: run.usbpreview ? "camera" : "hdmi", ...run.settings},
                camera: {id: document.getElementById("camera-list").value, model: window.current_camera?.model || ""},
                setup: session.setup, light: session.light, mode: run.mode, capabilities: window.capabilities, film: null};
        } catch (error) {
            failure = error;
        } finally {
            if (beginAttempted) {
                try {await this.request("CALIBRATION_END");}
                catch (error) {failure = new Error(`Could not confirm light restoration: ${error.message} The server expires abandoned sessions after 120 seconds.`);}
            }
        }
        try {
            this.check(run);
            if (failure) throw failure;
            this.status("Saving profile…", true);
            const saved = await this.request("COLOR_PROFILE_SAVE", {profile, token: run.token});
            localStorage.setItem("control.backlight.profile", saved.id);
            await this.refresh(saved.id);
            this.status(`Profile “${saved.name}” saved. Original light restored.`, true);
        } catch (error) {
            this.status(failure?.message || error.message, true);
        } finally {
            this.running = false;
            this.run = null;
            nameInput.disabled = false;
            document.getElementById("backlight-calibration-start").disabled = false;
            document.getElementById("backlight-calibration-cancel").disabled = true;
            this.selectionChanged();
            window.last_backlight = null;
            sendCommand2("GET");
            if (window.snapshot_canvas_ctx) refresh_snapshot();
        }
    },
};
