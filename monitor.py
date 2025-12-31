import customtkinter as ctk
import threading
import time
import re

# --- CONFIGURATION ---
SERIAL_PORT = "COM7"  # Change this to your ESP32 port (e.g., /dev/ttyUSB0 on Linux/Mac)
BAUD_RATE = 115200

# Map MAC addresses (from your logs) to Names for the display
# Note: Your logs show MACs without colons (e.g., 082697773354)
KNOWN_DEVICES = {
    "082697773354": "John Smith (iPad)",
    "0a2697773355": "Unknown Device A",
}

class SentinelApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🛡️ Sentinel: Presence Monitor")
        self.geometry("500x400")
        
        # Store device widgets here to update them later
        self.device_widgets = {} # Format: { "MAC_ADDR": { "label": widget, "bar": widget, "last_seen": time } }

        # Title
        self.header = ctk.CTkLabel(self, text="Live Device Tracker", font=("Arial", 20, "bold"))
        self.header.pack(pady=10)

        # Scrollable Frame for Devices
        self.scroll_frame = ctk.CTkScrollableFrame(self, width=450, height=300)
        self.scroll_frame.pack(pady=10, padx=10, fill="both", expand=True)

        # Start Serial Thread
        self.running = True
        self.thread = threading.Thread(target=self.read_serial_loop, daemon=True)
        self.thread.start()

        # Start Cleanup Loop (to mark devices offline)
        self.after(1000, self.check_timeouts)

    def add_or_update_device(self, mac, rssi):
        """ Creates a UI row for a device if new, or updates RSSI if exists. """
        
        # 1. Identify Name
        name = KNOWN_DEVICES.get(mac, f"Unknown ({mac[:4]}...)")
        
        # 2. Normalize RSSI (Assume -100 is 0%, -30 is 100%)
        # This converts -90...-30 range into a 0.0...1.0 float for the progress bar
        normalized_rssi = max(0, min(1, (int(rssi) + 100) / 70))
        
        # 3. Create Widgets if this is the first time we see this MAC
        if mac not in self.device_widgets:
            card = ctk.CTkFrame(self.scroll_frame)
            card.pack(pady=5, padx=5, fill="x")
            
            # Name Label
            lbl = ctk.CTkLabel(card, text=f"{name}", font=("Arial", 14, "bold"), width=150, anchor="w")
            lbl.pack(side="left", padx=10, pady=10)
            
            # RSSI Bar
            bar = ctk.CTkProgressBar(card, width=150)
            bar.pack(side="left", padx=10)
            bar.set(0) # Start empty
            
            # RSSI Value Label
            val_lbl = ctk.CTkLabel(card, text="-- dBm", width=60)
            val_lbl.pack(side="left", padx=5)

            self.device_widgets[mac] = {
                "frame": card,
                "bar": bar,
                "val_label": val_lbl,
                "last_seen": time.time()
            }

        # 4. Update the UI
        widgets = self.device_widgets[mac]
        widgets["last_seen"] = time.time()
        widgets["bar"].set(normalized_rssi)
        widgets["val_label"].configure(text=f"{rssi} dBm")
        
        # Color coding: Green if strong (-50), Yellow if medium, Red if weak (-90)
        if int(rssi) > -50:
            widgets["bar"].configure(progress_color="#2CC985") # Green
        elif int(rssi) > -75:
            widgets["bar"].configure(progress_color="#F2A900") # Yellow
        else:
            widgets["bar"].configure(progress_color="#E63946") # Red

    def check_timeouts(self):
        """ Dim devices that haven't been seen in 5 seconds """
        now = time.time()
        for mac, widgets in self.device_widgets.items():
            if now - widgets["last_seen"] > 5.0:
                widgets["bar"].set(0)
                widgets["val_label"].configure(text="Offline", text_color="gray")
                widgets["bar"].configure(progress_color="gray")
        
        self.after(1000, self.check_timeouts)

    def read_serial_loop(self):
        """ Reads the raw text from ESP32 and parses it """
        import serial
        
        try:
            # Open Serial Port
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            print(f"Connected to {SERIAL_PORT}")
            
            while self.running:
                if ser.in_waiting > 0:
                    try:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        self.parse_line(line)
                    except Exception as e:
                        print(f"Error reading line: {e}")
                else:
                    time.sleep(0.01)

        except Exception as e:
            print(f"Serial Error: {e}")
            print("Running in DEMO MODE (Simulating data)...")
            self.run_demo_mode()

    def parse_line(self, line):
        """
        Parses your specific ESP32 format:
        FT: 2 FST: 0 SRC: 082697773354 DEST: ... RSSI: -28 ...
        """
        # We look for lines starting with "FT:" that contain "SRC:" and "RSSI:"
        if line.startswith("FT:"):
            # Regex to pull out SRC and RSSI
            # Matches "SRC: (anything space)" and "RSSI: (numbers)"
            match = re.search(r"SRC:\s*([0-9a-zA-Z]+).*?RSSI:\s*(-?\d+)", line)
            
            if match:
                mac_address = match.group(1)
                rssi_value = match.group(2)
                
                # Update GUI (must use .after to be thread safe in Tkinter)
                self.after(0, lambda: self.add_or_update_device(mac_address, rssi_value))
    
    def run_demo_mode(self):
        """ Just for testing if you don't have the ESP32 plugged in right now """
        import random
        while self.running:
            # Simulate your ESP32 output
            fake_rssi = random.randint(-90, -30)
            fake_line = f"FT: 0 FST: 8 SRC: 082697773354 DEST: ffff RSSI: {fake_rssi} SEQ: 1 CHNL: 6"
            self.parse_line(fake_line)
            time.sleep(0.5)

if __name__ == "__main__":
    app = SentinelApp()
    app.mainloop()