import pygame
import serial
import threading
import time
import math
import queue
from collections import deque

# =================CONFIG=================
# SERIAL SETTINGS
SERIAL_PORT = '/dev/ttyUSB0'  # Replace with your port (e.g., '/dev/ttyUSB0' or 'COMx')
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
DEVICE_TIMEOUT_SECONDS = 300  # 5 minutes

# KNOWN DEVICES MAPPING
KNOWN_DEVICES = {
    "1848cada4d26": "JesusFG (Galaxy S21)",
    "a0cc2b775e0a": "Stephen (S8)",
    "6c19c0b485a6": "John (iPad)",
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
        # Random starting angle
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
        self.screen_pos = (0, 0) # Store current X,Y for click detection

    def update(self, rssi):
        self.last_seen = time.time()
        
        # INCREASE ALPHA to make it more responsive
        # 0.1 = Very smooth, slow lag
        # 0.5 = Fast response, slightly jittery
        # 1.0 = Instant jump, no smoothing
        alpha = 0.4  
        self.avg_rssi = (alpha * rssi) + ((1 - alpha) * self.avg_rssi)
        
        # Keep the rotation
        self.angle += 0.005

    def is_timed_out(self):
        return (time.time() - self.last_seen) > DEVICE_TIMEOUT_SECONDS

  def get_visual_distance(self):
        # Simply call the global helper function
        return rssi_to_pixels(self.avg_rssi)

# Global dictionary
active_devices = {}
devices_lock = threading.Lock()

# --- SERIAL THREAD ---
def read_serial_port():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to {SERIAL_PORT}")
        while True:
            try:
                line = ser.readline().decode('utf-8', errors='replace').strip()
                if not line.startswith("FT:"):
                    continue

                parts = line.split()
                if len(parts) < 10: continue

                ft_str = parts[1]
                fst_str = parts[3]
                src_mac = parts[5]
                rssi_str = parts[9]

                # FILTER: Ignore Beacons (Router noise)
                if ft_str == '0' and fst_str == '8':
                    continue

                # Add to Log Queue (so we can see it in the UI)
                log_queue.put(line)

                # FILTER: Ignore weak noise
                rssi_val = int(rssi_str)
                if rssi_val < -95: continue

                # Send valid data to main thread
                data_queue.put({'mac': src_mac, 'rssi': rssi_val})

            except (ValueError, IndexError):
                continue
    except serial.SerialException as e:
        print(f"Serial Error: {e}")
        data_queue.put("STOP")


# --- PHYSICS HELPERS ---
def meters_to_rssi(meters):
    # Log-Distance Path Loss Model
    # RSSI = RSSI_0 - 10 * n * log10(d)
    # n = 2.5 (Environmental factor for typical home)
    # RSSI_0 = -35 (Reference signal strength at 1 meter)
    n = 2.5 
    rssi_0 = -35
    if meters <= 0: return rssi_0
    return rssi_0 - (10 * n * math.log10(meters))

def rssi_to_pixels(rssi):
    # This must match your "get_visual_distance" logic exactly!
    STRONG_SIGNAL = -35 
    WEAK_SIGNAL   = -90
    
    MIN_SCREEN_RADIUS = 50
    MAX_SCREEN_RADIUS = (min(WINDOW_WIDTH, RADAR_HEIGHT) // 2) - 50
    
    clean_rssi = max(WEAK_SIGNAL, min(STRONG_SIGNAL, rssi))
    signal_range = STRONG_SIGNAL - WEAK_SIGNAL
    signal_diff  = STRONG_SIGNAL - clean_rssi
    percent_dist = signal_diff / signal_range
    
    pixel_range = MAX_SCREEN_RADIUS - MIN_SCREEN_RADIUS
    return int(MIN_SCREEN_RADIUS + (percent_dist * pixel_range))



# --- MAIN LOOP ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, TOTAL_HEIGHT))
    pygame.display.set_caption("ESP32 WiFi Radar")
    clock = pygame.time.Clock()
    
    # Fonts
    font_main = pygame.font.SysFont('Arial', 14)
    font_bold = pygame.font.SysFont('Arial', 14, bold=True)
    font_log = pygame.font.SysFont('Consolas', 12) # Monospace for logs

    # Log Buffer (Stores last 12 lines)
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
            
            # MOUSE CLICK DETECTION
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = pygame.mouse.get_pos()
                # Check clicks on devices
                with devices_lock:
                    for mac, dev in active_devices.items():
                        dx = mx - dev.screen_pos[0]
                        dy = my - dev.screen_pos[1]
                        # If click is within 15 pixels of the dot
                        if math.hypot(dx, dy) < 15:
                            dev.show_details = not dev.show_details

        # 2. DATA PROCESSING
        # Process Device Data
        try:
            for _ in range(20): # Process batch
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

        # Process Log Data
        try:
            while not log_queue.empty():
                line = log_queue.get_nowait()
                serial_log_buffer.append(line)
        except queue.Empty:
            pass

        # 3. CLEANUP TIMEOUTS
        with devices_lock:
            to_remove = [mac for mac, dev in active_devices.items() if dev.is_timed_out()]
            for mac in to_remove:
                del active_devices[mac]

        # 4. DRAWING
        screen.fill(BG_COLOR)

        # --- DRAW RADAR GRID ---
        # Define the distances you want to mark (in meters)
        markings = [1, 3, 5, 10, 20] 
        
        for dist in markings:
            # 1. Convert Distance -> RSSI -> Pixels
            target_rssi = meters_to_rssi(dist)
            radius = rssi_to_pixels(target_rssi)
            
            # Don't draw if it's off-screen or too close
            if radius > (min(WINDOW_WIDTH, RADAR_HEIGHT)//2): continue

            # 2. Draw the Circle (Thin, Dark Grey)
            pygame.draw.circle(screen, (40, 40, 60), CENTER, radius, 1)
            
            # 3. Draw the Label
            # Render text like "5m (-52)"
            label_text = f"{dist}m"
            text_surf = font_main.render(label_text, True, (80, 80, 100))
            
            # Position text slightly above the line
            screen.blit(text_surf, (CENTER[0] + 5, CENTER[1] - radius - 15))
        
        # Draw ESP32 Center
        pygame.draw.circle(screen, ESP_COLOR, CENTER, 10)
        label_esp = font_bold.render("ESP32", True, ESP_COLOR)
        screen.blit(label_esp, (CENTER[0] - 20, CENTER[1] + 15))

        # Draw Devices
        with devices_lock:
            for mac, dev in active_devices.items():
                dist_px = dev.get_visual_distance()
                
                # Calculate X,Y
                dev_x = CENTER[0] + math.cos(dev.angle) * dist_px
                dev_y = CENTER[1] + math.sin(dev.angle) * dist_px
                dev.screen_pos = (dev_x, dev_y)

                # Draw Dot
                pygame.draw.circle(screen, dev.color, (int(dev_x), int(dev_y)), 10)

                # --- REPLACE THIS SECTION IN YOUR CODE ---
                
                # Draw Text Labels
                # Logic: Always show Name for known devices.
                # If clicked (show_details=True), show MAC and RSSI for everyone.
                if dev.is_known or dev.show_details:
                    label_y = dev_y - 25
                    
                    # 1. Draw Name
                    name_surf = font_bold.render(dev.name, True, TEXT_COLOR)
                    screen.blit(name_surf, (dev_x + 15, label_y))
                    
                    # 2. Draw Details (MAC + RSSI) if clicked
                    if dev.show_details:
                         # Render MAC
                         mac_surf = font_main.render(dev.mac, True, (150, 150, 150))
                         screen.blit(mac_surf, (dev_x + 15, label_y + 15))
                         
                         # Render RSSI (New Line)
                         rssi_surf = font_main.render(f"RSSI: {int(dev.avg_rssi)}", True, (150, 150, 150))
                         screen.blit(rssi_surf, (dev_x + 15, label_y + 30))

        # --- DRAW LOG SECTION ---
        # Draw Divider Line
        pygame.draw.line(screen, (100, 100, 100), (0, RADAR_HEIGHT), (WINDOW_WIDTH, RADAR_HEIGHT), 2)
        
        # Draw Log Background
        log_rect = pygame.Rect(0, RADAR_HEIGHT, WINDOW_WIDTH, LOG_HEIGHT)
        pygame.draw.rect(screen, LOG_BG_COLOR, log_rect)

        # Render Log Text
        y_offset = RADAR_HEIGHT + 10
        for log_line in serial_log_buffer:
            txt_surf = font_log.render(log_line, True, (0, 255, 0)) # Matrix green
            screen.blit(txt_surf, (10, y_offset))
            y_offset += 15

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()