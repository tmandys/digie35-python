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
        'stream-analyze-cb': {checked: true}, 'stream-vision-cb': {checked: false}, 'snapshot-focus-cb': {checked: false},
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
    let samples = 0;
    const clean = {canvas: {}, drawImage() {samples++;}};
    const context = {
        window: {snapshot_canvas_ctx: {canvas: {width: 960, height: 540}, drawImage() {draws++;}, clearRect() {failures++;}}},
        document: {getElementById: id => elements[id], createElement: () => ({getContext: () => clean})},
        AbortController, performance, console: {warn() {}},
        Image: function() {this.naturalWidth = 1920; this.naturalHeight = 1080; images.push(this);},
        URL: {createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url)},
        setTimeout(fn, ms) {const id = ++nextTimer; timers.set(id, {fn, ms}); return id;},
        clearTimeout: id => timers.delete(id),
        fetch(url, options) {return new Promise((resolve, reject) => calls.push({url, options, resolve, reject}));},
        get_stream_url: (usb, path) => `http://preview:${usb ? 8408 : 8410}/${path}`,
        clear_snapshot_sample() {context.window.snapshot_color_sample = null;},
        clear_focus_score() {},
        update_color_box() {}, snapshot_draw_marker() {}, snapshot_draw_zoom() {}, snapshot_draw_analysis() {}, request_focus_score() {},
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    vm.runInContext(html.slice(html.indexOf('    function redraw_snapshot_marker('),
        html.indexOf('    function canvas_draw_empty(')), context);
    return {context, timers, calls, images, revoked, elements, clean,
        samples: () => samples, draws: () => draws, failures: () => failures,
        fire(id) {const timer = timers.get(id); assert.ok(timer); timers.delete(id); timer.fn();},
        respond(index = calls.length - 1) {calls[index].resolve({ok: true, blob: async () => ({})});},
    };
}

test('all inline scripts parse and preview control IDs are unique', () => {
    for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
    for (const id of ['preview-settings-modal', 'snapshot-sample-size', 'snapshot-interval', 'snapshot-timeout', 'snapshot-wb-delay', 'snapshot-focus-cb']) {
        assert.equal(html.split(` id="${id}"`).length - 1, 1);
    }
});

test('Invert changes displayed RGB and swatch but preserves the measurement for WB', () => {
    const elements = {'stream-invert-cb': {checked: false},
        'snapshot-color-box': {style: {}}, 'snapshot-color-value': {}};
    const sample = {rgb: [12.25, 80.5, 240], bounds: [10, 20, 9, 9]};
    const context = {window: {snapshot_color_sample: sample},
        document: {getElementById: id => elements[id]}};
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('    function render_snapshot_color('),
        html.indexOf('    function clear_snapshot_sample(')), context);
    context.render_snapshot_color();
    assert.equal(elements['snapshot-color-box'].style.backgroundColor, 'rgb(12.25, 80.5, 240)');
    elements['stream-invert-cb'].checked = true;
    context.render_snapshot_color();
    assert.equal(elements['snapshot-color-box'].style.backgroundColor, 'rgb(242.75, 174.5, 15)');
    assert.equal(elements['snapshot-color-value'].textContent, '[R:243 G:175 B:15 ]');
    assert.deepEqual(sample.rgb, [12.25, 80.5, 240]);
    elements['stream-invert-cb'].checked = false;
    context.render_snapshot_color();
    assert.equal(elements['snapshot-color-box'].style.backgroundColor, 'rgb(12.25, 80.5, 240)');
});

test('floating readings and lens stay outside the focus ROI in all orientations', () => {
    const calls = [];
    const lc = {drawImage(...args) {calls.push({args, filter: this.filter});}};
    for (const method of ['clearRect', 'fillRect', 'save', 'restore', 'translate', 'scale', 'rotate',
        'beginPath', 'moveTo', 'lineTo', 'stroke']) lc[method] = () => {};
    const panel = {style: {}, offsetWidth: 210, offsetHeight: 200,
        offsetParent: {clientLeft: 0, clientTop: 0, getBoundingClientRect: () => ({left: 0, top: 0})}};
    const elements = {'snapshot-info': panel, 'snapshot-zoom-cb': {checked: true},
        'snapshot-focus-cb': {checked: true}, 'snapshot-focus-value': {}, 'stream-invert-cb': {checked: false},
        'stream-crop-x-rng': {value: '0'}, 'stream-crop-y-rng': {value: '0'},
        'snapshot-loupe': {width: 144, height: 144, getContext: () => lc}};
    const source = {width: 1920, height: 1080};
    const context = {window: {snapshot_sample_ctx: {canvas: source}},
        document: {getElementById: id => elements[id]}};
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('    const SNAPSHOT_FOCUS_SIZE'),
        html.indexOf('    function snapshot_draw_marker(')), context);
    vm.runInContext(html.slice(html.indexOf('    function snapshot_display_point('),
        html.indexOf('    // The live image stays underneath')), context);
    for (const angle of [0, 90, 180, 270]) for (const flip of [false, true]) {
        const rect = {left: 0, top: 0, width: angle % 180 ? 540 : 960, height: angle % 180 ? 960 : 540};
        const canvas = {clientWidth: 960, clientHeight: 540, getBoundingClientRect: () => rect,
            classList: {contains: name => name === (flip ? 'flip-' : '') + 'rotate' + angle}};
        for (const position of [[0.5, 0.5], [0, 0], [1, 1]]) {
            context.snapshot_draw_zoom({canvas}, position);
            assert.equal(panel.hidden, false);
            const bounds = context.snapshot_focus_bounds(source, position);
            const p1 = context.snapshot_display_point(canvas, [bounds[0] / source.width, bounds[1] / source.height]);
            const p2 = context.snapshot_display_point(canvas, [(bounds[0] + bounds[2]) / source.width,
                (bounds[1] + bounds[3]) / source.height]);
            const left = parseFloat(panel.style.left), top = parseFloat(panel.style.top);
            assert.ok(left >= 0 && top >= 0 && left + 210 <= rect.width && top + 200 <= rect.height);
            assert.ok(left + 210 <= Math.min(p1.x, p2.x) * rect.width - 12
                || left >= Math.max(p1.x, p2.x) * rect.width + 12
                || top + 200 <= Math.min(p1.y, p2.y) * rect.height - 12
                || top >= Math.max(p1.y, p2.y) * rect.height + 12);
            const {args} = calls.at(-1);
            assert.equal(args[0], source);
            assert.equal(args[1] + position[0] * args[3], 0);
            assert.equal(args[2] + position[1] * args[4], 0);
        }
    }
    const canvas = {clientWidth: 960, clientHeight: 540,
        getBoundingClientRect: () => ({left: 0, top: 0, width: 960, height: 540}), classList: {contains: () => false}};
    elements['stream-invert-cb'].checked = true;
    context.snapshot_draw_zoom({canvas}, [0.5, 0.5]);
    assert.equal(calls.at(-1).filter, 'invert(100%)');
    elements['snapshot-zoom-cb'].checked = false;
    elements['snapshot-focus-cb'].checked = false;
    const before = calls.length;
    context.snapshot_draw_zoom({canvas}, [0.5, 0.5]);
    assert.equal(calls.length, before);
    assert.equal(elements['snapshot-loupe'].hidden, true);
    assert.equal(elements['snapshot-focus-value'].hidden, true);
    assert.equal(panel.hidden, false);
    context.snapshot_draw_zoom(null, null);
    assert.equal(panel.hidden, true);
});

test('pointer selects the same source pixel through all CSS rotations and flips', () => {
    const context = {};
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('    function snapshot_pointer_position('),
        html.indexOf('    function snapshot_sample_bounds(')), context);
    for (const angle of [0, 90, 180, 270]) for (const flip of [false, true]) {
        for (const [width, height] of [[960, 540], [321, 713]]) {
            // Forward-project source points with the CSS matrix, independently
            // of the normalized inverse mapping used by the UI.
            const radians = angle * Math.PI / 180;
            const c = Math.round(Math.cos(radians)), s = Math.round(Math.sin(radians));
            const scale = angle % 180 ? 0.66 : 1;
            const project = (x, y) => [
                617 + (flip ? -1 : 1) * scale * (c * (x - 0.5) * width - s * (y - 0.5) * height),
                431 + scale * (s * (x - 0.5) * width + c * (y - 0.5) * height),
            ];
            const corners = [[0, 0], [1, 0], [0, 1], [1, 1]].map(p => project(...p));
            const left = Math.min(...corners.map(p => p[0])), top = Math.min(...corners.map(p => p[1]));
            const rect = {left, top, width: Math.max(...corners.map(p => p[0])) - left,
                height: Math.max(...corners.map(p => p[1])) - top};
            const canvas = {getBoundingClientRect: () => rect,
                classList: {contains: name => name === `${flip ? 'flip-' : ''}rotate${angle}`}};
            for (const [px, py] of [[0, 0], [1919, 0], [0, 1079], [1919, 1079], [387, 741], [960, 540]]) {
                const position = [(px + 0.5) / 1920, (py + 0.5) / 1080];
                const [clientX, clientY] = project(...position);
                const actual = context.snapshot_pointer_position(canvas, {clientX, clientY});
                assert.ok(Math.abs(actual[0] - position[0]) < 1e-12);
                assert.ok(Math.abs(actual[1] - position[1]) < 1e-12);
                assert.equal(Math.floor(actual[0] * 1920), px);
                assert.equal(Math.floor(actual[1] * 1080), py);
            }
        }
    }
});

test('Analyze keeps the same transform classes as the live preview', () => {
    const classes = () => {
        const values = new Set();
        return {contains: value => values.has(value), add: value => values.add(value),
            remove: (...items) => items.forEach(value => values.delete(value)),
            toggle: (value, force = !values.has(value)) => force ? values.add(value) : values.delete(value)};
    };
    const canvas = {classList: classes(), getAttribute: () => null};
    const analysisCanvas = {classList: classes()};
    const viewer = {classList: classes(), parentNode: {querySelector: () => canvas}};
    const radios = [0, 90, 180, 270].map(angle => ({type: 'radio', value: `rotate${angle}`}));
    const flip = {type: 'checkbox', value: 'flip', checked: false};
    const invert = {type: 'checkbox', value: 'invert', checked: true};
    const elements = {'stream': viewer, 'snapshot': canvas, 'snapshot-analysis': analysisCanvas, 'stream-analyze-cb': {checked: true}, 'stream-flip-cb': flip,
        'stream-control': {getElementsByTagName: () => [...radios, flip, invert]}};
    const context = {window: {}, document: {getElementById: id => elements[id]}};
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('    function adjust_media_viewer('),
        html.indexOf('    function is_color_active(')), context);
    for (const angle of [0, 90, 180, 270]) for (const mirrored of [false, true]) {
        radios.forEach(radio => radio.checked = radio.value === `rotate${angle}`);
        flip.checked = mirrored;
        context.adjust_media_viewer('stream', '', true);
        assert.equal(viewer.classList.contains('invert'), true);
        assert.equal(canvas.classList.contains('invert'), false);
        assert.equal(analysisCanvas.classList.contains('invert'), false);
        for (const candidate of [0, 90, 180, 270]) for (const prefix of ['', 'flip-']) {
            const name = `${prefix}rotate${candidate}`;
            assert.equal(canvas.classList.contains(name), candidate === angle && Boolean(prefix) === mirrored);
            assert.equal(analysisCanvas.classList.contains(name), candidate === angle && Boolean(prefix) === mirrored);
        }
    }
});

test('crosshair spans the preview while sample and focus bounds retain source pixel sizes', () => {
    const calls = [];
    const elements = {
        'stream-crosshair-cb': {checked: true},
        'snapshot-focus-cb': {checked: true},
        'snapshot-sample-size': {value: '9'},
    };
    const ctx = {canvas: {width: 960, height: 540}};
    for (const method of ['save', 'restore', 'beginPath', 'rect', 'moveTo', 'lineTo', 'stroke', 'strokeRect', 'drawImage', 'clearRect']) {
        ctx[method] = (...args) => calls.push([method, ...args]);
    }
    const context = {
        window: {snapshot_sample_ctx: {canvas: {width: 1920, height: 1080}},
            snapshot_canvas_ctx: ctx, snapshot_cursor_position: [0.5, 0.5]},
        document: {getElementById: id => elements[id]},
    };
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('    function snapshot_sample_bounds('),
        html.indexOf('    function snapshot_sample_rgb(')), context);
    vm.runInContext(html.slice(html.indexOf('    const SNAPSHOT_FOCUS_SIZE'),
        html.indexOf('    function canvas_draw_empty(')), context);
    context.redraw_snapshot_marker();
    for (const expected of [
        ['moveTo', 480, 0], ['lineTo', 480, 540],
        ['moveTo', 0, 270], ['lineTo', 960, 270],
        ['rect', 478, 268, 4.5, 4.5], ['strokeRect', 456, 246, 48, 48],
    ]) assert.ok(calls.some(call => JSON.stringify(call) === JSON.stringify(expected)), JSON.stringify(expected));
    assert.equal(calls[0][0], 'clearRect');
    calls.length = 0;
    context.window.snapshot_cursor_position = [1, 1];
    context.redraw_snapshot_marker();
    assert.ok(calls.some(call => JSON.stringify(call) === JSON.stringify(['strokeRect', 912, 492, 48, 48])));
    calls.length = 0;
    context.window.snapshot_cursor_position = null;
    context.redraw_snapshot_marker();
    assert.deepEqual(calls.map(call => call[0]), ['clearRect']);
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
    assert.equal(h.draws(), 0); // the live stream is never painted over
    assert.equal(h.samples(), 1);
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

test('analysis panel preserves live stream, supports both sources and cancels stale frames', async () => {
    const h = setup(), c = h.context;
    const classes = () => ({toggle() {}});
    const overlay = c.window.snapshot_canvas_ctx;
    const canvas = {style: {}, classList: classes(), getContext: () => overlay};
    overlay.canvas = canvas;
    const stream = {src: 'live-stream', clientWidth: 960, clientHeight: 540, offsetLeft: 5, offsetTop: 5,
        classList: {add() {assert.fail('live stream must remain visible');}, remove() {assert.fail('live stream must remain untouched');}}};
    Object.assign(h.elements, {'snapshot': canvas, 'stream': stream,
        'analyze-panel': {open: false}, 'snapshot-only-control': {classList: classes()}});
    c.adjust_media_viewer = () => {};
    vm.runInContext(html.slice(html.indexOf('    function adjust_preview_mode('),
        html.indexOf('    function have_external_dependencies(')), c);
    c.window.current_usbpreview = true;
    c.adjust_preview_mode();
    assert.equal(h.elements['analyze-panel'].open, true);
    assert.equal(h.calls.length, 1);
    assert.match(h.calls[0].url, /:8408\/snapshot\?/);
    assert.equal(canvas.width, 960);
    assert.equal(canvas.style.left, '5px');
    h.respond();
    await new Promise(resolve => setImmediate(resolve));
    const staleLoad = h.images[0].onload;
    c.window.current_usbpreview = false;
    c.adjust_preview_mode();
    assert.equal(h.calls[0].options.signal.aborted, true);
    assert.equal(h.elements['analyze-panel'].open, true);
    assert.match(h.calls[1].url, /:8410\/snapshot\?/);
    staleLoad();
    assert.equal(h.samples(), 0);
    h.respond();
    await new Promise(resolve => setImmediate(resolve));
    h.images[1].onload();
    assert.equal(h.samples(), 1);
    assert.equal(h.draws(), 0);
    stream.clientWidth = 480;
    stream.clientHeight = 270;
    c.sync_snapshot_overlay();
    assert.equal(canvas.width, 480);
    assert.equal(canvas.style.height, '270px');
    h.elements['analyze-panel'].open = false;
    c.toggle_analyze_panel();
    assert.equal(h.elements['stream-analyze-cb'].checked, false);
    assert.equal(c.window.snapshot_canvas_ctx, null);
    assert.equal(c.window.snapshot_frame, null);
    assert.equal(h.timers.size, 0);
    assert.equal(stream.src, 'live-stream');
    // Calibration/WB can lock the compatibility control while measuring.
    h.elements['stream-analyze-cb'].disabled = true;
    h.elements['analyze-panel'].open = true;
    c.toggle_analyze_panel();
    assert.equal(h.elements['analyze-panel'].open, false);
    assert.equal(h.calls.length, 2);
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
