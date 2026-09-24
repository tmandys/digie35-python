// Run with Node.js; no browser, server, hardware, or third-party packages needed.
// Executes the actual inline script and adapter actions. DOM drawing is stubbed.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '../digie35/html/digie35.html'), 'utf8');
const script = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]).join('\n');
const actionStart = script.indexOf('window.adapter_buttons = {');
const actionEnd = script.indexOf('function do_adapter_onclick', actionStart);
const actions = script.slice(actionStart, actionEnd);
const STREAM = 1, ALIGN = 2, CAPTURE = 4, REPEAT = 8;

function setup() {
    let now = 100000, random = 0, mode = 'multi';
    const timers = [], commands = [], messages = [], elements = {};
    function element(id) {
        return elements[id] ??= {
            value: '', checked: false, disabled: false, selectedIndex: 0,
            options: [], getAttribute: () => '0.5',
            getElementsByTagName: () => [],
        };
    }
    class Clock extends Date { static now() { return now; } }
    const math = Object.create(Math);
    math.random = () => ++random / 1000;
    const ctx = {
        Date: Clock, Math: math,
        console: {log() {}, info() {}, error() {}, debug() {}},
        document: {getElementById: element},
        setTimeout: (fn, delay) => { timers.push({fn, at: now + delay}); return timers.length; },
        WebSocket: function () {
            this.OPEN = this.readyState = 1;
            this.send = text => {
                const colon = text.indexOf(':');
                commands.push(colon < 0 ? [text] : [text.slice(0, colon), JSON.parse(text.slice(colon + 1))]);
            };
        },
    };
    ctx.window = ctx;
    vm.createContext(ctx);
    vm.runInContext(script, ctx, {filename: 'digie35.html:inline-script'});
    vm.runInContext(actions, ctx);
    Object.assign(ctx, {
        capabilities: {motorized: true, vision: true, flattening: false},
        analyze_request: 0, last_analyze_stamp: null, stop_multicapture: false,
        download_in_progress: false, multi_tags: {has_multi: false},
        focus_warning: {},
        adjust() {}, adjust_adapter() {}, adjust_backlight() {},
        update_battery() {}, refresh_snapshot() {}, notify_update() {},
        add_frame_to_filmstrip() {}, set_visible() {},
        update_status_info: (...args) => messages.push(args),
        screen_notification() {}, get_file_template_values: () => ({}),
        get_radio_button_value: name => name === 'capture-mode' ? mode : '',
        get_adapter_button: name => ({click: () => ctx.adapter_buttons[name].action('')}),
    });
    Object.assign(element('capture-multi'), {value: '3'});
    Object.assign(element('preview-latency-rng'), {value: '1'});
    Object.assign(element('shoot-mode-list'), {value: 'capture|download'});
    element('usb-preview-cb').checked = true;
    element('vision-alignment-cb').checked = true;
    if (ctx.cancel_alignment) ctx.cancel_alignment();
    else ctx.analyze_in_progress = 0; // Allows comparison with the unmodified HEAD.
    ctx.connect();
    return {
        ctx, commands, timers, messages, element,
        advance(ms) { now += ms; },
        runTimers() {
            const batch = timers.splice(0).sort((a, b) => a.at - b.at);
            for (const timer of batch) { now = Math.max(now, timer.at); timer.fn(); }
        },
        reply(cmd, payload) { ctx.control_socket.onmessage({data: JSON.stringify({cmd, payload})}); },
        analyzeReply(status, context) {
            context ??= commands.filter(c => c[0] === 'ANALYZE').at(-1)[1].client_context;
            this.reply('ANALYZE', {status, move_by: 20, pixel_per_mm: 10, client_context: context});
        },
        completedMove(context) {
            context ??= commands.filter(c => c[0] === 'MOVE_BY').at(-1)[1].client_context;
            this.reply('ADAPTER', {action: 'MOVE_BY', movement: 0, frame_ready: true, backlight: {color: ''}, client_context: context});
        },
        count(cmd) { return commands.filter(c => c[0] === cmd).length; },
    };
}

let passed = 0, failed = 0;
function test(name, fn) {
    try { fn(setup()); console.log('PASS', name); passed++; }
    catch (error) { console.log('FAIL', name, '\n    ' + error.message); failed++; }
}

test('Stop rejects old analysis after a new alignment starts', t => {
    t.ctx.sendCommandAnalyze(ALIGN);
    const old = t.commands.at(-1)[1].client_context;
    t.ctx.adapter_buttons.stop.action();
    t.ctx.sendCommandAnalyze(ALIGN);
    t.analyzeReply('SHIFT_REQUIRED', old);
    assert.equal(t.count('MOVE_BY'), 0);
    assert.equal(t.ctx.analyze_in_progress, ALIGN);
    t.analyzeReply('SHIFT_REQUIRED');
    assert.equal(t.count('MOVE_BY'), 1);
});
test('Stop invalidates pending alignment timer and movement completion', t => {
    t.ctx.sendCommandAnalyze(ALIGN); t.analyzeReply('SHIFT_REQUIRED');
    const old = t.commands.at(-1)[1].client_context;
    t.completedMove(old);
    t.ctx.adapter_buttons.stop.action();
    t.runTimers(); t.completedMove(old); t.runTimers();
    assert.equal(t.count('ANALYZE'), 1);
});
test('Late reply after timeout cannot overwrite current request', t => {
    t.ctx.sendCommandAnalyze(ALIGN);
    const old = t.commands.at(-1)[1].client_context;
    t.advance(6000); t.ctx.sendCommandAnalyze(ALIGN);
    t.analyzeReply('SHIFT_REQUIRED', old);
    assert.equal(t.count('MOVE_BY'), 0);
});
test('Successful standalone alignment releases busy state', t => {
    t.ctx.sendCommandAnalyze(ALIGN); t.analyzeReply('ALIGNED');
    assert.equal(t.ctx.analyze_in_progress, 0);
    t.ctx.sendCommandAnalyze(ALIGN);
    assert.equal(t.count('ANALYZE'), 2);
});
test('Alignment with capture shoots once', t => {
    t.ctx.sendCommandAnalyze(ALIGN | CAPTURE); t.analyzeReply('ALIGNED');
    assert.equal(t.count('CAPTURE'), 1);
});
test('Normal correction loop has a finite retry budget', t => {
    t.ctx.sendCommandAnalyze(ALIGN);
    for (let i = 0; i < 8; i++) {
        t.analyzeReply('SHIFT_REQUIRED');
        t.completedMove(); t.runTimers();
    }
    assert.equal(t.count('MOVE_BY'), 5);
    assert.equal(t.ctx.stop_multicapture, true);
});
test('Alignment error invalidates the operation; preview error does not', t => {
    const generation = t.ctx.alignment_generation;
    t.ctx.sendCommandAnalyze(STREAM); t.analyzeReply('NO_FILM');
    assert.equal(t.ctx.alignment_generation, generation);
    assert.equal(t.ctx.stop_multicapture, false);
    t.ctx.sendCommandAnalyze(ALIGN); t.analyzeReply('NO_FILM');
    assert.notEqual(t.ctx.alignment_generation, generation);
    assert.equal(t.ctx.stop_multicapture, true);
});
test('Preview analysis does not stop a capture sequence', t => {
    t.ctx.sendCommandAnalyze(STREAM); t.analyzeReply('ALIGNED');
    assert.equal(t.ctx.stop_multicapture, false);
});
test('Repeated readiness checks schedule exactly one capture', t => {
    t.element('vision-alignment-cb').checked = false;
    t.ctx.automove_in_progress = false;
    t.ctx.check_multicapture(); t.ctx.check_multicapture();
    assert.equal(t.timers.length, 1);
    t.runTimers(); assert.equal(t.count('CAPTURE'), 1);
});
test('Stop cancels pending capture even after another shoot resets stop flag', t => {
    t.element('vision-alignment-cb').checked = false;
    t.ctx.automove_in_progress = false; t.ctx.check_multicapture();
    t.ctx.adapter_buttons.stop.action(); t.ctx.adapter_buttons.shoot.action();
    t.runTimers(); assert.equal(t.count('CAPTURE'), 1);
});
for (const order of ['download-first', 'movement-first']) {
    test(`Capture cycle continues once: ${order}`, t => {
        t.element('automove-cb').checked = true;
        t.element('vision-alignment-cb').checked = false;
        t.reply('CAPTURE', {film_position: 0});
        const download = () => t.reply('DOWNLOAD', {file_path: 'image.jpg'});
        if (order === 'download-first') { download(); t.completedMove(); }
        else { t.completedMove(); download(); }
        t.runTimers(); assert.equal(t.count('CAPTURE'), 1);
    });
}
test('Manual movement supersedes outstanding alignment', t => {
    t.ctx.sendCommandAnalyze(ALIGN);
    t.ctx.adapter_buttons.move.action(1);
    t.analyzeReply('SHIFT_REQUIRED');
    assert.equal(t.count('MOVE_BY'), 0, 'old alignment still issues a correction after manual MOVE');
});
for (const action of ['move', 'moveby', 'frame', 'eject']) {
    test(`Manual ${action} invalidates old replies and scheduled alignment`, t => {
        t.ctx.sendCommandAnalyze(ALIGN);
        t.analyzeReply('SHIFT_REQUIRED');
        const oldMove = t.commands.at(-1)[1].client_context;
        t.completedMove(oldMove); // A follow-up analysis timer is now pending.
        t.advance(3000);
        t.ctx.sendCommandAnalyze(ALIGN);
        const oldAnalysis = t.commands.at(-1)[1].client_context;
        const generation = t.ctx.alignment_generation;
        t.ctx.adapter_buttons[action].action(1);
        assert.notEqual(t.ctx.alignment_generation, generation);
        const sent = t.commands.length;
        t.analyzeReply('SHIFT_REQUIRED', oldAnalysis);
        t.runTimers();
        t.completedMove(oldMove);
        t.runTimers();
        assert.equal(t.commands.length, sent);
        if (action === 'frame') {
            const currentMove = t.commands.filter(c => c[0] === 'MOVE_BY').at(-1)[1].client_context;
            t.completedMove(currentMove); t.runTimers();
            assert.equal(t.commands.at(-1)[0], 'ANALYZE');
        }
    });
}
test('Automatic frame advance preserves the capture operation', t => {
    const generation = t.ctx.alignment_generation;
    t.element('automove-cb').checked = true;
    t.reply('CAPTURE', {film_position: 0});
    assert.equal(t.ctx.alignment_generation, generation);
    assert.equal(t.commands.at(-1)[1].client_context.generation, generation);
    assert.equal(t.ctx.stop_multicapture, false);
    t.reply('DOWNLOAD', {file_path: 'image.jpg'});
    t.completedMove(); t.runTimers();
    t.analyzeReply('ALIGNED');
    assert.equal(t.count('CAPTURE'), 1);
});
test('Stop rejects delayed LEAD_IN completion', t => {
    t.ctx.adapter_buttons.stop.action();
    t.reply('ADAPTER', {action: 'LEAD_IN', movement: 0, frame_ready: true, backlight: {color: ''}});
    t.runTimers();
    if (t.count('ANALYZE')) t.analyzeReply('SHIFT_REQUIRED');
    assert.equal(t.count('MOVE_BY'), 0, 'old insertion completion restarts alignment after Stop');
});
test('Old INSERT completion is rejected after Stop and a new INSERT', t => {
    t.ctx.adapter_buttons.insert.action();
    const old = t.commands.at(-1)[1]?.client_context;
    assert.ok(old?.generation, 'INSERT must carry its operation token');
    t.ctx.adapter_buttons.stop.action();
    t.ctx.adapter_buttons.insert.action();
    const current = t.commands.at(-1)[1].client_context;
    assert.notEqual(old.generation, current.generation);
    const completed = context => t.reply('ADAPTER', {
        action: 'LEAD_IN', movement: 0, frame_ready: true,
        backlight: {color: ''}, client_context: context,
    });
    completed(old); t.runTimers();
    assert.equal(t.count('ANALYZE'), 0);
    completed(current); t.runTimers();
    assert.equal(t.count('ANALYZE'), 1);
    t.analyzeReply('SHIFT_REQUIRED');
    assert.equal(t.count('MOVE_BY'), 1);
});
test('Alignment merged into preview initializes retry budget', t => {
    t.ctx.sendCommandAnalyze(STREAM); t.ctx.sendCommandAnalyze(ALIGN);
    assert.equal(t.ctx.analyze_counter, 5);
    assert.equal(t.count('ANALYZE'), 1);
    t.analyzeReply('SHIFT_REQUIRED');
    assert.equal(t.count('MOVE_BY'), 1);
});
test('Multiple callers sharing an analysis consume one retry', t => {
    t.ctx.sendCommandAnalyze(ALIGN); t.analyzeReply('SHIFT_REQUIRED');
    t.advance(3000); t.ctx.sendCommandAnalyze(STREAM);
    t.ctx.sendCommandAnalyze(REPEAT | CAPTURE);
    assert.equal(t.ctx.analyze_counter, 4);
    t.ctx.sendCommandAnalyze(REPEAT | CAPTURE);
    t.ctx.sendCommandAnalyze(ALIGN);
    t.ctx.sendCommandAnalyze(STREAM);
    assert.equal(t.ctx.analyze_counter, 4);
    assert.equal(t.count('ANALYZE'), 2);
    t.analyzeReply('ALIGNED');
    assert.equal(t.count('CAPTURE'), 1);
});
test('Retry budget remains finite when every repeat joins a preview', t => {
    t.element('preview-latency-rng').value = '6';
    t.ctx.sendCommandAnalyze(STREAM); t.ctx.sendCommandAnalyze(ALIGN);
    t.analyzeReply('SHIFT_REQUIRED');
    for (let i = 0; i < 5; i++) {
        t.completedMove();
        t.advance(2600); t.ctx.sendCommandAnalyze(STREAM);
        t.runTimers(); t.analyzeReply('SHIFT_REQUIRED');
    }
    assert.equal(t.count('MOVE_BY'), 5);
    assert.equal(t.ctx.stop_multicapture, true);
    assert.equal(t.ctx.analyze_counter, 0);
});
test('Preview throttle does not suppress a combined alignment request', t => {
    t.ctx.sendCommandAnalyze(STREAM); t.analyzeReply('ALIGNED');
    t.ctx.sendCommandAnalyze(STREAM);
    assert.equal(t.count('ANALYZE'), 1);
    t.ctx.sendCommandAnalyze(STREAM | ALIGN);
    assert.equal(t.count('ANALYZE'), 2);
    assert.equal(t.ctx.analyze_counter, 5);
});
test('Repeat alignment merged into preview continues alignment and capture', t => {
    t.element('preview-latency-rng').value = '6'; // 3 seconds, above preview throttle.
    t.ctx.sendCommandAnalyze(ALIGN | CAPTURE); t.analyzeReply('SHIFT_REQUIRED');
    t.completedMove();
    t.advance(2600); t.ctx.sendCommandAnalyze(STREAM);
    t.runTimers(); t.analyzeReply('ALIGNED');
    assert.equal(t.count('CAPTURE'), 1, 'repeat flag is merged without ALIGN; aligned result is handled as preview');
});
test('Null path in an error DOWNLOAD is accepted', t => {
    t.element('notify-image-filename-cb').checked = true;
    t.reply('DOWNLOAD', {error: 'Target directory is not specified', file_path: null});
    assert.equal(t.ctx.stop_multicapture, true);
});
test('White to IR with equal exposure sends a new backlight command', t => {
    // Restore the actual function, normally stubbed to keep state tests focused.
    const fresh = {window: t.ctx, document: t.ctx.document};
    vm.createContext(fresh); vm.runInContext(script, fresh);
    t.ctx.adjust_backlight = fresh.adjust_backlight;
    fresh.set_visible = () => {};
    fresh.sendCommand2 = (...args) => t.commands.push(args);
    const colors = t.element('backlight-color-list');
    colors.value = 'white'; colors.options = [{text: 'White', disabled: false}];
    t.element('backlight-exposure').value = '0'; t.element('backlight-ir-exposure').value = '0';
    t.ctx.adjust_backlight(); colors.value = 'ir'; t.ctx.adjust_backlight();
    assert.equal(t.count('SET_BACKLIGHT'), 2);
});

console.log(`\n${passed} passed, ${failed} failed. Tests simulate event ordering; no hardware exercised.`);
process.exitCode = failed ? 1 : 0;
