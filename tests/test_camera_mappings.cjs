const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../digie35/html/digie35.html'), 'utf8');
function element() {
    return {children: [], options: [], value: '', isConnected: true, style: {},
        append(...items) {this.children.push(...items);},
        add(item) {this.options.push(item);},
        replaceChildren(...items) {this.children = items; this.options = items;}};
}
function setup() {
    const elements = {'camera-list': {...element(), value: 'camera-a'},
        'camera-mapping-add-step': {...element(), value: 'set', options: [{value: 'set'}, {value: 'delay'}]}};
    const calls = [], timers = [];
    const context = {window: {}, cameraProfiles: {cameraConfig: {camera: {id: 'camera-a'},
        parameters: [{id: 'iso', choices: ['100', '200']}, {id: 'readonly', readonly: true, choices: ['1']}] }},
        document: {getElementById: id => elements[id] ||= element(), createElement: () => element(),
            querySelectorAll: () => []},
        Option: function(text, value) {this.text = text; this.value = value;},
        sendCommand: (...args) => calls.push(args), setTimeout: fn => timers.push(fn),
        get_modal: () => null, show_modal() {}, close_modal() {}, structuredClone};
    const start = html.indexOf('        window.cameraMappings = {');
    vm.createContext(context);
    vm.runInContext(html.slice(start, html.indexOf('\n        };', start) + 11), context);
    const mapping = context.window.cameraMappings;
    mapping.draft = {actions: {focus: {steps: []}}};
    mapping.action = 'focus';
    return {mapping, elements, context, calls, timers};
}
test('camera opening sends selected mapping or saved mapping before the list arrives', () => {
    const {mapping: m, context, calls} = setup();
    context.localStorage = {getItem: () => 'saved-mapping'};
    m.openCamera();
    assert.equal(calls[0][0], 'SET_CAMERA');
    assert.equal(calls[0][2].mapping_id, 'saved-mapping');
    assert.equal(calls[0][2].include_config, true);
    m.selected = () => ({id: 'selected-mapping'});
    m.openCamera();
    assert.equal(calls[1][2].mapping_id, 'selected-mapping');
    assert.equal(calls[1][2].include_config, true);
});

test('toggle labels stay On/Off after refreshing choices and retain numeric values', () => {
    const {mapping: m, context, elements} = setup();
    context.cameraProfiles.cameraConfig.parameters.push({id: 'af', type_name: 'toggle', value: 0});
    const step = {id: 'af', value: 1};
    m.draft.actions.focus.steps = [step];
    m.renderSteps();
    const value = elements['camera-mapping-steps'].children[0].children[0].children[1];
    assert.deepEqual(Array.from(value.options, item => item.text), ['Off', 'On']);
    m.refreshChoices(value, step, 'value');
    m.receiveConfigChoices();
    assert.deepEqual(Array.from(value.options, item => item.text), ['Off', 'On']);
    assert.equal(value.value, '1');
    value.value = '0';
    value.onchange();
    assert.equal(step.value, 0);
});

test('reopening remembers the selected action separately for each mapping', () => {
    const {mapping: m} = setup();
    const a = {id: 'a', actions: {meter_exposure: {steps: []}, autofocus: {steps: []}}};
    const b = {...structuredClone(a), id: 'b'};
    m.draft = structuredClone(a);
    m.open(true);
    m.selectAction('autofocus');
    m.draft = structuredClone(b);
    m.open(true);
    assert.equal(m.action, 'meter_exposure');
    m.draft = structuredClone(a);
    m.open(true);
    assert.equal(m.action, 'autofocus');
    delete m.draft.actions.autofocus;
    m.open(true);
    assert.equal(m.action, 'meter_exposure');
});

test('AE and AF use the same mapping command and busy lifecycle', () => {
    for (const action of ['meter_exposure', 'autofocus']) {
        const {mapping: m, context, calls} = setup();
        context.adjust = () => {};
        m.selected = () => ({id: 'canon', actions: {[action]: {steps: [{id: 'eosremoterelease', value: 'Press Half'}]}}});
        m.runAction(action);
        assert.equal(calls[0][0], 'RUN_CAMERA_ACTION');
        assert.equal(calls[0][2].action, action);
        assert.equal(context.window.camera_action_in_progress, true);
        assert.equal(context.window.camera_capture_in_progress, true);
    }
});

test('mode restrictions block actions, include MF Assist, and preserve Wait-only actions', () => {
    const {mapping: m, context, calls, elements} = setup();
    context.adjust = () => {};
    let mode = 'mf';
    context.window.cameraProfiles = {selectedMode: () => mode};
    const definition = {modes: ['af'], steps: [{delay_ms: 0}]};
    m.selected = () => ({id: 'sony', actions: {autofocus: definition}});
    m.runAction('autofocus');
    assert.equal(calls.length, 0);
    mode = 'af';
    m.runAction('autofocus');
    assert.equal(calls[0][2].mode, 'af');
    definition.modes = ['mf'];
    mode = 'focus';
    assert.equal(m.modeAllowed(definition), true);
    mode = 'af';
    assert.equal(m.modeAllowed(definition), false);
    m.draft.actions.focus = definition;
    m.renderSteps();
    assert.equal(elements['camera-mapping-modes'].value, 'mf');
    m.setModes('');
    assert.equal(definition.modes, undefined);
    assert.equal(m.modeAllowed(definition), true);
    m.readOnly = true;
    m.setModes('mf');
    assert.equal(definition.modes, undefined);
});

test('parameter addition is disabled without the selected camera catalogue; Wait still works', () => {
    const {mapping: m, elements, context} = setup();
    elements['camera-list'].value = '';
    m.renderSteps();
    assert.equal(elements['camera-mapping-add-step'].options[0].disabled, true);
    assert.equal(elements['camera-mapping-add-step'].value, 'delay');
    m.addStep();
    assert.equal(m.draft.actions.focus.steps[0].delay_ms, 800);
    elements['camera-mapping-add-step'].value = 'set';
    m.addStep();
    assert.equal(m.draft.actions.focus.steps.length, 1);
    elements['camera-list'].value = 'other-camera';
    m.updateAddStep();
    assert.equal(elements['camera-mapping-add-step'].options[0].disabled, true);
    elements['camera-list'].value = 'camera-a';
    context.cameraProfiles.cameraConfig.parameters[0].readonly = true;
    m.updateAddStep();
    assert.equal(elements['camera-mapping-add-step'].options[0].disabled, true);
});
test('new parameter step has an enabled selector; missing choices are explicitly disabled', () => {
    const {mapping: m, elements} = setup();
    m.addStep();
    const row = elements['camera-mapping-steps'].children[0];
    const select = row.children[0].children[0];
    assert.equal(select.disabled, false);
    assert.equal(select.options[0].disabled, true);
    assert.equal(select.options[1].value, 'iso');
    assert.equal(select.options.length, 2);
    select.value = 'iso';
    select.onchange();
    assert.equal(m.draft.actions.focus.steps[0].id, 'iso');
    m.populateChoices(select, {id: 'missing'}, 'parameter');
    assert.equal(select.options[0].disabled, true);
    assert.equal(select.disabled, false);
});
test('opening mapping choices refreshes camera catalogue without resetting values or step order', () => {
    const {mapping: m, context, calls} = setup();
    const step = {id: 'iso', value: '100'};
    m.draft.actions.focus.steps = [step, {delay_ms: 800}];
    const select = element();
    m.bindChoiceRefresh(select, step, 'value');
    select.onpointerdown();
    assert.equal(calls[0][0], 'REFRESH_CAMERA_CONFIG');
    context.cameraProfiles.cameraConfig.parameters[0].choices = ['200', '400'];
    assert.equal(m.receiveConfigChoices(), true);
    assert.deepEqual(Array.from(select.options, option => option.value), ['100', '200', '400']);
    assert.equal(step.value, '100');
    assert.equal(m.draft.actions.focus.steps[1].delay_ms, 800);
    assert.equal(select.value, '100');
});
test('late refresh and timeout cannot edit another mapping action', () => {
    const {mapping: m, timers} = setup();
    const select = element();
    m.refreshChoices(select, {id: 'iso', value: '100'}, 'value');
    m.action = 'other';
    assert.equal(m.receiveConfigChoices(), true);
    assert.equal(select.options.length, 0);
    m.refreshChoices(select, {id: 'iso', value: '100'}, 'value');
    timers.at(-1)();
    assert.equal(m.pendingChoices, null);
});

test('mapping action selector uses the shared labels and preserves older custom actions', () => {
    const {mapping: m, elements} = setup();
    m.actionLabels = {after_open: 'After camera open', meter_exposure: 'Meter exposure'};
    m.draft.actions.custom_action = {steps: []};
    m.action = 'after_open';
    m.renderActionOptions();
    const select = elements['camera-mapping-action'];
    assert.equal(select.value, 'after_open');
    assert.equal(select.options[0].text, 'After camera open');
    assert.ok(select.options.some(option => option.value === 'custom_action'));
});

test('entry action starts with one profile step and allows explicit reordering', () => {
    const {mapping: m, elements} = setup();
    m.entryActions = {mf: 'enter_mf', focus: 'enter_mf', af: 'enter_af'};
    const add = elements['camera-mapping-add-step'];
    m.selectAction('enter_mf');
    const steps = m.draft.actions.enter_mf.steps;
    assert.equal(steps[0].apply_profile, true);
    add.value = 'delay';
    m.addStep();
    m.moveStep(1, -1);
    assert.equal(steps[0].delay_ms, 800);
    assert.equal(steps[1].apply_profile, true);
    add.value = 'profile';
    m.addStep();
    assert.equal(steps.length, 2);
    m.selectAction('meter_exposure');
});

test('missing and duplicate mandatory steps can be repaired but cannot be saved', () => {
    const {mapping: m, elements, calls} = setup();
    m.entryActions = {mf: 'enter_mf'};
    m.action = 'enter_mf';
    m.draft.actions = {enter_mf: {steps: []}};
    elements['camera-mapping-name'] = {value: 'Repair'};
    m.renderSteps();
    assert.equal(m.draft.actions.enter_mf.steps.length, 0);
    assert.ok(elements['camera-mapping-steps'].children.some(item => item.textContent === 'Restore Apply profile parameters'));
    m.save();
    assert.equal(calls.length, 0);
    m.restoreProfileStep();
    m.restoreProfileStep();
    assert.equal(m.draft.actions.enter_mf.steps.length, 1);
    const row = elements['camera-mapping-steps'].children[0];
    assert.equal(row.children[0].children.at(-1).children.length, 2); // move buttons only
    m.draft.actions.enter_mf.steps.push({apply_profile: true});
    m.renderSteps();
    m.save();
    assert.equal(calls.length, 0);
    const duplicate = elements['camera-mapping-steps'].children[1];
    duplicate.children[0].children.at(-1).children.at(-1).onclick();
    assert.equal(m.draft.actions.enter_mf.steps.length, 1);
});

test('built-in View reuses the editor without mutation; Copy restores editing', () => {
    const {mapping: m, elements, calls} = setup();
    const builtin = {id: 'builtin', name: 'Built-in camera', schema_version: 1,
        actions: {meter_exposure: {steps: [{id: 'iso', value: '100'}, {delay_ms: 800}]},
            autofocus: {steps: [{id: 'iso', value: '200'}]}}};
    m.builtins = [builtin];
    m.actionLabels = {meter_exposure: 'Meter exposure', autofocus: 'Autofocus', unused: 'Unused'};
    m.selected = () => builtin;
    m.edit();
    assert.equal(m.readOnly, true);
    assert.equal(elements['camera-mapping-steps'].disabled, true);
    assert.equal(elements['camera-mapping-name'].readOnly, true);
    assert.deepEqual(Array.from(elements['camera-mapping-action'].options, item => item.value), ['meter_exposure', 'autofocus']);
    m.selectAction('autofocus');
    assert.equal(elements['camera-mapping-steps'].children.length, 1);
    const before = JSON.stringify(m.draft);
    m.addStep(); m.moveStep(0, 1); m.removeAction(); m.restoreProfileStep(); m.save();
    assert.equal(JSON.stringify(m.draft), before);
    assert.equal(calls.length, 0);
    assert.equal(builtin.actions.meter_exposure.steps.length, 2);
    m.copy();
    assert.equal(m.readOnly, false);
    assert.equal(elements['camera-mapping-steps'].disabled, false);
    assert.equal(elements['camera-mapping-name'].readOnly, false);
    assert.equal(m.draft.id, undefined);
    elements['camera-mapping-add-step'].value = 'delay';
    m.addStep();
    assert.equal(m.draft.actions.meter_exposure.steps.length, 3);
    assert.equal(builtin.actions.meter_exposure.steps.length, 2);
});
