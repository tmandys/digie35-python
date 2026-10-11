// Run with: node --test tests/test_snapshot_preview.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../digie35/html/digie35.html'), 'utf8');
const source = html.slice(html.indexOf('    function preview_settings()'),
    html.indexOf('    function adjust_preview_mode()'));

function setup() {
    const timers = new Map();
    const calls = [];
    const images = [];
    const revoked = [];
    const elements = {
        'stream-analyze-cb': {checked: true}, 'stream-vision-cb': {checked: false},
        'snapshot-sample-size': {value: '9'},
    };
    for (const [id, value, min, max, step] of [
        ['snapshot-interval', 250, 50, 10000, 50],
        ['snapshot-timeout', 3000, 500, 30000, 100],
        ['snapshot-wb-delay', 1000, 0, 10000, 50],
    ]) {
        elements[id] = {value: String(value), defaultValue: String(value), checkValidity() {
            const n = Number(this.value);
            return n >= min && n <= max && (n - min) % step === 0;
        }};
    }
    let draws = 0;
    let failures = 0;
    let nextTimer = 0;
    const clean = {canvas: {}, drawImage() {}};
    const context = {
        window: {snapshot_canvas_ctx: {canvas: {width: 960, height: 540}, drawImage() {draws++;}}},
        document: {getElementById: id => elements[id], createElement: () => ({getContext: () => clean})},
        AbortController, performance, console: {warn() {}},
        Image: function() {this.naturalWidth = 1920; this.naturalHeight = 1080; images.push(this);},
        URL: {createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url)},
        setTimeout(fn, ms) {const id = ++nextTimer; timers.set(id, {fn, ms}); return id;},
        clearTimeout: id => timers.delete(id),
        fetch(url, options) {return new Promise((resolve, reject) => calls.push({url, options, resolve, reject}));},
        get_stream_url: () => '/snapshot',
        clear_snapshot_sample() {context.window.snapshot_color_sample = null;},
        canvas_draw_empty() {failures++;},
        update_color_box() {}, snapshot_draw_marker() {}, snapshot_draw_analysis() {},
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    return {context, timers, calls, images, revoked, elements, clean,
        draws: () => draws, failures: () => failures,
        fire(id) {const timer = timers.get(id); assert.ok(timer); timers.delete(id); timer.fn();},
        respond(index = calls.length - 1) {calls[index].resolve({ok: true, blob: async () => ({})});},
    };
}

test('all inline scripts parse and preview control IDs are unique', () => {
    for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
    for (const id of ['preview-settings-modal', 'snapshot-sample-size', 'snapshot-interval', 'snapshot-timeout', 'snapshot-wb-delay']) {
        assert.equal(html.split(` id="${id}"`).length - 1, 1);
    }
});

test('single flight, decode completion, natural resolution and scheduled retry', async () => {
    const h = setup(), c = h.context;
    const pending = c.refresh_snapshot();
    await c.refresh_snapshot();
    assert.equal(h.calls.length, 1);
    h.respond();
    await pending;
    assert.ok(c.window.snapshot_request); // transfer complete, still decoding
    h.images[0].onload();
    assert.equal(h.draws(), 1);
    assert.equal(h.clean.canvas.width, 1920);
    assert.equal(h.clean.canvas.height, 1080);
    assert.equal(c.window.snapshot_request, null);
    assert.equal(h.timers.size, 1);
    assert.equal(h.timers.get(c.window.snapshot_timer).ms, 250);
    assert.deepEqual(h.revoked, ['blob:test']);
    h.fire(c.window.snapshot_timer);
    assert.equal(h.calls.length, 2);
    c.stop_snapshot_requests();
});

test('hung transfer times out; late completion cannot replace a newer request', async () => {
    const h = setup(), c = h.context;
    const pending = c.refresh_snapshot();
    const old = c.window.snapshot_request;
    h.fire(old.timer);
    assert.equal(h.calls[0].options.signal.aborted, true);
    assert.equal(h.failures(), 1);
    h.fire(c.window.snapshot_timer);
    const current = c.window.snapshot_request;
    h.respond(0); // deliberately simulate a transport ignoring cancellation
    await pending;
    assert.equal(c.window.snapshot_request, current);
    assert.equal(h.draws(), 0);
    c.stop_snapshot_requests();
});

test('hung decoder is bounded and its late callback is ignored', async () => {
    const h = setup(), c = h.context;
    const pending = c.refresh_snapshot();
    h.respond(); await pending;
    const late = h.images[0].onload;
    h.fire(c.window.snapshot_request.timer);
    late();
    assert.equal(h.draws(), 0);
    assert.deepEqual(h.revoked, ['blob:test']);
    assert.equal(h.timers.size, 1);
});

test('stop cancels the request, scheduled retry and stale callbacks', async () => {
    const h = setup(), c = h.context;
    const pending = c.refresh_snapshot();
    h.respond(); await pending;
    const late = h.images[0].onload;
    c.stop_snapshot_requests();
    late();
    assert.equal(h.draws(), 0);
    assert.equal(h.timers.size, 0);
    assert.equal(c.window.snapshot_request, null);
    c.window.snapshot_canvas_ctx = null;
    await c.refresh_snapshot();
    assert.equal(h.calls.length, 1);
});

test('HTTP and decoding failures clear measurements and schedule recovery', async () => {
    for (const type of ['http', 'decode', 'network']) {
        const h = setup(), c = h.context;
        c.window.snapshot_color_sample = {rgb: [1, 2, 3]};
        const pending = c.refresh_snapshot();
        if (type === 'http') h.calls[0].resolve({ok: false, status: 503});
        else if (type === 'network') h.calls[0].reject(new Error('Disconnected'));
        else h.respond();
        await pending;
        if (type === 'decode') h.images[0].onerror();
        assert.equal(c.window.snapshot_color_sample, null);
        assert.equal(h.failures(), 1);
        assert.equal(h.timers.size, 1);
    }
});

test('settings reject invalid values, accept zero WB delay and reschedule idle polling', () => {
    const h = setup(), c = h.context;
    h.elements['snapshot-interval'].value = '';
    h.elements['snapshot-timeout'].value = '-1';
    h.elements['snapshot-wb-delay'].value = '0';
    h.elements['snapshot-sample-size'].value = '';
    c.adjust_preview_settings();
    assert.equal(h.elements['snapshot-interval'].value, 250);
    assert.equal(h.elements['snapshot-timeout'].value, 3000);
    assert.equal(h.elements['snapshot-wb-delay'].value, 0);
    assert.equal(h.elements['snapshot-sample-size'].value, '9');
    h.elements['snapshot-interval'].value = '500';
    c.adjust_preview_settings();
    assert.equal(h.timers.size, 1);
    assert.equal(h.timers.get(c.window.snapshot_timer).ms, 500);
});
