#include "./esppl_functions.h"

// --- CONFIGURATION ---
#define RSSI_THRESHOLD -60 

// Define the specific channels to scan
int channels[] = {1, 4, 6, 11};
// Calculate how many channels are in the list
int channelCount = sizeof(channels) / sizeof(channels[0]);

// Callback function when a packet is sniffed
void cb(esppl_frame_info *info) {
  
  // 1. FILTER: IGNORE BEACONS 
  // Subtype 8 = Beacon (Router announcements). We remove this noise.
  if (info->framesubtype == 8) { 
      return; 
  }

  // 2. RSSI FILTER
  // Ignore weak signals
  if (info->rssi < RSSI_THRESHOLD) { 
      return; 
  }

  // 3. PRINT PACKET DETAILS
  Serial.print("\n");
  Serial.print("FT: ");  
  Serial.print((int) info->frametype);
  Serial.print(" FST: ");  
  Serial.print((int) info->framesubtype);
  Serial.print(" RSSI: ");
  Serial.print(info->rssi);
  Serial.print(" CH: ");
  Serial.print(info->channel);
  
  // Print Source MAC
  Serial.print(" SRC: ");
  for (int i = 0; i < 6; i++) Serial.printf("%02x", info->sourceaddr[i]);
  
  // Highlight Probe Requests (Devices searching for WiFi)
  if (info->framesubtype == 4) {
      Serial.print(" [PROBE]");
  }
}

void setup() {
    delay(500);
    Serial.begin(115200);
    
    // Initialize esppl
    esppl_init(cb);
    
    Serial.println("Sniffer started. Scanning channels: 1, 4, 6, 11");
}

void loop() {
    esppl_sniffing_start();
    
    // Iterate through our specific list of channels
    for (int i = 0; i < channelCount; i++) {
        int currentChannel = channels[i];
        esppl_set_channel(currentChannel);
        
        // Dwell Time: Stay on this channel for 250ms
        // This ensures we actually have time to "hear" packets before moving on
        unsigned long start = millis();
        while (millis() - start < 250) {
            // Process any packets that arrive while we wait
            while (esppl_process_frames()) {
                // Processing happens in the cb() function
            }
            yield(); // Keep the ESP happy (prevent watchdog reset)
        }
    }
}