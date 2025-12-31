import pygame
import serial
import threading
import time
import math
import queue

# =================CONFIG=================
# SERIAL SETTINGS
SERIAL_PORT = 'COM3'  # Replace with your port (e.g., '/dev/ttyUSB0' or 'COMx')
BAUD_RATE = 115200

# VISUALIZATION SETTINGS
WIDTH, HEIGHT = 800, 800
CENTER = (WIDTH // 2, HEIGHT // 2)
BG_COLOR = (20, 20, 30)  # Dark blue/gray
ESP_COLOR = (0, 255, 255) # Cyan
DEVICE_COLOR = (255, 100, 100) # Reddish

# TIMEOUT SETTINGS
DEVICE_TIMEOUT_SECONDS = 300  # 5 minutes

# KNOWN DEVICES MAPPING (Add yours here)
KNOWN_DEVICES = {
    "6e2ea47b4602": "Jesus (S21)",
    "a0cc2b775e0a": "Stephen (S8)",
    "6c19c0b485a6": "John (iPad)",
    # Add MACs you see in the logs here to give them names
}
# ========================================


# Thread-safe queue for passing data from serial thread to main thread
data_queue = queue.Queue()

# Class to track device state
class WiFiDevice:
    def __init__(self, mac, rssi):
        self.mac = mac
        self.name = KNOWN_DEVICES.get(mac, f"Unknown\n({mac[-4:]})")
        self.last_seen = time.time()
        # RSSI Smoothing: Initialize average with first value
        self.avg_rssi = rssi
        # Give it a random starting angle for visual placement
        self.angle = math.radians(hash(mac) % 360)

    def update(self, rssi):
        self.last_seen = time.time()
        # Simple exponential smoothing for less jittery movement
        # 0.1 = slow smooth response, 0.9 = fast jerky response
        alpha = 0.2
        self.avg_rssi = (alpha * rssi) + ((1 - alpha) * self.avg_rssi)
        # Slowly rotate angle for dynamic visual
        self.angle += 0.005

    def is_timed_out(self):
        return (time.time() - self.last_seen) > DEVICE_TIMEOUT_SECONDS

    def get_visual_distance(self):
        # --- RSSI TO DISTANCE MAPPING MAPPING ---
        # This is an estimation for visualization, not scientific meters.
        # Wi-Fi RSSI usually ranges from -30 (right next to it) to -90 (barely visible).
        # We map this range to pixels on screen (e.g., 50px to 350px radius)

        # Clamp RSSI values to practical limits
        clamped_rssi = max(-90, min(-30, self.avg_rssi))

        # Normalize -30 to -90 into a 0.0 to 1.0 scale where 0 is close, 1 is far.
        # -30 becomes 0.0, -90 becomes 1.0
        normalized_dist = (abs(clamped_rssi) - 30) / (90 - 30)

        # Map normalized 0-1 range to pixel range (min_radius, max_radius)
        min_px = 60
        max_px = min(WIDTH, HEIGHT) // 2 - 50
        pixel_distance = min_px + (normalized_dist * (max_px - min_px))
        return pixel_distance

# Global dictionary to store active devices
active_devices = {}
devices_lock = threading.Lock()


# --- SERIAL THREAD ---
def read_serial_port():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to {SERIAL_PORT}")
        while True:
            try:
                # Decode with error replacement just in case of garbled data
                line = ser.readline().decode('utf-8', errors='replace').strip()
                if not line.startswith("FT:"):
                    continue

                # Parsing the specific log format based on space splitting
                # Format: FT: 0 FST: 8 SRC: 0826... RSSI: -29 ...
                parts = line.split()

                # Safety check on line length
                if len(parts) < 10: continue

                ft_str = parts[1]
                fst_str = parts[3]
                src_mac = parts[5]
                rssi_str = parts[9]

                # --- FILTERING LOGIC ---
                # 1. Ignore Beacons (Router noise). FT 0 / FST 8
                if ft_str == '0' and fst_str == '8':
                    continue

                # 2. Ignore extremely weak signals that are likely garbage noise
                rssi_val = int(rssi_str)
                if rssi_val < -95:
                    continue

                # If it passed filters, send to main thread
                data_queue.put({'mac': src_mac, 'rssi': rssi_val})

            except (ValueError, IndexError):
                # Handle occasional malformed lines gracefully
                continue
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        # Send a signal to main thread to close application if serial fails
        data_queue.put("STOP")

# --- MAIN GRAPHICAL LOOP ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("ESP32 Proximity Monitor")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont('Arial', 16)
    small_font = pygame.font.SysFont('Arial', 12)

    # Start serial thread in background (daemon kills it when main ends)
    serial_thread = threading.Thread(target=read_serial_port, daemon=True)
    serial_thread.start()

    running = True
    while running:
        # 1. Process events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # 2. Process incoming serial data from queue
        try:
            # Process up to 20 packets per frame to prevent lag
            for _ in range(20):
                data = data_queue.get_nowait()
                if data == "STOP":
                    running = False
                    break
                
                mac = data['mac']
                rssi = data['rssi']

                with devices_lock:
                    if mac in active_devices:
                        active_devices[mac].update(rssi)
                    else:
                        #New device detected
                        active_devices[mac] = WiFiDevice(mac, rssi)
        except queue.Empty:
            pass

        # 3. Clean up old devices (Timeout > 5 mins)
        with devices_lock:
            # Create a list of MACs to remove to avoid modifying dict while iterating
            to_remove = [mac for mac, dev in active_devices.items() if dev.is_timed_out()]
            for mac in to_remove:
                print(f"Removing {mac} due to timeout.")
                del active_devices[mac]

        # 4. Drawing
        screen.fill(BG_COLOR)

        # Draw distance rings (guidelines)
        pygame.draw.circle(screen, (50, 50, 70), CENTER, 150, 1)
        pygame.draw.circle(screen, (50, 50, 70), CENTER, 250, 1)
        pygame.draw.circle(screen, (50, 50, 70), CENTER, 350, 1)

        # Draw ESP32 Center
        pygame.draw.circle(screen, ESP_COLOR, CENTER, 15)
        label_esp = font.render("ESP32 Scanner", True, ESP_COLOR)
        screen.blit(label_esp, (CENTER[0] - label_esp.get_width()//2, CENTER[1] + 20))

        # Draw Devices
        with devices_lock:
            for mac, device in active_devices.items():
                dist_px = device.get_visual_distance()
                
                # Calculate X, Y based on distance and angle
                dev_x = CENTER[0] + math.cos(device.angle) * dist_px
                dev_y = CENTER[1] + math.sin(device.angle) * dist_px
                
                # Draw device circle
                pygame.draw.circle(screen, DEVICE_COLOR, (int(dev_x), int(dev_y)), 12)
                
                # Draw labels (Name and RSSI)
                name_txt = font.render(device.name, True, (200, 200, 200))
                rssi_txt = small_font.render(f"{int(device.avg_rssi)} dBm", True, (150, 150, 150))
                
                screen.blit(name_txt, (dev_x + 15, dev_y - 10))
                screen.blit(rssi_txt, (dev_x + 15, dev_y + 10))

        # Show active count
        count_txt = font.render(f"Active Devices: {len(active_devices)}", True, (255, 255, 0))
        screen.blit(count_txt, (10, 10))

        pygame.display.flip()
        clock.tick(60) # Limit to 60 FPS

    pygame.quit()

if __name__ == "__main__":
    main()