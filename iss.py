# *************************************************** 
#   International Space Station Tracker.
#   using Raspberry Pi B+, Waveshare ePaper Display and ProtoStax enclosure
#   --> https://www.waveshare.com/product/modules/oleds-lcds/e-paper/2.7inch-e-paper-hat-b.htm
#   --> https://www.protostax.com/products/protostax-for-raspberry-pi-b
#
#   It displays the current location of the ISS and also its tracked trajectory. The
#   current location is shown by the ISS icon, and the trajectory by small circles.
#   15 minute markers are shown as small rectangles.
#
#   ISS Current Location is obtained using Open Notify ISS Current Location API
#   http://open-notify.org/Open-Notify-API/ISS-Location-Now/
# 
#   Written by Sridhar Rajagopal for ProtoStax.
#   BSD license. All text above must be included in any redistribution
# *


import sys
sys.path.append(r'lib')

if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")

from enum import Enum
import signal
import epd2in7b
import epdconfig

from PIL import Image,  ImageDraw,  ImageFont, ImageOps
from datetime import datetime
import time
import requests 

### Change as desired ###
####################################
# Update interval for fetching positions, should be min. 20 seconds (because a display refresh takes about 15 to 19 seconds)
DATA_INTERVAL = 30 #seconds
# Time between drawing two big dots on the trace line
BIG_DOT_INTERVAL = 15 * 60 # seconds
# Update interval for the display
DISPLAY_REFRESH_INTERVAL = 3 # Number of DATA_INTERVAL between successive display updates (e.g. 2 => update display every second deta fetch)
# Maximum past orbits to keep on the display, can be a float
MAX_ORBIT_TRACES = 1.0

### Map / Geo constants ###
###########################
# Maximum values for longitude(-180,180) and latitude(90,-90), do not change
max_lon = 180
max_lat = 90
# Width and height of the background picture / map, adjust accordingly
map_width = 264
map_height = 181
# Calculate linear scaling factor, assumes map is an equirectangular projection
hor_factor = map_width/float(max_lon*2)
ver_factor = map_height/float(max_lat*2)

class Display(object):
    def __init__(self, imageWidth, imageHeight):
        self.imageWidth = imageWidth
        self.imageHeight = imageHeight
        
    # Draws the ISS current location and trajectory from array of positions
    def drawISS(self, positions):
        imageBlack = Image.new('1', (self.imageWidth, self.imageHeight), 255) # 1: clear the frame
        imageMap = Image.open('world_map_m.bmp').convert('L')
        if ((int)(time.strftime("%H")) % 2 == 0):
            imageMap = ImageOps.invert(imageMap)
        imageBlack.paste(imageMap, (0,0))

        imageRed = Image.new('1', (self.imageWidth, self.imageHeight), 255) # 1: clear the frame
        issLogo = Image.open('iss.bmp').convert('L')
        drawred = ImageDraw.Draw(imageRed)
  
        
        maxPositionsToDraw = len(positions) - (MAX_ORBIT_TRACES * (90 * 60) / DATA_INTERVAL)
        # Traversing positons in reverse so we can simply break out after MAX_ORBIT_TRACES ('i' starts at len(positions -1))
        for i,t in reversed(list(enumerate(positions))):
            # Only draw the last MAX_ORBIT_TRACES on the screen (based on one orbit per 90 mins).
            if(i < maxPositionsToDraw):
                # Ignore all older positions but keep them in the list, so that calculations based on len(positions) dont't change
                break
            
            (lat,lon) = t
            (x,y) = self.getXYFromLonLat(lat, lon)

            # Draw ISS frist (backwards iteration), trajectory line on top, so that the white iss.bmp background does not 'cut' into the trajectory line
            if (i == len(positions) - 1):
                # Draw ISS on latest position
                s = 10 # half the width/height of the issLogo
                imageRed.paste(issLogo, ((int)(x-s), (int)(y-s)))
            elif (i % max((int)(BIG_DOT_INTERVAL/DATA_INTERVAL),1) == 0):
                # Draw big dot every BIG_DOT_INTERVAL seconds (one reading every DATA_INTERVAL seconds, so every BIG_DOT_INTERVAL/DATA_INTERVAL readings)
                s = 3
                drawred.ellipse((x-s,y-s,x+s,y+s), fill=0)
            else:
                # Draw small dot
                s = 1
                drawred.ellipse((x-s,y-s,x+s,y+s), fill=0)

        # return the rendered Red and Black images
        return imageBlack, imageRed

    # Calculates x and y coordinates for the 264x181 world map background picture
    # from longitude and latitude using linear scaing factors hor_factor and hor_factor
    def getXYFromLonLat(self, lat, lon):
        x = (int)((lon + max_lon) * hor_factor)
        # Subtract from map_height because the latitude grows from bottom to the top (-90 to 90), while the y coordinates grow from top to bottom (0 to map_height) 
        y = (int)(map_height - (lat + max_lat) * ver_factor)
        return x, y

def myPrint(text):
    nowStr = datetime.utcnow().strftime("%H:%M:%S")
    print(nowStr + "> " + text.encode('ascii', 'ignore').decode('ascii'))

# The main function    
def main():
    # API to get ISS Current Location
    URL = 'http://api.open-notify.org/iss-now.json'

    # Initialize and clear the 2in7b (tri-color) display
    epd = epd2in7b.EPD()
    display = Display(epd2in7b.EPD_HEIGHT, epd2in7b.EPD_WIDTH)

    positions = []
    while(True):
        t0 = time.time()
        r = requests.get(url = URL)
        data = r.json() 
        
        lat = float(data['iss_position']['latitude'])
        lon = float(data['iss_position']['longitude'])
        
        positions.append((lat, lon))
        myPrint("Fetched new coordinates: " + str(positions[len(positions) -1]))
        
        # Refresh the display on the first fetch and then on every DISPLAY_REFRESH_INTERVAL fetch
        if (DISPLAY_REFRESH_INTERVAL == 1 or len(positions) % DISPLAY_REFRESH_INTERVAL == 1):
            myPrint("Updating screen ...")
            t2 = time.time()
            epd.init()
            (imageBlack, imageRed) = display.drawISS(positions)
            epd.display(epd.getbuffer(imageBlack), epd.getbuffer(imageRed))
            time.sleep(2)
            epd.sleep()
            myPrint("Updated screen in " + str(round(time.time() - t2)) + "s.")
        
        t1 = time.time()
        sleepTime = max(DATA_INTERVAL - (t1 - t0), 0)
        time.sleep(sleepTime) # Try to keep a data refresh interval of DATA_INTERVAL seconds


# gracefully exit without a big exception message if possible
def ctrl_c_handler(signal, frame):
    myPrint('Goodbye!')
    # XXX : TODO
    #
    # To preserve the life of the ePaper display, it is best not to keep it powered up -
    # instead putting it to sleep when done displaying, or cutting off power to it altogether.
    #
    # epdconfig.module_exit() shuts off power to the module and calls GPIO.cleanup()
    # The latest epd library chooses to shut off power (call module_exit) even when calling epd.sleep()    
    # epd.sleep() calls epdconfig.module_exit(), which in turns calls cleanup().
    # We can therefore end up in a situation calling GPIO.cleanup twice
    # 
    # Need to cleanup Waveshare epd code to call GPIO.cleanup() only once
    # for now, calling epdconfig.module_init() to set up GPIO before calling module_exit to make sure
    # power to the ePaper display is cut off on exit
    # I have also modified epdconfig.py to initialize SPI handle in module_init() (vs. at the global scope)
    # because slepe/module_exit closes the SPI handle, which wasn't getting initialized in module_init
    epdconfig.module_init()
    epdconfig.module_exit()
    myPrint("Remeber to clear the display using cleardisplay.py if you plan to power down your Pi and store it, to prevent burn-in!")
    exit(0)

signal.signal(signal.SIGINT, ctrl_c_handler)


if __name__ == '__main__':
    main()