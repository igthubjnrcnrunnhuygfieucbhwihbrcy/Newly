#!/usr/bin/env python3
"""
Script to generate ICO file from SVG for Newly Windows app.
Requires: pillow, cairosvg
Install: pip install pillow cairosvg
"""

import os
import sys
from io import BytesIO
from PIL import Image
import cairosvg

def svg_to_ico(svg_path, ico_path, sizes=[16, 24, 32, 48, 64, 96, 128, 256]):
    """Convert SVG to ICO with multiple sizes."""
    images = []
    
    for size in sizes:
        # Convert SVG to PNG at specific size
        png_data = cairosvg.svg2png(
            url=svg_path,
            output_width=size,
            output_height=size
        )
        
        # Open PNG and add to images list
        img = Image.open(BytesIO(png_data))
        images.append(img)
    
    # Save as ICO
    if images:
        images[0].save(
            ico_path,
            format='ICO',
            sizes=[(img.width, img.height) for img in images]
        )
        print(f"✅ ICO file saved to: {ico_path}")
        return True
    return False

if __name__ == "__main__":
    svg_file = os.path.join(os.path.dirname(__file__), "icon.svg")
    ico_file = os.path.join(os.path.dirname(__file__), "icon.ico")
    
    if not os.path.exists(svg_file):
        print(f"❌ SVG file not found: {svg_file}")
        sys.exit(1)
    
    try:
        svg_to_ico(svg_file, ico_file)
        print("✅ Icon generation complete!")
    except ImportError as e:
        print(f"❌ Required package not installed: {e}")
        print("\nInstall required packages:")
        print("  pip install pillow cairosvg")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error generating icon: {e}")
        sys.exit(1)
