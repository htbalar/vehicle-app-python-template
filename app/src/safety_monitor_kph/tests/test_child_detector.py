
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock heavy dependencies before they are imported by the module
sys.modules["torch"] = MagicMock()
sys.modules["torch.nn"] = MagicMock()
sys.modules["torchvision"] = MagicMock()
sys.modules["torchvision.models"] = MagicMock()
sys.modules["torchvision.transforms"] = MagicMock()
sys.modules["cv2"] = MagicMock()
sys.modules["joblib"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["PIL"] = MagicMock()
sys.modules["PIL.Image"] = MagicMock()

# Now we can import the module
# Adjust import based on where pytest is run. Assuming PYTHONPATH includes app/src
try:
    from app.src.safety_monitor_kph.child_detector import ChildPresenceDetector
except ImportError:
    # Try relative import if running directly or different structure
    sys.path.append("app/src")
    from safety_monitor_kph.child_detector import ChildPresenceDetector

class TestChildPresenceDetector(unittest.TestCase):
    
    @patch("app.src.safety_monitor_kph.child_detector.load")
    @patch("os.path.exists")
    def test_initialization(self, mock_exists, mock_load):
        # Setup mock for joblib load
        mock_data = {
            "kmeans": MagicMock(),
            "child_cluster": 0,
            "no_child_cluster": 1
        }
        mock_data["kmeans"].cluster_centers_ = [MagicMock(), MagicMock()]
        mock_load.return_value = mock_data
        
        detector = ChildPresenceDetector()
        self.assertIsNotNone(detector)
        self.assertIsNotNone(detector.kmeans)

    def test_detect_child_no_camera(self):
        detector = ChildPresenceDetector()
        # Mock cv2.VideoCapture to fail
        sys.modules["cv2"].VideoCapture.return_value.isOpened.return_value = False
        
        result = detector.detect_child()
        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()
