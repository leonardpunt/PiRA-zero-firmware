from __future__ import print_function

import datetime
import io
import os
import struct
import time
import pigpio
import RPi.GPIO as gpio
import sqlite3
import json
import requests

from ..hardware import devices, lora
from ..const import MEASUREMENT_DEVICE_VOLTAGE, MEASUREMENT_DEVICE_TEMPERATURE
from ..messages import create_measurements_message

# Persistent state.
STATE_FRAME_COUNTER = 'lora.frame_counter'
IMSI_FILE = '/home/pi/hack-the-poacher/data/imsi-catcher.db'


class LoRa(lora.LoRa):
    # We need to override the default dio_mapping here as calling set_dio_mapping below
    # causes a race condition if the GPIO watchdog fires before set_dio_mapping is called.
    dio_mapping = [0, 0, 0, 0, 0, 0]


class Module(object):
    def __init__(self, boot):
        self._boot = boot
        self._lora = None
        self._last_update = datetime.datetime.now()
        self._frame_counter = boot.state[STATE_FRAME_COUNTER] or 1
        self._db = sqlite3.connect(IMSI_FILE)
        self._db_cursor = None
        self._htp_device_id = os.environ.get('DEVICE_ID', 'Unknown')
        self._slack_msg("Starting up")

        # Parse configuration.
        try:
            self._device_addr = self._decode_hex('LORA_DEVICE_ADDR', length=4)
            self._nws_key = self._decode_hex('LORA_NWS_KEY', length=16)
            self._apps_key = self._decode_hex('LORA_APPS_KEY', length=16)
            self._spread_factor = int(os.environ.get('LORA_SPREAD_FACTOR', '7'))
            self._enabled = True
            # self._initialize_lora_module()
        except:
            self._enabled = False

    def _decode_hex(self, name, length):
        """Decode hex-encoded environment variable."""
        value = [ord(x) for x in os.environ.get(name, '').decode('hex')]
        if len(value) != length:
            raise ValueError

        return value

    def _initialize_lora_module(self):
        # Initialize LoRa driver if needed.

        try:
            #first reset
            print("LoRa hardware reset.")
            self._boot.pigpio.set_mode(devices.GPIO_LORA_RESET_PIN, pigpio.OUTPUT)
            self._boot.pigpio.write(devices.GPIO_LORA_RESET_PIN, gpio.HIGH)
            time.sleep(0.01)
            self._boot.pigpio.write(devices.GPIO_LORA_RESET_PIN, gpio.LOW)
            time.sleep(0.001)
            self._boot.pigpio.write(devices.GPIO_LORA_RESET_PIN, gpio.HIGH)
            time.sleep(0.006)

            self._lora = LoRa(verbose=False)
            self._lora.set_mode(lora.MODE.SLEEP)
            self._lora.set_dio_mapping([0, 0, 0, 0, 0, 0])
            self._lora.set_freq(868.1)
            self._lora.set_pa_config(pa_select=1)
            self._lora.set_spreading_factor(self._spread_factor)
            self._lora.set_pa_config(max_power=0x0F, output_power=0x0E)
            self._lora.set_sync_word(0x34)
            self._lora.set_rx_crc(True)

        except AssertionError:
            self._lora = None
            print("WARNING: LoRa is not correctly initialized, skipping.")
            return

    def _get_new_catches(self):
        cursor = None
        if self._db_cursor:
            cursor = self._db.execute("SELECT * FROM observations WHERE julianday(stamp) > julianday(?) ORDER BY julianday(stamp) ASC", (str(self._db_cursor),))
        else:
            cursor = self._db.execute("SELECT * FROM observations ORDER BY julianday(stamp) ASC")
        result = cursor.fetchall()

        if result:
            self._db_cursor = result[-1][0]
        
        return result

    def _slack_msg(self, msg):
        msg = unicode(msg).encode("iso-8859-2", "replace") # Fix issues with weird characters

        enabled = os.environ.get('SLACK_DEBUGGING_ENABLED', '1') == '1' # Enables debugging by default
        if not enabled:
            print("Skip sending Slack message, Slack debugging not enabled")
            return

        url = os.environ.get('SLACK_URL', None)
        if not url:
            print("Skip sending Slack message, Slack URL not set")
            return

        payload = {
            'channel': '#hack-the-poacher',
            'username': 'HTP %s' % (self._htp_device_id,),
            'text': msg,
            'icon_emoji': ':sleuth_or_spy:'
        }

        try:
            requests.post(url, data={'payload': json.dumps(payload)})
        except:
            print("Something went wrong while sending message %s to Slack" % (msg,))

    def _slack_catches(self, catches):
        catch_msgs = []
        for catch in catches:
            tmsi1 = catch[1]
            tmsi2 = catch[2]
            imsi = catch[3]
            imsicountry = catch[4]
            imsibrand = catch[5]
            imsioperator = catch[6]
            if imsi:
                catch_msgs.append("- IMSI %s, country %s, brand %s, operator %s" % (imsi, imsicountry, imsibrand, imsioperator))
            elif tmsi1 and tmsi2:
                catch_msgs.append("- TMSI-1 %s, TMSI-2 %s" % (tmsi1, tmsi2))
            else:
                catch_msgs.append("- TMSI-1 %s" % (tmsi1,))

        msg = "Discovered:\n%s" % (".\n".join(catch_msgs,))
        self._slack_msg(msg)

    def process(self, modules):
        if not self._enabled:
            print("WARNING: LoRa is not correctly configured, skipping.")
            return

        catches = self._get_new_catches()
        if not catches:
            self._slack_msg("No new TMSIs/IMSIs found")
            return

        self._slack_catches(catches)

        # #Initialize lora modue if needed
        # if not self._lora:
        #     self._initialize_lora_module()

        # # Transmit message.
        # measurements = [
        #     MEASUREMENT_DEVICE_TEMPERATURE,
        #     MEASUREMENT_DEVICE_VOLTAGE,
        # ]

        # if 'pira.modules.ultrasonic' in modules:
        #     from .ultrasonic import MEASUREMENT_ULTRASONIC_DISTANCE
        #     measurements.append(MEASUREMENT_ULTRASONIC_DISTANCE)

        # message = create_measurements_message(self._boot, self._last_update, measurements)
        # if not message:
        #     return

        # print("Transmitting message ({} bytes) via LoRa...".format(len(message)))

        # payload = lora.LoRaWANPayload(self._nws_key, self._apps_key)
        # payload.create(
        #     lora.MHDR.UNCONF_DATA_UP,
        #     {
        #         'devaddr': self._device_addr,
        #         'fcnt': self._frame_counter % 2**16,
        #         'data': list([ord(x) for x in message]),
        #     }
        # )

        # self._lora.write_payload(payload.to_raw())
        # self._lora.set_mode(lora.MODE.TX)

        # # Wait for transmission to finish.
        # tx_wait_start = datetime.datetime.now()
        # while (datetime.datetime.now() - tx_wait_start) < datetime.timedelta(seconds=30):
        #     if self._lora.get_irq_flags()['tx_done']:
        #         break

        #     time.sleep(0.1)
        # else:
        #     print("WARNING: Timeout while transmitting LoRa message.")

        # self._lora.set_mode(lora.MODE.STDBY)
        # self._lora.clear_irq_flags(TxDone=1)

        # self._last_update = datetime.datetime.now()
        # self._frame_counter += 1
        # self._boot.state[STATE_FRAME_COUNTER] = self._frame_counter % 2**16

    def shutdown(self, modules):
        self._slack_msg("Shutting down")
