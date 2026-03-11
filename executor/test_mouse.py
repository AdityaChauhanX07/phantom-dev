#!/usr/bin/env python3
"""Quick test to verify pyautogui can move mouse and click."""

import pyautogui
import time

print("Testing pyautogui mouse control...")
print("If this works, you should see the mouse move and click.")

# Test 1: Move mouse
print("\n1. Moving mouse to center of screen...")
screen_width, screen_height = pyautogui.size()
center_x = screen_width // 2
center_y = screen_height // 2
pyautogui.moveTo(center_x, center_y, duration=1)
print(f"   Moved to ({center_x}, {center_y})")

time.sleep(1)

# Test 2: Click
print("\n2. Clicking at center...")
pyautogui.click(center_x, center_y)
print("   Clicked!")

time.sleep(1)

# Test 3: Type
print("\n3. Testing keyboard input...")
print("   (This will type 'test' - make sure a text field is focused)")
time.sleep(2)
pyautogui.typewrite("test", interval=0.1)
print("   Typed 'test'")

print("\n✅ All tests completed!")
print("If you saw the mouse move and click, pyautogui is working correctly.")
print("If not, check Accessibility permissions in System Settings.")
