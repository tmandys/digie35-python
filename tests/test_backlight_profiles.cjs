const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../digie35/html/backlight_profiles.js'), 'utf8');

function setup() {
    const elements = {};
    const el = id => elements[id] ??= {value: '', checked: true, disabled: false, textContent: ''};
    el('snapshot-sample-size').value = '9';
    el('backlight-profile-name').value = 'Test';
    const stored = new Map();
    const calls = [];
    const context = {console, performance, setTimeout, clearTimeout,
        window: {snapshot_canvas_ctx: {}, snapshot_marker_position: [.5,.5], current_usbpreview: true, capabilities: {rgb_backlight:true}},
        document: {getElementById: el}, localStorage: {getItem: k => stored.get(k), setItem: (k,v) => stored.set(k,v)},
        preview_settings: () => ({interval: 250, timeout: 3000, wb_delay: 1000}),
        sendCommand2() {}, refresh_snapshot() {}, stop_snapshot_requests() {}, clear_snapshot_sample() {},
        adjust_preview_mode() {context.window.snapshot_canvas_ctx = el('stream-analyze-cb').checked ? {} : null;},
    };
    vm.createContext(context);
    vm.runInContext(source + '\nglobalThis.api = backlightProfiles;', context);
    const api = context.api;
    const defaults = {CALIBRATION_BEGIN: {token:'token', channels:['red'], base:{color:'red+green+blue',exposure:0,gain:{red:1}}},
        COLOR_PROFILE_SAVE: {id:'user:one',name:'Test'}};
    api.request = async (cmd, params) => {
        calls.push({cmd,params});
        if (cmd === 'CALIBRATION_STEP') return {settings:{color:'red+green+blue',exposure:params.exposure ?? 0,gain:{red:params.factor ?? 1}}};
        return defaults[cmd] || {};
    };
    api.refresh = async () => {};
    const measurements = [[100,110,120],[80,108,120],[120,112,120],[100,110,120]];
    const measure = api.measure;
    api.measure = async () => measurements.shift();
    return {api, context, el, calls, stored, measure};
}

test('successful calibration restores light before saving portable measurements', async () => {
    const h = setup();
    await h.api.start();
    const cmds = h.calls.map(c=>c.cmd);
    assert(cmds.indexOf('CALIBRATION_END') < cmds.indexOf('COLOR_PROFILE_SAVE'));
    const profile = h.calls.find(c=>c.cmd === 'COLOR_PROFILE_SAVE').params.profile;
    assert.equal(profile.schema_version, 1);
    assert(Math.abs(profile.matrix[0][0] - 100) < 1e-9);
    assert.equal(profile.units, 'preview_rgb_per_channel_gain');
    assert.equal(h.stored.get('control.backlight.profile'), 'user:one');
    assert.equal(h.api.running, false);
});

test('duplicate name stops before any LED command', async () => {
    const h = setup();
    h.api.request = async cmd => {h.calls.push({cmd}); throw new Error('Duplicate name');};
    await h.api.start();
    assert.deepEqual(h.calls.map(c=>c.cmd), ['COLOR_PROFILE_CHECK']);
    assert.match(h.el('backlight-calibration-status').textContent, /Duplicate/);
});

test('Analyze is enabled temporarily and restored on success, failure and cancellation', async () => {
    for (const outcome of ['success', 'failure', 'cancel']) {
        const h = setup();
        h.el('stream-analyze-cb').checked = false;
        h.context.window.snapshot_canvas_ctx = null;
        const measure = h.api.measure;
        h.api.measure = async run => {
            assert.equal(h.el('stream-analyze-cb').checked, true);
            if (outcome === 'failure') throw new Error('test failure');
            if (outcome === 'cancel') {h.api.cancel(); h.api.check(run);}
            return measure(run);
        };
        await h.api.start();
        assert.equal(h.el('stream-analyze-cb').checked, false);
        assert.equal(h.context.window.snapshot_canvas_ctx, null);
        assert.equal(h.api.running, false);
        assert(h.calls.some(c=>c.cmd === 'CALIBRATION_END'));
    }
});

test('auto EV increases dim baseline and saves the actual chosen exposure', async () => {
    const h = setup(), request = h.api.request;
    let ev = 0;
    h.api.request = async (cmd, params) => {
        const result = await request(cmd,params);
        if (cmd === 'CALIBRATION_BEGIN') result.exposure_options = [0,0.5,1];
        if (cmd === 'CALIBRATION_STEP') {
            if (params.exposure !== undefined) ev = params.exposure;
            result.settings.exposure = ev;
        }
        return result;
    };
    const measurements = [[30,40,50],[40,55,70],[100,110,120],[80,108,120],[120,112,120],[100,110,120]];
    h.api.measure = async () => measurements.shift();
    await h.api.start();
    assert.equal(h.calls.find(c=>c.cmd === 'COLOR_PROFILE_SAVE').params.profile.baseline.settings.exposure,1);
    assert.deepEqual(h.calls.filter(c=>c.cmd === 'CALIBRATION_STEP' && c.params.exposure !== undefined).map(c=>c.params.exposure),[0,0.5,1]);
});

test('auto EV backs off clipping and stops at safe limits', async () => {
    const h = setup();
    const run = {mode:'red+green+blue',usbpreview:true};
    let count = 0;
    h.api.measure = async () => {
        if (!count++) throw Object.assign(new Error('clipped'),{exposureDirection:-1});
        return [100,110,120];
    };
    const session = {token:'token',base:{exposure:1},exposure_options:[0.5,1]};
    await h.api.tuneExposure(run,session);
    assert.equal(session.base.exposure,0.5);
    h.api.measure = async () => {throw Object.assign(new Error('dark'),{exposureDirection:1});};
    await assert.rejects(h.api.tuneExposure(run,session), /safe limit/);
});

test('measurement failure restores light and never saves', async () => {
    const h = setup();
    h.api.measure = async () => {throw new Error('Clipped');};
    await h.api.start();
    assert.equal(h.calls.at(-1).cmd, 'CALIBRATION_END');
    assert(!h.calls.some(c=>c.cmd === 'COLOR_PROFILE_SAVE'));
    assert.match(h.el('backlight-calibration-status').textContent, /Clipped/);
});

test('lost begin reply still requests restoration; cancellation does not save', async () => {
    for (const cancelled of [false, true]) {
        const h = setup(), request = h.api.request;
        h.api.request = async (cmd, params) => {
            const reply = await request(cmd, params);
            if (cmd === 'CALIBRATION_BEGIN') {
                if (cancelled) h.api.cancel();
                else throw new Error('Reply timed out');
            }
            return reply;
        };
        await h.api.start();
        assert.equal(h.calls.at(-1).cmd, 'CALIBRATION_END');
        assert(!h.calls.some(c=>c.cmd === 'COLOR_PROFILE_SAVE'));
        assert.equal(h.api.running, false);
    }
});

test('bad response and drifting baseline do not create profiles', async () => {
    for (const values of [
        [[100,110,120],[100,110,120],[100,110,120],[100,110,120]],
        [[100,110,120],[80,108,120],[120,112,120],[120,130,140]],
    ]) {
        const h = setup();
        h.api.measure = async () => values.shift();
        await h.api.start();
        assert(!h.calls.some(c=>c.cmd === 'COLOR_PROFILE_SAVE'));
        assert.equal(h.calls.at(-1).cmd, 'CALIBRATION_END');
    }
});

test('changing capabilities invalidates calibration; marker is not required', () => {
    const h = setup();
    h.context.window.snapshot_marker_position = null;
    h.api.check({mode:'red+green+blue',usbpreview:true});
    h.context.window.capabilities = {white_backlight:true};
    assert.throws(() => h.api.check({mode:'red+green+blue',usbpreview:true}), /capabilities/);
});

test('capabilities select visible channels automatically', () => {
    const h = setup();
    for (const [caps, expected] of [
        [{rgbaw_backlight:true}, 'amber+white+red+green+blue'],
        [{rgbaw_backlight:true,rgb_backlight:true,white_backlight:true}, 'amber+white+red+green+blue'],
        [{rgb_backlight:true,white_backlight:true}, 'white+red+green+blue'],
        [{rgb_backlight:true}, 'red+green+blue'],
        [{white_backlight:true}, 'white'],
    ]) {
        h.context.window.capabilities = caps;
        assert.equal(h.api.calibrationMode(), expected);
    }
    h.context.window.capabilities = {ir_backlight:true};
    assert.throws(() => h.api.calibrationMode(), /no supported/);
});

test('uneven response reports measurements and the failing comparison', () => {
    const h = setup();
    assert.throws(() => h.api.responseMatrix([100,110,120], {
        white:{low:[90,109,120],high:[101,111,120],low_level:0.8,high_level:1.2},
    }, ['white']), /Uneven response from white.*RGB low \(gain 0.8\): \[90.00, 109.00, 120.00\].*baseline: \[100.00, 110.00, 120.00\].*high \(gain 1.2\): \[101.00, 111.00, 120.00\].*Evaluated R: baseline-low = 10.00, high-baseline = 1.00/);
});

test('RPC replies are correlated and server errors reject the request', async () => {
    const h = setup();
    // Use an isolated context to exercise the real request implementation.
    const c = vm.createContext({...h.context, window:{control_socket:{readyState:1,send(text){h.sent=text;}}}});
    vm.runInContext(source+'\nglobalThis.rpc=backlightProfiles;',c);
    const pending = c.rpc.request('COLOR_PROFILE_CHECK',{name:'Test'});
    const id = JSON.parse(h.sent.slice(h.sent.indexOf(':')+1)).client_context.profile_request;
    assert.equal(c.rpc.receive({cmd:'OTHER',payload:{}}), false);
    c.rpc.receive({cmd:'COLOR_PROFILE_CHECK',payload:{client_context:{profile_request:id},error:'Duplicate'}});
    await assert.rejects(pending,/Duplicate/);
    assert.equal(c.rpc.pending.size,0);
});

test('measurement requires three distinct stable frames', async () => {
    const h = setup();
    let now = 0, reads = 0;
    h.context.performance = {now: () => now};
    h.context.window.snapshot_sample_ctx = {};
    h.api.sampleFrame = () => ({rgb:[100,110,120],clipped_fraction:0,width:1920,height:1080});
    h.api.wait = async (run, ms) => {
        now += ms;
        if (ms === 50) {
            reads++;
            h.context.window.snapshot_frame = {started_at:now, sequence:reads, timestamp:[1,1,2,2,3][reads-1]};
        }
    };
    const rgb = await h.measure.call(h.api,{settings:{wb_delay:1000,timeout:3000,interval:250}});
    assert.deepEqual(Array.from(rgb),[100,110,120]);
    assert.equal(reads,5);
});

test('center crop excludes borders from both averaging and clipping', () => {
    const h = setup();
    let total = 0;
    const ctx = {canvas:{width:100,height:200},getImageData(x,y,w,height) {
        assert.equal(x,5); assert.equal(w,90); assert(height <= 64);
        assert(y >= 10 && y + height <= 190);
        total += w*height;
        return {data:Uint8ClampedArray.from(Array.from({length:w*height},()=>[100,120,140,255]).flat())};
    }};
    const sample = h.api.sampleFrame(ctx);
    assert.equal(total,90*180);
    assert.deepEqual(Array.from(sample.bounds),[5,10,90,180]);
    assert.deepEqual(Array.from(sample.rgb),[100,120,140]);
    assert.equal(sample.clipped_fraction,0);
});

test('trimmed mean rejects dust and highlights without hiding clipping', () => {
    const h = setup();
    const pixels = [
        ...Array.from({length:10}, () => [0, 0, 0, 255]),
        ...Array.from({length:80}, () => [100, 120, 140, 255]),
        ...Array.from({length:10}, () => [255, 255, 255, 255]),
    ];
    const sample = h.api.sampleFrame({canvas:{width:100,height:1},getImageData(x,y,w) {
        return {data:Uint8ClampedArray.from(pixels.slice(x,x+w).flat())};
    }});
    assert.deepEqual(Array.from(sample.rgb), [100,120,140]);
    assert.equal(sample.clipped_fraction, 5/90);
    assert.equal(sample.dark_fraction, 5/90);
});

test('dark pixels are distinct from highlights and errors report measured values', () => {
    const h = setup();
    const sample = {rgb:[40,50,60],clipped_fraction:0,dark_fraction:0.08};
    h.api.validateSample(sample);
    assert.throws(() => h.api.validateSample({...sample,clipped_fraction:0.06}), /clipped highlights.*RGB: \[40.0, 50.0, 60.0\]; highlights >=254: 6.00%; dark <=1: 8.00%/);
    assert.throws(() => h.api.validateSample({...sample,rgb:[4,50,60]}), /below 5/);
    assert.throws(() => h.api.validateSample({...sample,rgb:[246,50,60]}), /exceeds 245/);
    assert.throws(() => h.api.validateSample({...sample,rgb:[246,50,60]}), /-1 EV/);
    assert.throws(() => h.api.validateSample({...sample,rgb:[2,3,4]}), /\+2 EV/);
    assert.throws(() => h.api.validateSample({...sample,rgb:[4,50,60]}), /\+1 EV/);
    assert.throws(() => h.api.validateSample({...sample,rgb:[4,200,220]}), /channel balance before increasing/);
});

test('trimmed mean handles partial histogram bins and tiny frames', () => {
    const h = setup();
    for (const values of [[10,10,20,30,40,50,60,70,90,90], [42]]) {
        const sample = h.api.sampleFrame({canvas:{width:values.length,height:1},getImageData() {
            return {data:Uint8ClampedArray.from(values.flatMap(v => [v,v,v,255]))};
        }});
        const trim = Math.floor(values.length * 0.1);
        const kept = values.slice(trim, values.length - trim);
        const expected = kept.reduce((a,b) => a+b,0) / kept.length;
        assert.deepEqual(Array.from(sample.rgb), [expected,expected,expected]);
    }
});
