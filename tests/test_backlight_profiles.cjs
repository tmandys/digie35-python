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
    };
    vm.createContext(context);
    vm.runInContext(source + '\nglobalThis.api = backlightProfiles;', context);
    const api = context.api;
    const defaults = {CALIBRATION_BEGIN: {token:'token', channels:['red'], base:{color:'red+green+blue',exposure:0,gain:{red:1}}},
        COLOR_PROFILE_SAVE: {id:'user:one',name:'Test'}};
    api.request = async (cmd, params) => {
        calls.push({cmd,params});
        if (cmd === 'CALIBRATION_STEP') return {settings:{gain:{red:params.factor}}};
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

test('full frame averaging includes every source pixel and bounds temporary read size', () => {
    const h = setup();
    let total = 0;
    const ctx = {canvas:{width:4,height:130},getImageData(x,y,w,height) {
        assert.equal(x,0); assert.equal(w,4); assert(height <= 64);
        total += w*height;
        return {data:Uint8ClampedArray.from(Array.from({length:w*height},(_,i)=>[y+Math.floor(i/w),100,200,255]).flat())};
    }};
    const sample = h.api.sampleFrame(ctx);
    assert.equal(total,520);
    assert.deepEqual(Array.from(sample.rgb),[64.5,100,200]);
    assert.equal(sample.clipped_fraction,2/130);
});
