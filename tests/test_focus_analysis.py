import unittest

import cv2
import numpy as np

from digie35.digie35image import ImageAnalysis


def jpeg(image):
    success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 100])
    assert success
    return encoded.tobytes()


class FocusAnalysisTests(unittest.TestCase):
    def test_uses_source_coordinates_and_returns_the_strongest_rgb_channel(self):
        # Deliberately non-3:2: regular film analysis crops this image, while
        # focus coordinates must stay aligned with the browser source preview.
        image = np.zeros((60, 100, 3), dtype=np.uint8)
        image[20:40, 40:60, 2] = np.tile([0, 255], 10)  # Red vertical detail.
        result = ImageAnalysis(jpeg(image)).analyze_focus((0.5, 0.5), size=20)

        self.assertEqual(result["bounds"], [40, 20, 20, 20])
        self.assertEqual((result["width"], result["height"]), (100, 60))
        self.assertEqual(result["focus_channel"], "red")
        self.assertEqual(result["focus_score"], result["focus_scores"]["red"])
        self.assertGreater(result["focus_score"], result["focus_scores"]["green"])

    def test_roi_is_kept_inside_the_source_image_at_an_edge(self):
        image = np.zeros((10, 20, 3), dtype=np.uint8)
        result = ImageAnalysis(jpeg(image)).analyze_focus((1, 1), size=16)
        self.assertEqual(result["bounds"], [4, 0, 16, 10])

    def test_rejects_invalid_position_and_size(self):
        analyzer = ImageAnalysis(jpeg(np.zeros((10, 10, 3), dtype=np.uint8)))
        with self.assertRaisesRegex(ValueError, "position"):
            analyzer.analyze_focus((1.1, 0.5))
        with self.assertRaisesRegex(ValueError, "size"):
            analyzer.analyze_focus((0.5, 0.5), size=2)
