// The browser measures the selected source-image area; the server owns LED changes.
const whiteBalance = window.whiteBalance = {
    running: false, run: null,
    profileId() {return document.getElementById("backlight-profile-list").value || localStorage.getItem("control.backlight.profile") || "";},
    unavailable() {
        if (!window.control_socket || window.control_socket.readyState !== 1) return "Connect to the server before WB.";
        if (backlightProfiles.running) return "Wait for light calibration to finish.";
        if (!document.getElementById("stream-analyze-cb").checked) return "Enable Analyze before WB.";
        if (!document.getElementById("camera-list").value) return "Select a camera before WB.";
        if (!window.snapshot_marker_position) return "Click the image to select a neutral reference area before WB.";
        const mode = ledPresets.mode();
        if (!ledPresets.modes[mode]) return "Select RGB, RGB+White or RGBAW before WB.";
        if (!this.profileId()) return "Select a measured color profile in Backlight settings before WB.";
        if (!window.snapshot_sample_ctx) return "Wait for a source snapshot before WB.";
        return "";
    },
    update() {
        const button = document.getElementById("snapshot-wb");
        if (!button) return;
        button.textContent = this.running ? "Cancel WB" : "WB";
        const reason = this.running ? "" : this.unavailable();
        button.disabled = !!reason;
        button.title = this.running ? "Cancel white balance and restore the original LED gains." : reason || "Make the selected area neutral by adjusting enabled LED gains, including white. Keep camera exposure and WB fixed; use a neutral reference (clear film base for a negative).";
    },
    status(text, failure = false) {
        update_status_info("", "WB", true);
        if (text) update_status_info(text, "WB", false, !failure);
    },
    check(run) {
        if (run.cancelled) throw new Error("White balance cancelled.");
        if (!window.control_socket || window.control_socket.readyState !== 1) throw new Error("Server disconnected during WB.");
        if (document.getElementById("camera-list").value !== run.cameraId
            || ledPresets.mode() !== run.mode || this.profileId() !== run.profileId
            || window.current_usbpreview !== run.usbpreview
            || JSON.stringify(window.snapshot_marker_position) !== JSON.stringify(run.position)
            || document.getElementById("snapshot-sample-size").value !== run.sampleSize
            || !document.getElementById("stream-analyze-cb").checked || !window.snapshot_canvas_ctx) {
            throw new Error("The camera, reference area, preview or light mode changed. Repeat WB.");
        }
    },
    apply(settings, originalGains = null) {
        if (!settings) return;
        document.getElementById("backlight-color-list").value = settings.color || "";
        for (const [c, gain] of Object.entries(settings.gain || {})) {
            document.getElementById(`backlight-${c}-switch`).checked = gain > 0;
            if (gain > 0) document.getElementById(`backlight-${c}-num`).value = gain;
            else if (originalGains?.[c] !== undefined) document.getElementById(`backlight-${c}-num`).value = originalGains[c];
        }
        window.last_backlight = null;
        adjust_backlight(true, false);
    },
    sampler(run) {
        const sampler = Object.create(backlightProfiles);
        sampler.check = () => this.check(run);
        sampler.sampleFrame = ctx => {
            const bounds = snapshot_sample_bounds(ctx.canvas, run.position);
            const pixels = ctx.getImageData(...bounds).data;
            let clipped = 0, dark = 0;
            for (let i = 0; i < pixels.length; i += 4) {
                if ([0,1,2].some(c => pixels[i+c] >= 254)) clipped++;
                if ([0,1,2].some(c => pixels[i+c] <= 1)) dark++;
            }
            return {rgb:snapshot_sample_rgb(pixels), bounds, width:ctx.canvas.width, height:ctx.canvas.height,
                clipped_fraction:clipped / (pixels.length / 4), dark_fraction:dark / (pixels.length / 4)};
        };
        return sampler;
    },
    async choosePartial(run) {
        document.getElementById("wb-interrupted-measurement").textContent = run.lastMeasurement || "No RGB measurement available.";
        show_modal("wb-interrupted-modal");
        run.partialChoice = null;
        const deadline = performance.now() + 20000;
        try {
            while (run.partialChoice === null && performance.now() < deadline) {
                this.check(run);
                if (get_modal()?.id !== "wb-interrupted-modal") return false;
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            this.check(run);
            return run.partialChoice === true;
        } finally {
            if (get_modal()?.id === "wb-interrupted-modal") close_modal();
        }
    },
    choose(keep) {if (this.run) this.run.partialChoice = keep;},
    async start() {
        if (this.running) {this.run.cancelled = true; this.status("Cancelling WB…"); return;}
        const reason = this.unavailable();
        if (reason) {this.status(reason); return;}
        const run = {position:[...window.snapshot_marker_position], mode:ledPresets.mode(),
            cameraId:document.getElementById("camera-list").value, profileId:this.profileId(),
            sampleSize:document.getElementById("snapshot-sample-size").value,
            usbpreview:window.current_usbpreview, settings:preview_settings(), cancelled:false,
            gains:Object.fromEntries(["red", "green", "blue"].map(c => [c, Number(document.getElementById(`backlight-${c}-num`).value)]))};
        this.run = run; this.running = true; this.update();
        const controls = Array.from(document.querySelectorAll("#backlight-fieldset, #backlight-settings-modal input, #backlight-settings-modal select, #backlight-settings-modal button:not(.close), #camera-list, #snapshot-sample-size, #stream-analyze-cb"));
        const disabled = controls.map(control => control.disabled);
        controls.forEach(control => {control.disabled = true;});
        let attempted = false, committed = false, failure = null;
        const request = (cmd, params) => backlightProfiles.request(cmd, params);
        try {
            this.check(run);
            this.status("Starting WB…");
            attempted = true;
            const session = await request("WB_BEGIN", {profile_id:run.profileId, camera_id:run.cameraId, enable_gains:run.gains});
            run.token = session.token;
            this.check(run);
            this.apply(session.settings);
            const sampler = this.sampler(run);
            for (let i = 0; i <= 16; i++) {
                this.status(`WB: measuring step ${i + 1}…${run.lastMeasurement ? " " + run.lastMeasurement : ""}`);
                const rgb = await sampler.measure(run);
                this.check(run);
                const result = await request("WB_STEP", {token:run.token, rgb});
                this.check(run);
                this.apply(result.settings);
                console.info("LED white balance", JSON.stringify(result));
                run.lastMeasurement = `RGB [${rgb.map(v => v.toFixed(1)).join(", ")}] · difference ${(result.imbalance * 100).toFixed(1)}%`;
                this.status(`WB: ${run.lastMeasurement}`);
                if (result.done) {
                    const end = await request("WB_END", {token:run.token, commit:true});
                    if (end.restored) throw new Error("WB expired before completion; original gains were restored.");
                    committed = true;
                    this.apply(end.settings);
                    screen_notification("White balance adjusted.", true);
                    break;
                }
            }
            if (!committed) throw new Error("WB did not converge within the step limit.");
        } catch (error) {
            failure = error.message;
            if (error.snapshotUnavailable && run.token && !run.cancelled && window.control_socket?.readyState === 1) {
                try {
                    if (await this.choosePartial(run)) {
                        const end = await request("WB_END", {token:run.token, commit:true, keep_partial:true});
                        if (end.restored) throw new Error("WB expired; original gains were restored.");
                        committed = true;
                        this.apply(end.settings);
                        failure = null;
                        this.status("WB unfinished. Current LED gains kept; the last change may not have been measured.");
                        screen_notification("Unfinished WB: LED gains kept.", true);
                    }
                } catch (choiceError) {failure = choiceError.message;}
            }
        }
        finally {
            if (attempted && !committed) {
                try {
                    const result = await request("WB_END", {token:run.token, commit:false});
                    this.apply(result.settings, result.restored ? run.gains : null);
                    failure = result.restored ? `${failure || "WB stopped."} Original LED gains restored.`
                        : "WB was applied successfully; its first confirmation was delayed.";
                } catch (error) {failure = `${failure || "WB stopped."} Restoration could not be confirmed: ${error.message} The server restores abandoned sessions after 120 seconds.`;}
            }
            this.running = false; this.run = null;
            controls.forEach((control, i) => {control.disabled = disabled[i];});
            adjust_backlight(true, false);
            this.update();
            sendCommand2("GET");
            if (failure) this.status(failure, true);
        }
    },
};
