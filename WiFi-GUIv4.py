import pygame
import serial
import threading
import time
import math
import queue
from collections import deque

# Manufacturer Database (OUI Prefixes - First 6 chars of MAC)
# You can add more from: https://maclookup.app/
MAC_PREFIXES = {
    "00000c": "Cisco",
    "001a11": "Google",
    "3c5ab4": "Google",
    "f4f5e8": "Google",
    "a0cc2b": "Samsung",
    "1848ca": "Samsung",
    "082697": "Samsung",
    "dce55b": "Samsung",
    "6c19c0": "Apple",
    "78fd94": "Apple",
    "b6ce21": "Apple",
    "acbc32": "Apple",
    "18fe34": "Espressif",
    "24a160": "Espressif",
    "a4cf12": "Espressif",
}

# =================CONFIG=================
# SERIAL SETTINGS
# UPDATE THIS to match your specific port! 
# Windows: 'COM3', 'COM4' | Linux/Mac: '/dev/ttyUSB0'
SERIAL_PORT = 'COM3' 
BAUD_RATE = 115200

# VISUALIZATION SETTINGS
WINDOW_WIDTH = 800
RADAR_HEIGHT = 600
LOG_HEIGHT = 200
TOTAL_HEIGHT = RADAR_HEIGHT + LOG_HEIGHT

CENTER = (WINDOW_WIDTH // 2, RADAR_HEIGHT // 2)

# COLORS
BG_COLOR = (20, 20, 30)       # Dark blue/gray background
LOG_BG_COLOR = (0, 0, 0)      # Black for log area
ESP_COLOR = (0, 255, 255)     # Cyan
KNOWN_COLOR = (255, 100, 100) # Reddish for known people
UNKNOWN_COLOR = (100, 100, 100) # Grey for strangers
TEXT_COLOR = (200, 200, 200)

# TIMEOUT SETTINGS
DEVICE_TIMEOUT_SECONDS = 10  # Seconds before dot disappears

# KNOWN DEVICES MAPPING (Lowercase MACs)
KNOWN_DEVICES = {
    "1848cada4d26": "JesusFG (Galaxy S21)",
    "a0cc2b775e0a": "Stephen (S8)",
    "6c19c0b485a6": "John (iPad)",
    "78fd9409735d": "Peter (iPhone)",
}
# ========================================

# Thread-safe queues
data_queue = queue.Queue() # For device updates
log_queue = queue.Queue()  # For text output

# Class to track device state
class WiFiDevice:
    def __init__(self, mac, rssi):
        self.mac = mac
        self.last_seen = time.time()
        self.avg_rssi = rssi
        # Random starting angle based on MAC hash
        self.angle = math.radians(hash(mac) % 360)
        
        # Identity logic
        self.is_known = mac in KNOWN_DEVICES
        if self.is_known:
            self.name = KNOWN_DEVICES[mac]
            self.color = KNOWN_COLOR
        else:
            self.name = "Unknown"
            self.color = UNKNOWN_COLOR
        
        # Interactivity
        self.show_details = False 
        self.screen_pos = (0, 0) 

    def update(self, rssi):
        self.last_seen = time.time()
        
        # Smoothing Factor (Alpha)
        # 0.1 = Slow/Smooth, 0.5 = Fast/Jittery
        alpha = 0.2  
        self.avg_rssi = (alpha * rssi) + ((1 - alpha) * self.avg_rssi)
        
        # Slow rotation to make it look alive
        self.angle += 0.005

    def is_timed_out(self):
        return (time.time() - self.last_seen) > DEVICE_TIMEOUT_SECONDS

    def get_visual_distance(self):
        return rssi_to_pixels(self.avg_rssi)

# Global dictionary
active_devices = {}
devices_lock = threading.Lock()

# --- SERIAL THREAD ---
def read_serial_port():
    try:
        # Open Serial Port
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to {SERIAL_PORT}")
        
        while True:
            try:
                line = ser.readline().decode('utf-8', errors='replace').strip()
                
                # Format: FT: 0 FST: 1 RSSI: -24 CH: 0 SRC: 082697773354
                if not line.startswith("FT:"):
                    continue

                parts = line.split()
                
                # Robust Parsing: Find indices dynamically
                try:
                    rssi_idx = parts.index("RSSI:") + 1
                    src_idx = parts.index("SRC:") + 1
                    
                    rssi_str = parts[rssi_idx]
                    src_mac = parts[src_idx]
                    
                    # Clean the data
                    rssi_val = int(rssi_str)
                    src_mac = src_mac.replace(':', '').lower() # Clean MAC
                    
                except (ValueError, IndexError):
                    # Malformed line, skip it
                    continue

                # Add raw line to Log Queue (limit length to save memory)
                log_queue.put(line[:80])

                # Send valid data to main thread
                data_queue.put({'mac': src_mac, 'rssi': rssi_val})

            except Exception as e:
                # Catch decoding errors or other glitches
                continue
                
    except serial.SerialException as e:
        print(f"Serial Error: {e}")
        print("Check your SERIAL_PORT variable at the top of the script!")
        data_queue.put("STOP")


# --- PHYSICS HELPERS ---
def meters_to_rssi(meters):
    # Log-Distance Path Loss Model
    n = 2.5 
    rssi_0 = -45 
    if meters <= 0: return rssi_0
    return rssi_0 - (10 * n * math.log10(meters))

def rssi_to_pixels(rssi):
    # Calibrated for your strong signal data (-20 to -30)
    STRONG_SIGNAL = -10  # Center of screen (Very close)
    WEAK_SIGNAL   = -90  # Edge of radar (Very far)
    
    MIN_SCREEN_RADIUS = 30
    MAX_SCREEN_RADIUS = (min(WINDOW_WIDTH, RADAR_HEIGHT) // 2) - 30
    
    # Clamp RSSI
    clean_rssi = max(WEAK_SIGNAL, min(STRONG_SIGNAL, rssi))
    
    # Map RSSI to Pixel Distance
    signal_range = STRONG_SIGNAL - WEAK_SIGNAL
    signal_diff  = STRONG_SIGNAL - clean_rssi
    percent_dist = signal_diff / abs(signal_range)
    
    return int(MIN_SCREEN_RADIUS + (percent_dist * pixel_range))


# Helper function to get vendor
def get_vendor(mac):
    # Check first 6 chars (clean MAC has no colons)
    prefix = mac[:6].lower()
    return MAC_PREFIXES.get(prefix, "Unknown Vendor")

# --- MAIN LOOP ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, TOTAL_HEIGHT))
    pygame.display.set_caption("ESP32 WiFi Radar")
    clock = pygame.time.Clock()
    
    # Fonts
    font_main = pygame.font.SysFont('Arial', 14)
    font_bold = pygame.font.SysFont('Arial', 14, bold=True)
    font_log = pygame.font.SysFont('Consolas', 12) 

    # Log Buffer
    serial_log_buffer = deque(maxlen=12)

    # Start Serial Thread
    thread = threading.Thread(target=read_serial_port, daemon=True)
    thread.start()

    running = True
    while running:
        # 1. EVENT HANDLING
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            
            # Click Detection
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = pygame.mouse.get_pos()
                with devices_lock:
                    for mac, dev in active_devices.items():
                        dx = mx - dev.screen_pos[0]
                        dy = my - dev.screen_pos[1]
                        if math.hypot(dx, dy) < 15:
                            dev.show_details = not dev.show_details

        # 2. DATA PROCESSING
        # Process Device Queue
        try:
            for _ in range(20): 
                data = data_queue.get_nowait()
                if data == "STOP":
                    running = False
                    break
                
                with devices_lock:
                    mac = data['mac']
                    if mac in active_devices:
                        active_devices[mac].update(data['rssi'])
                    else:
                        active_devices[mac] = WiFiDevice(mac, data['rssi'])
        except queue.Empty:
            pass

        # Process Log Queue
        try:
            while not log_queue.empty():
                line = log_queue.get_nowait()
                serial_log_buffer.append(line)
        except queue.Empty:
            pass

        # Cleanup Timeouts
        with devices_lock:
            to_remove = [mac for mac, dev in active_devices.items() if dev.is_timed_out()]
            for mac in to_remove:
                del active_devices[mac]

        # 3. DRAWING
        screen.fill(BG_COLOR)

        # Draw Radar Grid
        markings = [1, 3, 5, 10, 20] 
        for dist in markings:
            target_rssi = meters_to_rssi(dist)
            radius = rssi_to_pixels(target_rssi)
            
            if radius > (min(WINDOW_WIDTH, RADAR_HEIGHT)//2): continue

            pygame.draw.circle(screen, (40, 40, 60), CENTER, radius, 1)
            label_text = f"{dist}m"
            text_surf = font_main.render(label_text, True, (80, 80, 100))
            screen.blit(text_surf, (CENTER[0] + 5, CENTER[1] - radius - 15))
        
        # Draw ESP32 Center
        pygame.draw.circle(screen, ESP_COLOR, CENTER, 10)
        label_esp = font_bold.render("ESP32", True, ESP_COLOR)
        screen.blit(label_esp, (CENTER[0] - 20, CENTER[1] + 15))

        # Draw Devices
        with devices_lock:
            for mac, dev in active_devices.items():
                dist_px = dev.get_visual_distance()
                
                dev_x = CENTER[0] + math.cos(dev.angle) * dist_px
                dev_y = CENTER[1] + math.sin(dev.angle) * dist_px
                dev.screen_pos = (dev_x, dev_y)

                pygame.draw.circle(screen, dev.color, (int(dev_x), int(dev_y)), 10)

                # Draw Labels
                if dev.is_known or dev.show_details:
                    label_y = dev_y - 25
                    name_surf = font_bold.render(dev.name, True, TEXT_COLOR)
                    screen.blit(name_surf, (dev_x + 15, label_y))
                    
                    if dev.show_details:
                         # 1. Render MAC
                         mac_surf = font_main.render(dev.mac, True, (150, 150, 150))
                         screen.blit(mac_surf, (dev_x + 15, label_y + 15))
                         
                         # 2. Render Vendor (New!)
                         vendor_name = get_vendor(dev.mac)
                         vendor_surf = font_main.render(vendor_name, True, (255, 200, 100)) # Orange color
                         screen.blit(vendor_surf, (dev_x + 15, label_y + 30))

                         # 3. Render RSSI (Shifted down)
                         rssi_surf = font_main.render(f"RSSI: {int(dev.avg_rssi)}", True, (150, 150, 150))
                         screen.blit(rssi_surf, (dev_x + 15, label_y + 45))

        # Draw Log Section
        pygame.draw.line(screen, (100, 100, 100), (0, RADAR_HEIGHT), (WINDOW_WIDTH, RADAR_HEIGHT), 2)
        log_rect = pygame.Rect(0, RADAR_HEIGHT, WINDOW_WIDTH, LOG_HEIGHT)
        pygame.draw.rect(screen, LOG_BG_COLOR, log_rect)

        y_offset = RADAR_HEIGHT + 10
        for log_line in serial_log_buffer:
            txt_surf = font_log.render(log_line, True, (0, 255, 0)) 
            screen.blit(txt_surf, (10, y_offset))
            y_offset += 15

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()