#!/bin/bash

echo "#######################################################"
echo "### User Hook: Install ML Dependencies              ###"
echo "#######################################################"

# Install CPU-only torch
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

# Install Logic Dependencies (missing from requirements.txt)
# opencv-python-headless is required for cv2
# joblib, scikit-learn are required for the model
# Pillow is required for image processing
pip3 install opencv-python-headless joblib scikit-learn numpy Pillow --no-cache-dir
