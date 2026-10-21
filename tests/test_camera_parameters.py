import unittest
from digie35.camera_parameters import camera_value, logical_value, logical_catalog


class ParameterTests(unittest.TestCase):
    def test_aliases_select_first_supported_and_read_back_all_variants(self):
        mapping = {'values': {'manual_focus': ['Manual', 'Manual Focus']}}
        self.assertEqual(camera_value(mapping, 'manual_focus', {'choices': ['Manual Focus', 'Manual']}), 'Manual')
        self.assertEqual(camera_value(mapping, 'manual_focus', {'choices': ['Manual Focus']}), 'Manual Focus')
        for alias in ('Manual', 'Manual Focus'):
            self.assertEqual(logical_value(mapping, alias), 'manual_focus')
        for choices in ([], ['DMF']):
            with self.assertRaises(ValueError):
                camera_value(mapping, 'manual_focus', {'choices': choices})

    def test_aperture_translates_per_camera_and_rejects_unsupported_choice(self):
        self.assertEqual(camera_value({'number_format': 'f/%f'}, 'f/8', {'choices': ['4.5', '8.0']}), '8.0')
        self.assertEqual(camera_value({}, 'f/8', {'choices': ['f/4.5', 'f/8']}), 'f/8')
        with self.assertRaisesRegex(ValueError, 'No camera choice'):
            camera_value({}, 'f/2.8', {'choices': ['f/4.5', 'f/8']})
        self.assertEqual(logical_value({'number_format': 'f/%f'}, '8.0'), 'f/8')

    def test_shutter_rounding_and_range(self):
        self.assertEqual(camera_value({'value_type': 'shutter_speed'}, '1/60', {'choices': ['0.0167s', '0.02s']}), '0.0167s')
        item = {'type_name': 'range', 'range': {'minimum': 2500, 'maximum': 9900, 'increment': 100}}
        self.assertEqual(camera_value({}, '5000', item), 5000)
        for value in ('0', '5050', 'nan'):
            with self.assertRaises(ValueError):
                camera_value({}, value, item)

    def test_logical_catalog_preserves_readonly_and_translates_current_and_choices(self):
        result = logical_catalog({'parameters': [{'id': 'exposure_mode', 'label': 'Exposure mode',
            'mapping': {'values': {'Av': 'A', 'M': 'M'}},
            'camera_parameter': {'id': 'expprogram', 'value': 'A', 'choices': ['A', 'M'], 'readonly': True}}]})
        self.assertEqual(result[0]['value'], 'Av')
        self.assertEqual(result[0]['choices'], ['Av', 'M'])
        self.assertTrue(result[0]['readonly'])
        self.assertEqual(result[0]['kind'], 'logical')
