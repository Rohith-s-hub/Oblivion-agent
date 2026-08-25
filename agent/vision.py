"""
agent/vision.py - Multimodal Vision Support for Oblivion AI

Encodes local images (PNG, JPG, WEBP, GIF) into base64 data URLs for
vision-capable models (gemma4:31b-cloud, gemini-2.5-flash, gpt-4o, etc.).
"""
from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path


def is_vision_supported(model_id: str) -> bool:
    """Check if the given model ID supports multimodal vision input."""
    model_lower = model_id.lower()
    vision_keywords = ["gemma4", "gemini", "gpt-4o", "claude-3", "llava", "vision", "qwen-vl"]
    return any(kw in model_lower for kw in vision_keywords)


def encode_image_to_data_url(image_path: str) -> tuple[bool, str, str]:
    """
    Validate image file and encode it into a base64 Data URL.
    Returns (success, data_url_or_error_msg, mime_type).
    """
    path = Path(image_path).expanduser().resolve()

    if not path.exists():
        return False, f"Image file not found: {image_path}", ""

    if not path.is_file():
        return False, f"Path is not a file: {image_path}", ""

    # Detect mime type
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        ext = path.suffix.lower()
        if ext in (".png", ".webp"):
            mime_type = f"image/{ext[1:]}"
        elif ext in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"
        elif ext == ".gif":
            mime_type = "image/gif"
        else:
            return False, f"Unsupported image format: {path.suffix}. Use PNG, JPG, WEBP, or GIF.", ""

    # Check file size (cap at 15MB)
    if path.stat().st_size > 15 * 1024 * 1024:
        return False, "Image file too large (max 15MB). Please resize or compress.", ""

    try:
        raw_bytes = path.read_bytes()
        encoded = base64.b64encode(raw_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"
        return True, data_url, mime_type
    except Exception as e:
        return False, f"Failed to read image: {e}", ""


def format_multimodal_message(prompt: str, data_url: str) -> dict:
    """
    Format a user message with both text and image_url in litellm standard format.
    """
    return {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": prompt if prompt.strip() else "Analyze this image in detail and describe what code, design, or fix is needed."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": data_url
                }
            }
        ]
    }
