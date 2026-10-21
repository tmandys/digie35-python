const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../digie35/html/digie35.html'), 'utf8');
function setup() {
    const elements = {'camera-list': {value: 'camera-a'}};
    const calls = [];
    const context = {window: {}, structuredClone, setTimeout() {},
        localStorage: {getItem: () => null},
        Option: function(text, value) {this.text = text; this.value = value;},
        document: {getElementById: id => elements[id] ||= {focus() {}, replaceChildren() {}, add() {}}},
        show_modal() {}, close_modal() {}, get_modal: () => null,
        sendCommand: (...args) => calls.push(args)};
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('        function createCameraProfiles()'),
        html.indexOf('        window.settings =')), context);
    const profiles = context.createCameraProfiles();
    profiles.renderEditor = () => {};
    profiles.renderMetering = () => {};
    profiles.updateSelection = () => {};
    return {profiles, elements, calls, context};
}
function config(id = 'camera-a') {
    const item = {id: 'iso', label: 'ISO', value: '200', choices: ['100', '200']};
    return {camera: {id}, parameters: [item], logical_parameters: [{...item, kind: "logical"}], default_profile: {parameters: [
        {id: 'iso', available: true, camera_parameter: item, default: {set: '100', check: '100'},
            overrides: {focus: {set: '200'}}},
    ]}};
}
test('template preserves inactive values, explicit flags, and empty values', () => {
    const {profiles: p} = setup();
    assert.equal(p.templateValue({set: true, check: false}), undefined);
    assert.equal(p.templateValue({set: false, check: '100'}), '100');
    assert.equal(p.templateValue({value: '', set: true}), '');
    for (const specification of [
        {value: 'f/8', set: false, check: false},
        {value: 'f/8', set: true, check: true},
        {value: '', set: false, check: false},
        {value: '100', set: false, check: true},
    ]) {
        const target = {modes: {}};
        assert.equal(p.addDefaultMode({}, target, 'default', specification), true);
        assert.deepEqual(JSON.parse(JSON.stringify(target.modes.default)), specification);
    }
});

test('general parameters come first and can be added offline with portable values', () => {
    const {profiles: p, elements} = setup();
    p.builtinDefaults = {parameters: [{id: 'aperture', label: 'Aperture', default: {set: 'f/8'}}]};
    p.draft = {parameters: {}};
    p.mode = 'default';
    elements['camera-list'].value = '';
    const select = elements['camera-profile-add-parameter'] = {value: '', options: [],
        replaceChildren(...items) {this.options = items;}, add(item) {this.options.push(item);}};
    p.populateParameterCatalog();
    assert.equal(select.disabled, false);
    assert.equal(select.options[2].value, 'logical:aperture');
    select.value = 'logical:aperture';
    p.addParameter();
    const saved = p.draft.parameters['logical:aperture#0'];
    assert.equal(saved.kind, 'logical');
    assert.equal(saved.modes.default.value, 'f/8');
    p.cameraConfig = {parameters: [{id: 'f-number', label: 'F-Number'}]};
    p.populateParameterCatalog();
    assert.equal(select.options[2].value, 'logical:aperture');
    assert.equal(select.options[4].value, 'f-number#0');
});

test('metering refresh keeps logical and raw values separate', () => {
    const {profiles: p} = setup();
    p.cameraConfig = {parameters: [{id: 'aperture', value: '8'}], logical_parameters: [{id: 'aperture', kind: 'logical', value: 'f/8'}]};
    p.receiveMetering([{id: 'aperture', value: '4'}, {id: 'aperture', kind: 'logical', value: 'f/4'}]);
    assert.equal(p.cameraConfig.parameters[0].value, '4');
    assert.equal(p.catalogItem({id: 'aperture', kind: 'logical'}).value, 'f/4');
});

test('metering order survives saving without reordering camera settings', () => {
    const {profiles: p} = setup();
    p.draft = {parameters: {
        'iso#0': {id: 'iso', display: true, modes: {default: {set: true, value: '100'}}},
        'aperture#0': {id: 'aperture', display: true, modes: {mf: {set: true, value: '8'}}},
        'shutterspeed#0': {id: 'shutterspeed', display: false, modes: {}},
    }};
    const before = JSON.stringify(Object.values(p.draft.parameters).map(item => item.modes));
    p.moveMeteringParameter('aperture#0', -1);
    const saved = JSON.parse(JSON.stringify(p.draft));
    assert.deepEqual(Array.from(p.meteringParameters(saved), ([key]) => key),
        ['aperture#0', 'iso#0', 'shutterspeed#0']);
    assert.deepEqual(Object.keys(saved.parameters), ['iso#0', 'aperture#0', 'shutterspeed#0']);
    assert.equal(JSON.stringify(Object.values(saved.parameters).map(item => item.modes)), before);
});

test('Metering tab edits shared display flags without creating a camera mode', () => {
    const {profiles: p, context} = setup();
    function node() {return {children: [], append(...children) {this.children.push(...children);}};}
    context.document.createElement = node;
    p.draft = {parameters: {'iso#0': {id: 'iso', modes: {default: {value: '100'}}}}};
    const box = node();
    p.renderMeteringEditor(box);
    const checkbox = box.children[1].children[0].children[0];
    checkbox.checked = true;
    checkbox.onchange();
    assert.equal(p.draft.parameters['iso#0'].display, true);
    assert.deepEqual(Object.keys(p.draft.parameters['iso#0'].modes), ['default']);
});

test('metering overlay follows the same display order and excludes unchecked parameters', () => {
    const {profiles: p, elements, context} = setup();
    const actual = context.createCameraProfiles();
    actual.cameraConfig = {parameters: [
        {id: 'iso', value: '100'}, {id: 'aperture', value: '8'}, {id: 'focusmode', value: 'Manual'},
    ]};
    actual.selected = () => ({parameters: {
        iso: {id: 'iso', display: true, display_order: 1},
        aperture: {id: 'aperture', display: true, display_order: 0},
        focus: {id: 'focusmode', display: false},
    }});
    elements['metering-cb'] = {checked: true};
    actual.renderMetering();
    assert.equal(elements['metering-overlay'].textContent, 'f/8 · ISO 100');
});

test('defaults populate after the asynchronous camera catalogue arrives', () => {
    const {profiles: p, calls} = setup();
    p.addFromDefaults();
    assert.equal(Object.keys(p.draft.parameters).length, 0);
    assert.equal(calls[0][0], 'REFRESH_CAMERA_CONFIG');
    assert.equal(calls[0][2].camera_id, 'camera-a');
    p.draft.name = 'My scan profile';
    p.receiveCameraConfig(config());
    assert.equal(p.draft.parameters['logical:iso#0'].modes.default.value, '100');
    assert.equal(p.draft.parameters['logical:iso#0'].logical_id, 'iso');
    assert.equal(p.draft.parameters['logical:iso#0'].modes.focus.value, '200');
    assert.equal(p.draft.name, 'My scan profile');
    assert.equal(p.pendingDefaults, null);
    p.draft.parameters['logical:iso#0'].modes.default.value = '200';
    p.receiveCameraConfig(config());
    assert.equal(p.draft.parameters['logical:iso#0'].modes.default.value, '200');
});
test('metering formats the logical aperture rather than a vendor widget name', () => {
    const {context, elements} = setup();
    const p = context.createCameraProfiles();
    elements['metering-cb'] = {checked: true};
    for (const [id, logical_id] of [['f-number', undefined], ['vendor-aperture', 'aperture']]) {
        p.cameraConfig = {parameters: [{id, value: 'f/4.5'}]};
        p.selected = () => ({parameters: {a: {id, logical_id, display: true, label: 'F-Number'}}});
        p.renderMetering();
        assert.equal(elements['metering-overlay'].textContent, 'f/4.5');
    }
    p.cameraConfig.default_profile = {parameters: [{id: 'aperture', camera_parameter: {id: 'vendor-aperture'}}]};
    assert.equal(p.logicalParameterId({id: 'vendor-aperture'}), 'aperture');
});
test('matching cached defaults populate immediately; previous camera is not reused', () => {
    const {profiles: p, calls} = setup();
    p.cameraConfig = config();
    p.addFromDefaults();
    assert.equal(p.draft.parameters['logical:iso#0'].modes.default.value, '100');
    assert.equal(calls.length, 0);
    p.cameraConfig = config('previous-camera');
    p.addFromDefaults();
    p.receiveCameraConfig(config('previous-camera'));
    assert.equal(Object.keys(p.draft.parameters).length, 0);
    p.receiveCameraConfig(config());
    assert.equal(Object.keys(p.draft.parameters).length, 1);
});
test('late catalogue does not populate a cancelled or replacement draft', () => {
    const {profiles: p} = setup();
    p.addFromDefaults();
    p.cancelEdit();
    p.receiveCameraConfig(config());
    assert.equal(p.draft, null);
    p.cameraConfig = null;
    p.addFromDefaults();
    p.addEmpty();
    p.receiveCameraConfig(config());
    assert.equal(Object.keys(p.draft.parameters).length, 0);
});
test('defaults can be loaded without a camera, including unavailable settings', () => {
    const {profiles: p, elements, calls} = setup();
    elements['camera-list'].value = '';
    p.addFromDefaults();
    assert.equal(calls[0][0], 'LIST_CAMERA_PROFILES');
    const defaults = config().default_profile;
    defaults.parameters[0].available = false;
    defaults.parameters[0].camera_parameter = null;
    p.receive({profiles: [], default_profile: defaults});
    assert.equal(p.draft.parameters['logical:iso#0'].modes.default.value, '100');
    assert.equal(p.draft.parameters['logical:iso#0'].modes.focus.value, '200');
    p.addFromDefaults();
    assert.equal(calls.length, 1);
    assert.equal(p.draft.parameters['logical:iso#0'].modes.default.value, '100');
});
test('camera-mode choices refresh on demand without replacing the draft or editor', () => {
    const {profiles: p, calls} = setup();
    p.cameraConfig = config();
    p.addFromDefaults();
    const parameter = p.draft.parameters['logical:iso#0'];
    const setting = parameter.modes.default;
    const select = {isConnected: true, replaceChildren(...options) {this.options = options;}};
    p.renderEditor = () => assert.fail('Choice refresh must not rebuild the editor');
    p.refreshParameterChoices(select, parameter, setting);
    assert.equal(calls[0][0], 'REFRESH_CAMERA_CONFIG');
    const fresh = config();
    fresh.logical_parameters[0].choices = ['200', '400'];
    p.receiveCameraConfig(fresh);
    assert.deepEqual(Array.from(select.options, option => option.value), ['100', '200', '400']);
    assert.equal(select.value, '100');
    assert.equal(setting.value, '100');
});
test('late choice response does not change the newly selected editor mode', () => {
    const {profiles: p} = setup();
    p.cameraConfig = config();
    p.addFromDefaults();
    const parameter = p.draft.parameters['logical:iso#0'];
    p.refreshParameterChoices({isConnected: false, replaceChildren() {assert.fail('Stale select');}}, parameter, parameter.modes.default);
    p.selectMode('focus');
    p.renderEditor = () => assert.fail('Late response must not reset the editor');
    p.receiveCameraConfig(config());
    assert.equal(p.mode, 'focus');
    assert.equal(parameter.modes.focus.value, '200');
});

test('mode transition sends selected mapping and the actual Focus target to the server', () => {
    const {profiles: p, context, calls} = setup();
    context.localStorage.setItem = () => {};
    context.adjust = () => {};
    context.cameraMappings = {selected: () => ({id: 'selected-mapping'})};
    p.selectedMode = () => 'focus';
    p.profileId = () => 'selected-profile';
    p.applySelectedMode('camera-a');
    assert.equal(calls[0][0], 'APPLY_CAMERA_PROFILE');
    assert.equal(calls[0][2].mapping_id, 'selected-mapping');
    assert.equal(calls[0][2].mode, 'focus');
});

