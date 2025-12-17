import cv2
import numpy as np
from PIL import Image

import torch
import torch.nn as nn
from torchvision import models, transforms
from torchvision.models import ResNet18_Weights

from joblib import load

MODEL_DIR = "models"


def get_feature_extractor():
    resnet = models.resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    resnet.eval()
    modules = list(resnet.children())[:-1]
    feature_extractor = nn.Sequential(*modules)
    for p in feature_extractor.parameters():
        p.requires_grad = False
    return feature_extractor


def get_preprocess():
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ])


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    feature_extractor = get_feature_extractor().to(device)
    preprocess = get_preprocess()

    # Load clustering model + info
    model_data = load(f"{MODEL_DIR}/kmeans_child_detection.joblib")
    kmeans = model_data["kmeans"]
    child_cluster = model_data["child_cluster"]
    no_child_cluster = model_data["no_child_cluster"]
    child_radius = model_data.get("child_radius", None)  # just for debugging

    print(f"[INFO] child_cluster={child_cluster}, no_child_cluster={no_child_cluster}")
    print(f"[INFO] child_radius (for reference)={child_radius}")

    centers = kmeans.cluster_centers_
    center_child = centers[child_cluster]
    center_no = centers[no_child_cluster]

    # How strict we want to be: <1.0 means we require child distance to be much smaller
    margin = 0.84
    

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Cannot open camera")
        return

    print("Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break

        # Convert BGR (OpenCV) to RGB (PIL/torch)
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)

        with torch.no_grad():
            inp = preprocess(pil_img).unsqueeze(0).to(device)
            feat = feature_extractor(inp)
            feat = feat.view(feat.size(0), -1)  # (1, 512)
            feat_np = feat.cpu().numpy()[0]

        # Distances to both centers
        dist_child = np.linalg.norm(feat_np - center_child)
        dist_no = np.linalg.norm(feat_np - center_no)

        # Decision: only child if clearly closer to child center
        if dist_child < dist_no * margin:
            child_present = True
        else:
            child_present = False

        # --- draw debug info on screen (optional but helpful) ---
        text = "Child detected" if child_present else "No child detected"
        color = (0, 255, 0) if child_present else (0, 0, 255)

        cv2.putText(frame, text, (30, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)

        # small debug line with distances (you can comment this if too noisy)
        debug_text = f"d_child={dist_child:.1f}, d_no={dist_no:.1f}"
        cv2.putText(frame, debug_text, (30, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)

        cv2.imshow("Child detection demo", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
