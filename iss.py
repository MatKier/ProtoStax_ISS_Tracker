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
#
#   Contributions by:
#   jplegat
#   MatKier
#   MiketheChap/melcasipit-Mike Davis paid coder melcasipit on Fiverr to write ring/circular buffer+exception handling
#
#   BSD license. All text above must be included in any redistribution


import sys
sys.path.append(r'lib')

if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")

import signal
import threading
from collections import deque
import epd2in7b

from PIL import Image, ImageDraw
from time import time

import requests

# Update interval for fetching positions
DATA_INTERVAL = 10  # seconds
# How often to refresh the display, in seconds
DISPLAY_REFRESH_INTERVAL = 300  # seconds
ORBITS_TO_KEEP = 2.9

ORBIT_DURATION = 90 * 60  # seconds, approximate ISS orbital period
DATA_LIMIT = int(ORBITS_TO_KEEP * ORBIT_DURATION / DATA_INTERVAL)  # number of samples depending on the orbits to keep

# Note:
# The dimensions of the 2.7 in ePaper display are 264 x 176

# Module-level handles so the signal handler can reach them without a second init.
_stop_event = threading.Event()
_epd = None


class Display(object):
    def __init__(self, imageWidth, imageHeight):
        self.imageWidth = imageWidth
        self.imageHeight = imageHeight
        self.imageMap = Image.open('world_map_m.bmp').convert('L')
        self.issLogo = Image.open('iss.bmp').convert('L')

    def drawISS(self, positions):
        imageBlack = Image.new('1', (self.imageWidth, self.imageHeight), 255)
        imageBlack.paste(self.imageMap, (0, 0))

        imageRed = Image.new('1', (self.imageWidth, self.imageHeight), 255)
        drawred = ImageDraw.Draw(imageRed)

        last = len(positions) - 1
        for i, (lat, lon, ts) in enumerate(positions):
            x, y = self.mapLatLongToXY(lat, lon)

            if i == last:
                s = 10
                imageRed.paste(self.issLogo, (int(x - s), int(y - s)))
            else:
                s = 2.5 if ts % (15 * 60) < DATA_INTERVAL else 1
                drawred.ellipse((x - s, y - s, x + s, y + s), fill=0)

        # Rotate image 180 degrees - Remove the # comments of the lines below to rotate the image and allow for alternate positioning/mounting of the Raspberry Pi
        # imageRed = imageRed.transpose(Image.ROTATE_180)
        # imageBlack = imageBlack.transpose(Image.ROTATE_180)

        return imageBlack, imageRed

    def mapLatLongToXY(self, lat, lon):
        x = int(0.733 * lon + 132)
        y = int(-1.006 * lat + 90.5)
        return x, y


def fetch_loop(url, positions, lock, stop_event, data_available):
    while not stop_event.is_set():
        try:
            print("Fetching data ...", flush=True)
            r = requests.get(url=url, timeout=10)
            data = r.json()
            print(data)
            lat = float(data['iss_position']['latitude'])
            lon = float(data['iss_position']['longitude'])
            ts = data['timestamp']
            with lock:
                positions.append((lat, lon, ts))
            data_available.set()  # stays set after first successful fetch
        except Exception as e:
            print(f"Error fetching data: {e}, continuing")
        stop_event.wait(DATA_INTERVAL)


def display_loop(display, epd, positions, lock, stop_event, data_available):
    # Block until the first position arrives (or shutdown)
    data_available.wait()

    while not stop_event.is_set():
        t0 = time()
        with lock:
            current_positions = list(positions)

        if current_positions:
            print("Updating display", flush=True)
            epd.init()
            imageBlack, imageRed = display.drawISS(current_positions)
            epd.display(epd.getbuffer(imageBlack), epd.getbuffer(imageRed))
            epd.sleep()
            print(f"Display updated after: {time() - t0:.3f}s")

        stop_event.wait(max(DISPLAY_REFRESH_INTERVAL - (time() - t0), 0))


def main():
    global _epd
    URL = 'http://api.open-notify.org/iss-now.json'

    _epd = epd2in7b.EPD()
    display = Display(epd2in7b.EPD_HEIGHT, epd2in7b.EPD_WIDTH)

    positions = deque(maxlen=DATA_LIMIT)
    lock = threading.Lock()
    data_available = threading.Event()

    fetcher = threading.Thread(
        target=fetch_loop,
        args=(URL, positions, lock, _stop_event, data_available),
        daemon=True,
    )
    displayer = threading.Thread(
        target=display_loop,
        args=(display, _epd, positions, lock, _stop_event, data_available),
        daemon=True,
    )

    fetcher.start()
    displayer.start()

    _stop_event.wait()
    fetcher.join(timeout=DATA_INTERVAL + 5)
    displayer.join(timeout=30)


# gracefully exit without a big exception message if possible
def ctrl_c_handler(signal, frame):
    print('Goodbye!')
    _stop_event.set()
    # To preserve the life of the ePaper display, it is best not to keep it powered up -
    # instead putting it to sleep when done displaying, or cutting off power to it altogether when
    # quitting. We'll also make sure to clear the screen when exiting. If you are powering down your
    # Raspberry Pi and storing it and the ePaper display, it is recommended
    # that the display be cleared prior to storage, to prevent any burn-in.
    #
    # I have modified epdconfig.py to initialize SPI handle in module_init() (vs. at the global scope)
    # because slepe/module_exit closes the SPI handle, which wasn't getting initialized in module_init.
    # I've also added a module_sleep (which epd.sleep calls) which does not call GPIO.cleanup, and
    # made module_exit call both module_sleep and GPIO.cleanup
    epd = _epd or epd2in7b.EPD()
    print("Clearing screen before exiting ... Please wait!")
    epd.init()
    epd.Clear()
    epd.exit()
    exit(0)

signal.signal(signal.SIGINT, ctrl_c_handler)


if __name__ == '__main__':
    main()
