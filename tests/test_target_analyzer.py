import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from digie35.target_analyzer import analyze, detect_squares, load_image, measure_edge, main, load_reference, apply_reference, analyze_geometry
from digie35.target_analyzer import measure_focus_score


def chart():
    image = np.full((1000, 1500), .8, np.float32)
    for row in range(7):
        for col in range(9):
            if (row, col) in {(1, 1), (1, 7), (5, 1), (5, 7)}:
                continue
            box = cv2.boxPoints(((90 + col * 165, 70 + row * 140), (62, 62), 5))
            cv2.fillConvexPoly(image, np.rint(box).astype(np.int32), .2)
    return image


class TargetAnalyzerTests(unittest.TestCase):
    def test_focus_matches_online_formula_and_roi(self):
        rgb = np.zeros((140, 160, 3), np.uint8)
        rgb[::2, :, 0] = 200
        rgb[:, ::2, 1] = 40
        result = measure_focus_score(rgb, [159, 139])
        self.assertEqual(result['bounds'], [64, 44, 96, 96])
        expected = [float(cv2.Laplacian(rgb[44:140, 64:160, i], cv2.CV_64F).var()) for i in range(3)]
        self.assertEqual(result['focus_score'], max(expected))
        self.assertEqual(result['focus_channel'], 'red')
        self.assertEqual(list(result['focus_scores'].values()), expected)
        flat = measure_focus_score(np.full((40, 50, 3), 100, np.uint8), [25, 20])
        self.assertEqual(flat['bounds'], [0, 0, 50, 40])
        self.assertEqual(flat['focus_score'], 0)

    def geometry_points(self, transform):
        points = []
        for row in range(7):
            for column in range(9):
                source = [column/8, row/6]
                center = cv2.perspectiveTransform(np.array([[source]], float), transform)[0, 0]
                points.append(dict(row=row, column=column, center_px=center.tolist(),
                                   reference_center_normalized=source))
        return points

    def test_geometry_rotation_without_perspective(self):
        for angle in (-2., 0., 3.):
            rad = np.radians(angle)
            h = np.array([[1200*np.cos(rad), -800*np.sin(rad), 100],
                          [1200*np.sin(rad), 800*np.cos(rad), 100], [0, 0, 1.]])
            result = analyze_geometry(self.geometry_points(h))
            self.assertAlmostEqual(result['rotation_horizontal_mean_deg'], angle, places=4)
            self.assertAlmostEqual(result['width_change_percent'], 0, places=4)
            self.assertAlmostEqual(result['height_change_percent'], 0, places=4)
            self.assertAlmostEqual(result['side_lengths_px']['left'], 800, places=3)

    def test_geometry_known_trapezoid_and_sensitivity(self):
        # Analytic corners: (0,0), (1200,0), (1000,~666.67), (0,~666.67).
        h = np.array([[1200., 0, 0], [0, 800, 0], [0, .2, 1]])
        points = self.geometry_points(h)
        result = analyze_geometry(points, use_reference=True)
        self.assertAlmostEqual(result['width_change_percent'], -200/11, places=4)
        self.assertLess(result['projective_rms_px'], .001)
        self.assertGreater(result['affine_rms_px'], 10)
        self.assertEqual(len(result['leave_line_out']), 16)
        self.assertLess(np.ptp(result['sensitivity_ranges']['width_change_percent']), .001)
        for p in points:
            if p['row'] == 0:
                p['center_px'][0] += 30 * (p['column']/8-.5)
        perturbed = analyze_geometry(points, use_reference=True)
        self.assertGreater(np.ptp(perturbed['sensitivity_ranges']['width_change_percent']), 1)

    def test_five_frame_reference_and_registration(self):
        tile = (chart()*255).astype(np.uint8)
        cv2.rectangle(tile, (5,5), (1494,994), 0, 3)
        strip = np.full((1040, 5*1540),255,np.uint8)
        for i in range(5):
            strip[20:1020,i*1540+20:i*1540+1520] = tile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.tif'
            Image.fromarray(strip).save(path,dpi=(360,360))
            reference = load_reference(path,3)
            self.assertEqual(reference['frame_count'],5)
            self.assertEqual(len(reference['points']),59)
            self.assertEqual(reference['selected_frame'],3)
            points, _ = detect_squares(chart())
            geometry = apply_reference(points,reference)
            self.assertLess(geometry['reference_fit_rms_px'],1)
            import json
            json.dumps(reference, allow_nan=False)
            with self.assertRaises(ValueError):
                load_reference(path,6)

    def test_grid_with_missing_marker_cells_and_projective_transform(self):
        image = chart()
        transform = np.array([[.98, .015, 10], [-.005, .98, 12], [.00001, -.00001, 1.]])
        image = cv2.warpPerspective(image, transform, (1500, 1000), borderValue=.8)
        points, geometry = detect_squares(image)
        self.assertEqual(len(points), 59)
        self.assertEqual(len({p['id'] for p in points}), 59)
        expected = cv2.perspectiveTransform(np.array([[[750., 490.]]]), transform)[0, 0]
        np.testing.assert_allclose(geometry['center_px'], expected, atol=1.)

    def test_blurred_edge_width_tracks_known_gaussian_blur(self):
        # Analytic Gaussian ESF: 10-90 width = 2.5631*sigma.
        import math
        y, x = np.indices((220, 220))
        slope = .08749
        distance = (x - 110 - slope * (y - 110)) / np.sqrt(1 + slope*slope)
        scores = []
        for sigma in [1., 2., 4.]:
            erf = np.vectorize(math.erf)(distance / (sigma*np.sqrt(2)))
            image = (.2 + .6 * (1-erf)/2).astype(np.float32)
            result = measure_edge(image, [110-slope*80, 30], [110+slope*80, 190], [170, 110])
            self.assertTrue(result['valid'])
            self.assertAlmostEqual(result['width_10_90_px'], sigma*2.5631, delta=.45)
            self.assertEqual(result['direction'], 'X')
            scores.append(result['sharpness_inv_px'])
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[1], scores[2])

    def test_uniform_image_rejected(self):
        with self.assertRaisesRegex(ValueError, 'target'):
            detect_squares(np.ones((300, 400), np.float32))

    def test_low_contrast_edge_rejected(self):
        result = measure_edge(np.ones((200, 200), np.float32)*.5, [100, 20], [100, 180], [150, 100])
        self.assertFalse(result['valid'])

    def test_end_to_end_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'chart.png'
            output = Path(directory)/'report'
            Image.fromarray((chart()*255).astype(np.uint8)).save(source)
            main([str(source), '--output', str(output)])
            for name in ['report.html', 'report.json', 'measurements.csv', 'map.png']:
                self.assertGreater((output/name).stat().st_size, 100)
            with self.assertRaises(SystemExit):
                main([str(source), '--output', str(output)])

    def test_raw_decode_parameters(self):
        import rawpy
        with patch.object(rawpy, 'imread') as read:
            read.return_value.__enter__.return_value.postprocess.return_value = np.full((80, 80, 3), 32768, np.uint16)
            green, rgb, meta = load_image('example.ARW')
            self.assertTrue(meta['linear'])
            self.assertAlmostEqual(float(green[0,0]), .5, places=4)
            kwargs = read.return_value.__enter__.return_value.postprocess.call_args.kwargs
            self.assertEqual(kwargs['gamma'], (1, 1))
            self.assertTrue(kwargs['no_auto_bright'])
            self.assertEqual(kwargs['user_flip'], 0)


if __name__ == '__main__':
    unittest.main()
