import unittest

import numpy as np

from digie35.backlight_analyzer import measure_mosaic, summarize


class BacklightTests(unittest.TestCase):
    def measure(self, image, **kwargs):
        return measure_mosaic(image, [[0,1],[3,2]], [100]*4, [1100]*4,
                              columns=8, rows=6, **kwargs)

    def test_flat_field_with_different_channel_gains(self):
        image = np.full((240,320),500.)
        image[::2,::2] = 700
        image[1::2,1::2] = 300
        result = self.measure(image)
        for data in result['channels'].values():
            self.assertAlmostEqual(data['statistics']['cv_percent'],0)
            self.assertAlmostEqual(data['statistics']['p5_p95_uniformity_percent'],100)
        self.assertAlmostEqual(result['ratios']['R/G']['statistics']['mean'],1.5,places=5)
        self.assertAlmostEqual(result['combined']['statistics']['mean'],.4,places=5)

    def test_gradient_and_roi(self):
        image = np.tile(np.linspace(300,800,320),(240,1))
        full = self.measure(image)['channels']['G']['statistics']
        crop = self.measure(image,roi=(.25,.25,.75,.75))['channels']['G']['statistics']
        self.assertGreater(full['cv_percent'],crop['cv_percent'])
        self.assertLess(full['corners_relative_to_center_percent']['top_left'],100)
        self.assertGreater(full['corners_relative_to_center_percent']['top_right'],100)

    def test_clipping_not_hidden_by_median(self):
        image = np.full((240,320),500.)
        image[0,0] = 1100
        result = self.measure(image)
        self.assertIn('clipped_samples',result['channels']['R']['flags'])
        self.assertNotIn('R/G',result['ratios'])
        self.assertIn('clipped_samples', result['combined']['source_flags'])

    def test_dark_channel_has_no_misleading_uniformity(self):
        result = self.measure(np.full((240,320),100.))
        self.assertIsNone(result['channels']['G']['statistics'])
        self.assertEqual(result['ratios'],{})
        self.assertIsNone(result['combined']['statistics'])

    def test_combined_signal_preserves_channel_strength(self):
        image = np.full((240,320),500.)
        image[::2,::2] = np.linspace(200,800,160)[None,:]
        result = self.measure(image)
        expected = np.mean([result['channels'][c]['grid'] for c in 'RGB'],axis=0)
        np.testing.assert_allclose(result['combined']['grid'],expected)
        self.assertGreater(result['combined']['statistics']['cv_percent'],0)
        self.assertLess(result['combined']['statistics']['cv_percent'],result['channels']['R']['statistics']['cv_percent'])

    def test_invalid_roi_and_pattern(self):
        image = np.ones((240,320))
        with self.assertRaises(ValueError):
            self.measure(image,roi=(.9,0,.1,1))
        with self.assertRaises(ValueError):
            measure_mosaic(image,[[0]], [100]*4,[1100]*4)
        with self.assertRaises(ValueError):
            summarize(np.zeros((3,3)))


if __name__ == '__main__':
    unittest.main()
