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
            const light = profile.light ? ` | ${profile.light.name}` : "";
            const option = new Option(`${profile.name}${light} (${profile.source === "builtin" ? "built-in" : "user"})`, profile.id);
            option.title = profile.light ? `${profile.light.adapter_class}; S/N ${profile.light.serial_number || "not assigned"}` : "";
            select.add(option);
        }
        select.value = this.profiles.some(p => p.id === value) ? value : "";
        this.selectionChanged();
        this.status(this.profiles.length ? "" : "No profiles installed. Create a calibration to add one.");
    },

    selectionChanged() {
        const select = document.getElementById("backlight-profile-list");
        const profile = this.profiles.find(p => p.id === select.value);
        document.getElementById("backlight-profile-delete").disabled = this.running || profile?.source !== "user";
        window.whiteBalance?.update();
    },

    async remove() {
        const id = document.getElementById("backlight-profile-list").value;
        const profile = this.profiles.find(p => p.id === id);
        if (this.running || profile?.source !== "user" || !confirm(`Delete profile “${profile.name}”?`)) return;
        try {
            await this.request("COLOR_PROFILE_DELETE", {id});
            localStorage.setItem("control.backlight.profile", "");
            await this.refresh("");
            this.status("");
            screen_notification(`Profile “${profile.name}” deleted.`, true);
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
            const {light, channels, channel_labels} = await this.request("CALIBRATION_INFO");
            label.textContent = `${light.name} (${light.adapter_class}) · ${light.serial_number ? "S/N " + light.serial_number : "S/N not assigned"} · Channels: ${channels.map(c => channel_labels?.[c] || c).join(", ")}`;
        } catch (error) {label.textContent = error.message;}
    },

    check(run) {
        if (run.cancelled) throw new Error("Calibration cancelled.");
        if (run.cameraId !== undefined && document.getElementById("camera-list").value !== run.cameraId) {
            throw new Error("The selected camera changed or was disconnected. Select a camera and repeat calibration.");
        }
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
        const left = Math.floor(width * 0.05), top = Math.floor(height * 0.05);
        const sampleWidth = width - 2 * left, sampleHeight = height - 2 * top;
        const histograms = Array.from({length: 3}, () => new Uint32Array(256));
        let clipped = 0, dark = 0;
        // Read strips to bound temporary memory even for large snapshots.
        for (let y = top; y < top + sampleHeight; y += 64) {
            const pixels = ctx.getImageData(left, y, sampleWidth, Math.min(64, top + sampleHeight - y)).data;
            for (let i = 0; i < pixels.length; i += 4) {
                const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
                histograms[0][r]++; histograms[1][g]++; histograms[2][b]++;
                if (r >= 254 || g >= 254 || b >= 254) clipped++;
                if (r <= 1 || g <= 1 || b <= 1) dark++;
            }
        }
        const count = sampleWidth * sampleHeight;
        const trim = Math.floor(count * 0.1);
        // Histogram ranks remove exactly 10% at each end, including partial bins.
        // Clipping above is counted on all pixels, before outlier rejection.
        const rgb = histograms.map(histogram => {
            let rank = 0, sum = 0;
            for (let value = 0; value < histogram.length; value++) {
                const next = rank + histogram[value];
                const kept = Math.max(0, Math.min(next, count - trim) - Math.max(rank, trim));
                sum += kept * value;
                rank = next;
            }
            return sum / (count - 2 * trim);
        });
        return {rgb, clipped_fraction: clipped / count, dark_fraction: dark / count, width, height,
            bounds: [left, top, sampleWidth, sampleHeight]};
    },

    validateSample(sample, run = {}) {
        const details = `RGB: [${sample.rgb.map(v => v.toFixed(1)).join(", ")}]; highlights >=254: ${(100 * sample.clipped_fraction).toFixed(2)}%; dark <=1: ${(100 * (sample.dark_fraction || 0)).toFixed(2)}% (central 90% area).`;
        let reason;
        if (sample.rgb.some(v => !Number.isFinite(v))) reason = "Invalid RGB measurement.";
        else if (sample.clipped_fraction > 0.05) reason = "Too many clipped highlights (limit 5%). Suggested first step: reduce camera exposure by 1 EV (-1 EV, e.g. 1/60 s to 1/125 s), or halve overall LED brightness, then repeat calibration.";
        else if (sample.rgb.some(v => v > 245)) reason = "A mean RGB channel exceeds 245. Suggested first step: reduce camera exposure by 1 EV (-1 EV, e.g. 1/60 s to 1/125 s), or halve overall LED brightness, then repeat calibration.";
        else if (run.isolatedChannel ? Math.max(...sample.rgb) < 5 : sample.rgb.some(v => v < 5)) {
            const maximum = Math.max(...sample.rgb);
            const suggestion = maximum < 32
                ? "Suggested first step: increase camera exposure by 2 EV (+2 EV, e.g. 1/60 s to 1/15 s), then repeat calibration."
                : maximum < 120
                    ? "Suggested first step: increase camera exposure by 1 EV (+1 EV, e.g. 1/60 s to 1/30 s), then repeat calibration."
                    : "Other RGB channels are already bright: check the illuminated area and channel balance before increasing overall exposure.";
            reason = `A mean RGB channel is below 5. ${suggestion}`;
        }
        if (reason) {
            console.warn("Backlight calibration rejected sample", sample);
            const error = new Error(`${reason} ${details} EV suggestions are approximate for preview RGB; keep exposure and WB fixed during measurement.`);
            if (sample.rgb.every(Number.isFinite)) {
                error.exposureDirection = sample.clipped_fraction > 0.05 || sample.rgb.some(v => v > 245) ? -1 : 1;
            }
            throw error;
        }
    },

    async tuneExposure(run, session) {
        const options = session.exposure_options || [session.base.exposure];
        let index = options.indexOf(session.base.exposure);
        const visited = new Set();
        while (!visited.has(index)) {
            this.check(run);
            visited.add(index);
            this.status(`Finding light exposure: ${options[index]} EV…`, true);
            const reply = await this.request("CALIBRATION_STEP", {token: session.token, exposure: options[index]});
            if (reply.settings.exposure !== options[index]) throw new Error("Server did not apply the requested LED exposure. Restart the server and repeat calibration.");
            session.base = reply.settings;
            let rgb, failure, direction;
            try {
                rgb = await this.measure(run);
                const maximum = Math.max(...rgb);
                direction = maximum < 80 ? 1 : maximum > 180 ? -1 : 0;
            } catch (error) {
                if (!error.exposureDirection) throw error;
                failure = error;
                direction = error.exposureDirection;
            }
            console.info("Backlight calibration auto EV", {exposure: options[index], rgb, direction});
            const next = index + direction;
            if (!direction || next < 0 || next >= options.length || visited.has(next)) {
                if (failure) throw new Error(`Automatic LED exposure reached its safe limit. ${failure.message}`);
                return rgb;
            }
            index = next;
        }
        throw new Error("Could not find a stable light exposure.");
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
            run.bounds = sample.bounds;
            this.validateSample(sample, run);
            if (stable.length && sample.rgb.some((v, c) => Math.abs(v - stable[0][c]) > 2)) stable = [];
            stable.push([...sample.rgb]);
            if (stable.length >= 3) return stable[0].map((_, c) => stable.reduce((sum, rgb) => sum + rgb[c], 0) / stable.length);
        }
        throw Object.assign(new Error("No stable new snapshots arrived. Check the preview and increase its settling delay if needed."), {snapshotUnavailable:true});
    },

    responseMatrix(baseline, samples, channels) {
        return [0, 1, 2].map(c => channels.map(channel => {
            const {low, high, low_level, high_level} = samples[channel];
            const midpoint = samples[channel].baseline || baseline;
            const format = rgb => rgb.map(v => v.toFixed(2)).join(", ");
            const measured = `RGB low (gain ${low_level}): [${format(low)}]; baseline: [${format(midpoint)}]; high (gain ${high_level}): [${format(high)}].`;
            if (Math.max(...high.map((v, i) => Math.abs(v - low[i]))) < 2) {
                throw new Error(`No measurable response from ${channel}. ${measured} Largest low-to-high RGB change is below 2. Check channel levels and preview delay.`);
            }
            const dominant = high.map((v, i) => Math.abs(v - low[i])).indexOf(Math.max(...high.map((v, i) => Math.abs(v - low[i]))));
            const lower = midpoint[dominant] - low[dominant];
            const upper = high[dominant] - midpoint[dominant];
            if (lower * upper <= 0 || Math.min(Math.abs(lower), Math.abs(upper)) < 0.25 * Math.max(Math.abs(lower), Math.abs(upper))) {
                const details = `${measured} Evaluated ${["R", "G", "B"][dominant]}: baseline-low = ${lower.toFixed(2)}, high-baseline = ${upper.toFixed(2)}; changes must have the same sign and the smaller magnitude must be at least 25% of the larger. Leave more light headroom or increase the settling delay.`;
                console.warn(`Uneven response from ${channel}. ${details}`);
                throw new Error(`Uneven response from ${channel}. ${details}`);
            }
            return (high[c] - low[c]) / (high_level - low_level);
        }));
    },

    async measureIsolated(run, session, channel) {
        const label = session.channel_labels?.[channel] || channel;
        const step = (factor = 1, level) => this.request("CALIBRATION_STEP", {
            token:session.token, channel, factor, phase:"isolated", ...(level === undefined ? {} : {level}),
        });
        run.isolatedChannel = channel;
        try {
            let level = 1, baseline, settings, lastGood = null;
            for (let attempt = 0; attempt < 12; attempt++) {
                this.check(run);
                this.status(`Measuring ${label} alone: gain ${level} (other LEDs off)…`, true);
                const applied = await step(1, level);
                if (applied.limited) {
                    if (!lastGood) throw new Error(`${label}: no PWM headroom for isolated measurement.`);
                    level = lastGood.level;
                    await step(1, level);
                    baseline = await this.measure(run);
                    settings = lastGood.settings;
                    break;
                }
                settings = applied.settings;
                let direction;
                try {
                    baseline = await this.measure(run);
                    lastGood = {level, settings};
                    const peak = Math.max(...baseline);
                    direction = peak < 80 ? 1 : peak > 180 ? -1 : 0;
                } catch (error) {
                    if (!error.exposureDirection) throw error;
                    direction = error.exposureDirection;
                    baseline = null;
                }
                const next = Math.max(0.1, Math.min(8.33, Math.round(level * (direction > 0 ? 1.5 : 0.65) * 100) / 100));
                if (!direction || next === level || attempt === 11) break;
                level = next;
            }
            if (!baseline || Math.max(...baseline) < 20) throw new Error(`${label} alone is too dark or clipped. Adjust the fixed camera exposure and repeat calibration.`);
            this.status(`Measuring ${label} alone: lower level…`, true);
            const lowStep = await step(0.8);
            if (lowStep.limited) throw new Error(`${label}: insufficient PWM headroom.`);
            this.status(`Measuring ${label} alone: lower level, gain ${Number(lowStep.level.toFixed(3))} (other LEDs off)…`, true);
            const low = await this.measure(run);
            this.status(`Measuring ${label} alone: higher level…`, true);
            const highStep = await step(1.2);
            if (highStep.limited) throw new Error(`${label}: insufficient PWM headroom.`);
            this.status(`Measuring ${label} alone: higher level, gain ${Number(highStep.level.toFixed(3))} (other LEDs off)…`, true);
            const high = await this.measure(run);
            await step();
            const verification = await this.measure(run);
            if (verification.some((v, c) => Math.abs(v - baseline[c]) > 6)) throw new Error(`${label}: isolated baseline drifted. Check fixed camera exposure/WB and settling delay.`);
            const sample = {baseline, low, high, low_level:lowStep.level, high_level:highStep.level, settings, verification};
            this.responseMatrix(baseline, {[channel]:sample}, [channel]);
            console.info("Isolated light channel", JSON.stringify({channel, ...sample}));
            return sample;
        } finally {delete run.isolatedChannel;}
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
        if (window.whiteBalance?.running) {this.status("Cancel white balance before calibration.", true); return;}
        const cameraId = document.getElementById("camera-list").value;
        if (!cameraId) {this.status("Select a camera before starting calibration.", true); return;}
        let mode;
        try {mode = this.calibrationMode();} catch (error) {this.status(error.message, true); return;}
        const cameraProfileId = document.getElementById("camera-profile-list").value;
        if (!cameraProfileId) {this.status("Select a camera profile with Calibration settings before starting calibration.", true); return;}
        const nameInput = document.getElementById("backlight-profile-name");
        const name = nameInput.value.trim();
        if (!name) {this.status("Enter a profile name.", true); return;}
        const run = {cancelled: false, cameraId, cameraProfileId,
            usbpreview: window.current_usbpreview, settings: preview_settings()};
        run.mode = mode;
        const analyze = document.getElementById("stream-analyze-cb");
        run.originalAnalyze = analyze.checked;
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
            if (!analyze.checked) {
                analyze.checked = true;
                adjust_preview_mode();
            }
            this.check(run);
            this.status("Checking profile name…", true);
            await this.request("COLOR_PROFILE_CHECK", {name});
            this.check(run);
            beginAttempted = true;
            const session = await this.request("CALIBRATION_BEGIN", {name, method:"whole_lightbox", camera_id:cameraId, camera_profile_id:cameraProfileId});
            run.token = session.token;
            if (session.method !== "whole_lightbox") throw new Error("Restart the updated server before whole-lightbox calibration.");
            if (session.base.color !== run.mode) throw new Error("Light capabilities changed. Reconnect and repeat calibration.");
            this.check(run);
            const step = async (channel = null, factor = 1) => {
                this.check(run);
                return this.request("CALIBRATION_STEP", {token: session.token, channel, factor});
            };
            const baseline = await this.tuneExposure(run, session);
            console.info("Backlight calibration baseline", {rgb: baseline, settings: session.base});
            const isolatedSamples = {};
            if (session.method === "whole_lightbox") {
                for (const channel of session.channels) isolatedSamples[channel] = await this.measureIsolated(run, session, channel);
            }
            const samples = {};
            for (const channel of session.channels) {
                const label = session.channel_labels?.[channel] || channel;
                this.status(`Verifying ${label} in the mixture: lower level…`, true);
                const lowStep = await step(channel, 0.8);
                this.status(`Verifying ${label} in the mixture: lower level, gain ${Number(lowStep.settings.gain[channel].toFixed(3))}…`, true);
                const low = await this.measure(run);
                this.status(`Verifying ${label} in the mixture: higher level…`, true);
                const highStep = await step(channel, 1.2);
                this.status(`Verifying ${label} in the mixture: higher level, gain ${Number(highStep.settings.gain[channel].toFixed(3))}…`, true);
                const high = await this.measure(run);
                console.info("Backlight calibration channel", {channel, low, high});
                samples[channel] = {low, high, low_level: lowStep.settings.gain[channel], high_level: highStep.settings.gain[channel]};
            }
            this.status("Verifying the original light…", true);
            await step();
            const verification = await this.measure(run);
            const delta = verification.map((v, i) => v - baseline[i]);
            console.info("Backlight calibration verification", {baseline, verification, delta});
            if (verification.some((v, i) => Math.abs(v - baseline[i]) > 6)) {
                const format = rgb => rgb.map(v => v.toFixed(1)).join(", ");
                throw new Error(`Baseline changed during calibration. RGB start: [${format(baseline)}]; end: [${format(verification)}]; change: [${format(delta)}]. Check preview settling, camera settings and other connected clients changing the light.`);
            }
            profile = {schema_version: 1, name, channels: session.channels,
                matrix: this.responseMatrix(baseline, samples, session.channels),
                units: "preview_rgb_per_channel_gain", baseline: {settings: session.base, rgb: baseline},
                samples, verification, sampling: {method: "center_crop_trimmed_mean", border_fraction: 0.05,
                    trim_fraction: 0.1, dimensions: run.dimensions, bounds: run.bounds},
                preview: {source: run.usbpreview ? "camera" : "hdmi", ...run.settings},
                camera: {id: run.cameraId, model: window.current_camera?.model || "",
                    profile_id:run.cameraProfileId, white_balance:{source:"calibration_profile"},
                    exposure_requirement:"fixed_by_calibration_profile"},
                setup: session.setup, light: session.light, mode: run.mode, capabilities: window.capabilities, film: null};
            if (session.method === "whole_lightbox") Object.assign(profile, {
                scope:"lightbox", method:session.method, channel_labels:session.channel_labels,
                isolated_samples:isolatedSamples, isolated_matrix:this.responseMatrix(null, isolatedSamples, session.channels),
                matrix_context:"local_response_in_reference_mixture", isolated_matrix_context:"individually_lit_channels_at_recorded_gains",
            });
        } catch (error) {
            failure = error;
        } finally {
            if (beginAttempted) {
                try {
                    const restoration = await this.request("CALIBRATION_END");
                    if (restoration.camera_restore && !restoration.camera_restore.restored) {
                        throw new Error(restoration.camera_restore.warning || "Camera settings could not be restored.");
                    }
                }
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
            if (analyze.checked !== run.originalAnalyze) {
                analyze.checked = run.originalAnalyze;
                adjust_preview_mode();
            } else if (window.snapshot_canvas_ctx) refresh_snapshot();
        }
    },
};
