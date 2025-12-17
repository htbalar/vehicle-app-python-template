
import os
import logging
import numpy as np
import cv2
from PIL import Image
import torch
import torch.nn as nn
from torchvision import models, transforms
from torchvision.models import ResNet18_Weights
from joblib import load

logger = logging.getLogger(__name__)

class ChildPresenceDetector:
    def __init__(self, model_dir: str = "models"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._feature_extractor = self._get_feature_extractor().to(self.device)
        self._preprocess = self._get_preprocess()
        
        # Resolve absolute path for models to avoid CWD issues
        base_path = os.path.dirname(os.path.abspath(__file__))
        self.model_dir = os.path.join(base_path, model_dir)
        
        self.kmeans = None
        self.child_cluster = None
        self.no_child_cluster = None
        self.margin = 0.84
        
        self._load_models()

    def _get_feature_extractor(self):
        resnet = models.resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
        resnet.eval()
        modules = list(resnet.children())[:-1]
        feature_extractor = nn.Sequential(*modules)
        for p in feature_extractor.parameters():
            p.requires_grad = False
        return feature_extractor

    def _get_preprocess(self):
        return transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])

    def _load_models(self):
        try:
            model_path = os.path.join(self.model_dir, "kmeans_child_detection.joblib")
            logger.info(f"Loading child detection model from {model_path}")
            model_data = load(model_path)
            self.kmeans = model_data["kmeans"]
            self.child_cluster = model_data["child_cluster"]
            self.no_child_cluster = model_data["no_child_cluster"]
            
            centers = self.kmeans.cluster_centers_
            self.center_child = centers[self.child_cluster]
            self.center_no = centers[self.no_child_cluster]
            logger.info("Child detection model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load child detection model: {e}")
            self.kmeans = None

    def detect_child(self, frame: np.ndarray = None) -> bool:
        """
        Determines if a child is present in the given frame (or captures one).
        Returns True if child is detected, False otherwise.
        """
        if self.kmeans is None:
            logger.warning("Model not loaded, cannot detect child.")
            return False

        cap = None
        if frame is None:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                logger.warning("Cannot open camera for child detection.")
                return False
            ret, captured_frame = cap.read()
            if not ret:
                logger.warning("Failed to grab frame.")
                cap.release()
                return False
            frame = captured_frame

        try:
            # Inference
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            
            with torch.no_grad():
                inp = self._preprocess(pil_img).unsqueeze(0).to(self.device)
                feat = self._feature_extractor(inp)
                feat = feat.view(feat.size(0), -1)
                feat_np = feat.cpu().numpy()[0]

            dist_child = np.linalg.norm(feat_np - self.center_child)
            dist_no = np.linalg.norm(feat_np - self.center_no)
            
            # Logic: Child if clearly closer to child center
            if dist_child < dist_no * self.margin:
                return True
            return False

        except Exception as e:
            logger.error(f"Error during detection: {e}")
            return False
        finally:
            if cap:
                cap.release()
