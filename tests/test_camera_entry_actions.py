"""Execute actual entry-action/profile code without gphoto2 or camera hardware."""
import ast
import logging
import re
from pathlib import Path
from types import SimpleNamespace
import unittest
from digie35.camera_actions import PROFILE_ENTRY_ACTIONS, validate_camera_action_steps
from digie35.camera_parameters import camera_value, logical_value

path = Path(__file__).resolve().parents[1] / 'digie35' / 'digie35_server.py'
tree = ast.parse(path.read_text(encoding='utf-8'))
names = {'_resolve_logical_parameter', 'run_camera_action', 'enter_camera_profile', 'apply_camera_profile', '_apply_camera_profile_open',
         '_check_camera_profile_open', '_profile_mode_setting', 'set_camera'}
methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
ns = {'camera_value': camera_value, 'logical_value': logical_value, 'CameraControlError': RuntimeError, 'PROFILE_ENTRY_ACTIONS': PROFILE_ENTRY_ACTIONS,
      'validate_camera_action_steps': validate_camera_action_steps, 'logging': logging, 're': re,
      'time': SimpleNamespace(sleep=lambda seconds: None),
      'gp': SimpleNamespace(GP_OK=0, gp_widget_get_child_by_name=lambda config, name: (0, config[name]))}
class GPhotoError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f'gphoto error {code}')
ns['gp'].GPhoto2Error = GPhotoError
ns['gp'].GP_ERROR_CAMERA_BUSY = -110
exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), ns)
for name in ('GP_OPERATION_CAPTURE_PREVIEW', 'GP_OPERATION_CAPTURE_IMAGE', 'GP_OPERATION_CAPTURE_VIDEO',
             'GP_OPERATION_CAPTURE_AUDIO', 'GP_OPERATION_CONFIG', 'GP_OPERATION_TRIGGER_CAPTURE',
             'GP_FILE_OPERATION_DELETE', 'GP_FILE_OPERATION_PREVIEW', 'GP_FILE_OPERATION_RAW',
             'GP_FILE_OPERATION_AUDIO', 'GP_FILE_OPERATION_EXIF', 'GP_FOLDER_OPERATION_DELETE_ALL',
             'GP_FOLDER_OPERATION_PUT_FILE', 'GP_FOLDER_OPERATION_MAKE_DIR', 'GP_FOLDER_OPERATION_REMOVE_DIR'):
    setattr(ns['gp'], name, 1)


class Fake:
    def __init__(self):
        self._capture_in_progress = False
        self.locked = False
        self.events = []
        self.values = {'auto': 1, 'aperture': '8', 'after': 0}
        self.readonly = set()
        def widget(name):
            return SimpleNamespace(get_value=lambda: self.values[name],
                get_readonly=lambda: name in self.readonly,
                set_value=lambda value: (self.values.update({name: value}), self.events.append((name, value))))
        self._camera = SimpleNamespace(get_config=lambda: {name: widget(name) for name in self.values},
            get_single_config=widget, set_config=lambda config: None,
            set_single_config=lambda name, widget: None)

    def _acquire_capture_lock(self, *args):
        if self.locked:
            raise AssertionError('Nested camera lock')
        self.locked = True

    def _release_capture_lock(self, *args):
        self.locked = False

    def _open_camera(self, camera_id): pass
    def _close_camera(self): pass
    def _broadcast_capture_status_from_event(self): pass
    def _read_camera_config_catalog(self): pass
    def get_metering_values(self):
        return [{'id': name, 'occurrence': 0, 'value': value} for name, value in self.values.items()]
    _camera_config_value = staticmethod(lambda value: value)


for name in names:
    setattr(Fake, name, staticmethod(ns[name]) if name == '_profile_mode_setting' else ns[name])


class EntryTests(unittest.TestCase):
    def test_check_accepts_every_alias_even_when_choices_only_offer_another(self):
        camera = Fake()
        camera._match_default_camera_profile = lambda: {'parameters': [{'id': 'focus_mode',
            'mapping': {'values': {'manual_focus': ['Manual', 'Manual Focus']}},
            'camera_parameter': {'id': 'auto', 'choices': ['Manual']}}]}
        profile = {'parameters': {'focus': {'id': 'focus_mode', 'kind': 'logical',
            'modes': {'default': {'check': True, 'value': 'manual_focus'}}}}}
        for actual, ok in [('Manual', True), ('Manual Focus', True), ('DMF', False)]:
            camera.values['auto'] = actual
            result = camera._check_camera_profile_open(profile, 'mf')
            self.assertEqual(result['ok'], ok)
            self.assertEqual(result['errors'], [])

    def test_logical_profile_apply_and_check_use_runtime_translation(self):
        camera = Fake()
        camera._match_default_camera_profile = lambda: {'parameters': [{'id': 'aperture',
            'mapping': {'number_format': 'f/%f'},
            'camera_parameter': {'id': 'aperture', 'choices': ['8', '2.8']}}]}
        profile = {'parameters': {'logical:aperture#0': {'id': 'aperture', 'kind': 'logical',
            'modes': {'default': {'set': True, 'check': True, 'value': 'f/2.8'}}}}}
        result = camera.apply_camera_profile(profile, 'camera', 'mf')
        self.assertEqual(camera.values['aperture'], '2.8')
        self.assertTrue(result['check']['ok'])
        self.assertEqual(result['check']['checked'][0]['actual'], 'f/2.8')
        self.assertEqual(profile['parameters']['logical:aperture#0']['modes']['default']['value'], 'f/2.8')
        profile['parameters']['raw'] = {'id': 'aperture'}
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            camera._resolve_logical_parameter(profile['parameters']['logical:aperture#0'], 'f/8', profile)

    def test_action_mode_restriction_before_camera_access(self):
        camera = Fake()
        mapping = {'actions': {'autofocus': {'modes': ['af'], 'steps': [{'delay_ms': 0}]}}}
        for mode in ('mf', 'focus', None):
            with self.assertRaisesRegex(RuntimeError, 'not available in mode'):
                camera.run_camera_action('camera', mapping, 'autofocus', mode=mode)
            self.assertFalse(camera.locked)
        camera.run_camera_action('camera', mapping, 'autofocus', mode='af')
        mapping['actions']['autofocus']['modes'] = ['mf']
        camera.run_camera_action('camera', mapping, 'autofocus', mode='focus')

    def test_ev_check_accepts_numeric_zero_and_distinguishes_unavailable(self):
        profile = {'parameters': {'ev': {'id': 'exposurecompensation', 'modes': {
            'default': {'check': True, 'value': '0'}}}}}
        for value, category in [('0', 'checked'), ('0.000000', 'checked'), ('-0.0', 'checked'),
                                ('0.333', 'mismatches'), ('unknown', 'errors'), (None, 'errors'), ('nan', 'errors')]:
            camera = Fake()
            camera.values['exposurecompensation'] = value
            report = camera._check_camera_profile_open(profile, 'mf')
            self.assertEqual(len(report[category]), 1, value)
            self.assertEqual(camera.events, [])
        camera = Fake()
        report = camera._check_camera_profile_open(profile, 'mf')
        self.assertEqual(len(report['errors']), 1)
        self.assertEqual(report['mismatches'], [])

    def test_profile_retries_busy_single_value_without_replaying_earlier_writes(self):
        camera = Fake()
        writes = []
        def write(name, widget):
            writes.append(name)
            if name == 'aperture' and writes.count(name) < 3:
                raise GPhotoError(-110)
        camera._camera.set_single_config = write
        profile = {'parameters': {name: {'id': name, 'modes': {'mf': {'set': True, 'value': value}}}
                                 for name, value in [('auto', 0), ('aperture', '4')]}}
        report = camera.apply_camera_profile(profile, 'camera-a', 'mf')
        self.assertEqual(writes, ['auto', 'aperture', 'aperture', 'aperture'])
        self.assertEqual([item['id'] for item in report['set']], ['auto', 'aperture'])
        self.assertEqual(report['errors'], [])
        self.assertFalse(camera.locked)

    def test_profile_busy_retries_are_bounded_and_other_errors_are_not_retried(self):
        for code, count in [(-110, 21), (-1, 1)]:
            camera = Fake()
            writes = []
            def write(name, widget):
                writes.append(name)
                raise GPhotoError(code)
            camera._camera.set_single_config = write
            with self.assertLogs(level='ERROR'):
                report = camera.apply_camera_profile(self.profile(), 'camera-a', 'focus')
            self.assertEqual(writes, ['aperture'] * count)
            self.assertEqual(report['set'], [])
            self.assertEqual(report['errors'][0]['id'], 'aperture')
            self.assertFalse(camera.locked)

    def test_failed_mapping_step_reports_context_and_stops_sequence(self):
        camera = Fake()
        def fail(config):
            raise RuntimeError('[-110] I/O in progress')
        camera._camera.set_config = fail
        with self.assertRaisesRegex(RuntimeError, r"enter_mf, step 1/4:.*auto.*I/O in progress"):
            camera.enter_camera_profile(self.profile(), 'camera-a', 'mf', self.mapping())
        self.assertEqual(camera.events, [('auto', 0)])
        self.assertFalse(camera.locked)
        self.assertFalse(camera._capture_in_progress)

    def test_open_action_runs_in_same_session_before_returning_config(self):
        for mapping in (None, {'actions': {}}, {'actions': {'after_open': {'steps': [{'id': 'after', 'value': 1}]}}}):
            camera = Fake()
            camera._camera_model, camera._camera_id, camera._camera_battery = 'Canon', 'camera-a', 100
            camera._camera_config_catalog = []
            camera._camera_abilities = SimpleNamespace(device_type=0, status=0, library='', operations=0,
                                                       file_operations=0, folder_operations=0)
            sessions = []
            camera._open_camera = lambda camera_id: sessions.append('open')
            camera._close_camera = lambda: sessions.append('close')
            camera.get_camera_config = lambda: dict(camera.values)
            result = camera.set_camera('camera-a', include_config=True, mapping=mapping)
            has_action = bool(mapping and mapping['actions'])
            self.assertEqual(result['camera_config']['after'], int(has_action))
            self.assertEqual(sessions, ['open', 'open', 'close', 'close'] if has_action else ['open', 'close'])
            self.assertFalse(camera.locked)

    def profile(self):
        return {'parameters': {'aperture': {'id': 'aperture', 'modes': {
            mode: {'set': True, 'check': True, 'value': value}
            for mode, value in [('mf', '8'), ('focus', '2.8'), ('af', '11')]}}}}

    def mapping(self):
        return {'id': 'camera-mapping', 'actions': {name: {'steps': [
            {'id': 'auto', 'value': 0}, {'apply_profile': True}, {'delay_ms': 10}, {'id': 'after', 'value': 1}
        ]} for name in ('enter_mf', 'enter_af')}}

    def test_target_mode_controls_parameters_and_sequence_is_flat(self):
        for mode, value, action in [('mf', '8', 'enter_mf'), ('focus', '2.8', 'enter_mf'), ('af', '11', 'enter_af')]:
            with self.subTest(mode=mode):
                camera = Fake()
                camera.values['aperture'] = '16'
                result = camera.enter_camera_profile(self.profile(), 'camera-a', mode, self.mapping())
                self.assertEqual(camera.events, [('auto', 0), ('aperture', value), ('after', 1)])
                self.assertEqual(result['actions'][0]['action'], action)
                self.assertTrue(result['check']['ok'])
                metering = {item['id']: item['value'] for item in result['metering']}
                self.assertEqual(metering['aperture'], value)
                self.assertEqual(metering['after'], 1)
                self.assertFalse(camera.locked)
                self.assertFalse(camera._capture_in_progress)

    def test_no_entry_action_falls_back_to_parameters_only(self):
        for mapping in (None, {'actions': {}}):
            camera = Fake()
            result = camera.enter_camera_profile(self.profile(), 'camera-a', 'focus', mapping)
            self.assertEqual(camera.events, [('aperture', '2.8')])
            self.assertEqual(next(item['value'] for item in result['metering'] if item['id'] == 'aperture'), '2.8')

    def test_profile_failure_stops_later_steps_and_releases_lock(self):
        camera = Fake()
        camera.readonly.add('aperture')
        with self.assertRaisesRegex(RuntimeError, 'remaining mapping steps'):
            camera.enter_camera_profile(self.profile(), 'camera-a', 'focus', self.mapping())
        self.assertEqual(camera.events, [('auto', 0)])
        self.assertFalse(camera.locked)
        self.assertFalse(camera._capture_in_progress)

    def test_check_mismatch_reports_warning_and_runs_remaining_steps(self):
        camera = Fake()
        profile = self.profile()
        profile['parameters']['aperture']['modes']['af']['set'] = False
        result = camera.enter_camera_profile(profile, 'camera-a', 'af', self.mapping())
        self.assertEqual(camera.events, [('auto', 0), ('after', 1)])
        self.assertFalse(result['check']['ok'])
        mismatch = result['check']['mismatches'][0]
        self.assertEqual((mismatch['actual'], mismatch['expected']), ('8', '11'))
        self.assertEqual(result['errors'], [])
        self.assertFalse(camera.locked)
        self.assertFalse(camera._capture_in_progress)

    def test_invalid_or_recursive_actions_are_rejected_before_execution(self):
        for steps in ([], [{'action': 'enter_mf'}], [{'apply_profile': True}, {'apply_profile': True}],
                      [{'id': 'auto', 'value': 0}], [{'apply_profile': True, 'action': 'enter_mf'}]):
            camera = Fake()
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                camera.enter_camera_profile(self.profile(), 'camera-a', 'mf',
                    {'actions': {'enter_mf': {'steps': steps}}})
            self.assertEqual(camera.events, [])
            self.assertFalse(camera.locked)

    def test_profile_step_requires_matching_entry_context(self):
        camera = Fake()
        with self.assertRaises(RuntimeError):
            camera.run_camera_action('camera-a', self.mapping(), 'enter_mf')
        with self.assertRaises(RuntimeError):
            camera.run_camera_action('camera-a', self.mapping(), 'enter_mf', self.profile(), 'af')
        self.assertEqual(camera.events, [])


if __name__ == '__main__': unittest.main()
