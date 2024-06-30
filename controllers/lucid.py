#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Created By  : https://github.com/dstarikov
# Created Date: 30/06/2024
# version ='1.0'
# ---------------------------------------------------------------------------
""" Lucid L600 controller module for mqtt-bed

I have a Lucid L600 https://lucidmattress.com/l600-adjustable-bed-frame/

This bed uses an Okin controller with its own codes and handles

The Android application I used is "Okin ComfortBed II" by OKIN Refined
https://play.google.com/store/apps/details?id=com.ore.jalon.neworebeding

Using this application I intercepted the Bluetooth codes.

Note: This module is based off the dewertokin.py controller.

"""
# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import logging
import threading
import time
import struct

from bluepy.btle import Peripheral


class lucidBLEController:
    def __init__(self, addr):
        self.logger = logging.getLogger(__name__)
        self.charWriteInProgress = threading.Lock()
        self.addr = addr
        self.manufacturer = "Lucid"
        self.current_preset = "Unknown"
        self.previous_preset = "None"
        self.model = "L600"
        self.commands = {
            "Flat Preset":        "e6fe160000000800fd",
            "ZeroG Preset":       "e6fe160010000000f5",
            "TV Preset":          "e6fe160040000000c5",
            "Lounge Preset":      "e6fe160020000000e5",
            "Quiet Sleep":        "e6fe16008000000085",
            "Memory 1":           "e6fe16000001000004",
            "Memory 2":           "e6fe16000004000001",
            "Underlight":         "e6fe16000002000003",
            "Lift Head":          "e6fe16010000000004",
            "Lower Head":         "e6fe16020000000003",
            "Lift Foot":          "e6fe16040000000001",
            "Lower Foot":         "e6fe160800000000fd",
            "Massage Toggle":     "e6fe16000100000004",
            # Note: Wave cycles "On High", "On Medium", "On Low", "Off"
            "Wave Massage Cycle": "e6fe160000001000f5",
            # Note: Head and Foot cycles "On Low, "On Medium", "On High", "Off"
            "Head Massage Cycle": "e6fe160008000000fd",
            "Foot Massage Cycle": "e6fe16000400000001",
            "Massage Timer":      "e6fe16000200000003",
            "Keepalive NOOP":     "e6fe16000000000005",
        }
        # Initialise the adapter and connect to the bed before we start waiting for messages.
        self.last_known_values = {}
        self.seen_services = set()
        self.seen_characteristics = set()
        self.preset_characteristics = {}
        self.connectBed()
        # Start the background polling/keepalive/heartbeat function.
        # thread = threading.Thread(target=self.bluetoothPoller, args=())
        # thread.daemon = True
        # thread.start()
        self.scan_characteristics_periodically()

    # There seem to be a lot of conditions that cause the bed to disconnect Bluetooth.
    # Here we use the value of 040200000000, which seems to be a noop.
    # This lets us poll the bed, detect a disconnection and reconnect before the user notices.
    def bluetoothPoller(self):
        while True:
            with self.charWriteInProgress:
                try:
                    cmd = self.commands.get("Keepalive NOOP", None)
                    self.device.writeCharacteristic(
                        0x001A, bytes.fromhex(cmd), withResponse=True
                    )
                    self.logger.debug("Keepalive success!")
                except Exception:
                    self.logger.error("Keepalive failed! (1/2)")
                    try:
                        # We perform a second keepalive check 0.5 seconds later before reconnecting.
                        time.sleep(0.5)
                        cmd = self.commands.get("Keepalive NOOP", None)
                        self.device.writeCharacteristic(
                            0x001A, bytes.fromhex(cmd), withResponse=True
                        )
                        self.logger.info("Keepalive success!")
                    except Exception:
                        # If both keepalives failed, we reconnect.
                        self.logger.error("Keepalive failed! (2/2)")
                        self.connectBed()
            time.sleep(10)

    # Separate out the bed connection to an infinite loop that can be called on init (or a communications failure).
    def connectBed(self):
        while True:
            try:
                self.logger.debug("Attempting to connect to bed.")
                self.device = Peripheral(deviceAddr=self.addr, addrType="random")
                self.logger.info("Connected to bed.")
            except Exception as e:
                self.logger.error(f"Error connecting to bed: {e}")

            if self.device is not None:
                try:
                    self.logger.debug("Enabling bed control.")
                    self.device.readCharacteristic(0x001A)
                    self.device.readCharacteristic(0x001D)
                    self.logger.info("Bed control enabled.")
                    return
                except Exception as e:
                    self.logger.error(f"Error setting up bed control: {e}")
            self.logger.error("Error connecting to bed, retrying in one second.")
            time.sleep(1)

    # Separate out the command handling.
    def send_command(self, name):
        cmd = self.commands.get(name, None)
        if cmd is None:
            # print, but otherwise ignore Unknown Commands.
            self.logger.error(f"Unknown Command '{cmd}' -- ignoring.")
            return
        with self.charWriteInProgress:
            try:
                self.charWrite(cmd, name)
            except Exception:
                self.logger.error("Error sending command, attempting reconnect.")
                start = time.time()
                self.connectBed()
                end = time.time()
                if (end - start) < 5:
                    try:
                        self.charWrite(self, cmd, name)
                    except Exception:
                        self.logger.error(
                            "Command failed to transmit despite second attempt, dropping command."
                        )
                else:
                    self.logger.error(
                        "Bluetooth reconnect took more than five seconds, dropping command."
                    )

    # Separate charWrite function.
    def charWrite(self, cmd, name):
        self.logger.debug("Attempting to transmit command.")
        self.device.writeCharacteristic(0x001A, bytes.fromhex(cmd), withResponse=True)
        self.logger.info("Command sent successfully.")
        self.previous_preset = self.current_preset
        self.current_preset = name
        return

    def scan_characteristics(self):
        with self.charWriteInProgress:
            try:
                updated = False
                services = self.device.getServices()
                for service in services:
                    if service.uuid not in self.seen_services:
                        updated = True
                        self.logger.info(f"Service {service.uuid} found for the first time:")
                        self.seen_services.add(service.uuid)

                    characteristics = service.getCharacteristics()
                    for char in characteristics:
                        if char.uuid not in self.seen_characteristics:
                            updated = True
                            self.logger.info(f"  Characteristic {char.uuid} found for the first time:")
                            self.seen_characteristics.add(char.uuid)

                        try:
                            value = char.read()
                            if self.compare_and_update(service.uuid, char.uuid, value):
                                updated = True
                            descriptors = char.getDescriptors()
                            for desc in descriptors:
                                desc_value = desc.read()
                                if self.compare_and_update_descriptor(service.uuid, char.uuid, desc.uuid, desc_value):
                                    updated = True
                        except Exception as e:
                            self.logger.error(f"    Error reading characteristic: {e}")
                if updated:
                    self.logger.info("Finished refreshing updated characteristics")
            except Exception as e:
                self.logger.error(f"Error scanning characteristics: {e}")

    def scan_characteristics_periodically(self):
        thread = threading.Thread(target=self.periodic_scan, args=())
        thread.daemon = True
        thread.start()

    def periodic_scan(self):
        while True:
            self.scan_characteristics()
            time.sleep(1)  # Adjust the interval as needed

    def compare_and_update(self, service_uuid, char_uuid, new_value) -> bool:
        updated = False
        parsed_value = self.parse_value(new_value)
        if char_uuid in self.last_known_values:
            if self.last_known_values[char_uuid] != new_value:
                self.logger.info(f"Service {service_uuid} Characteristic {char_uuid} changed from {self.previous_preset} = {self.parse_value(self.last_known_values[char_uuid])} to {self.current_preset} = {parsed_value}")
                self.last_known_values[char_uuid] = new_value
                updated = True
        else:
            self.logger.info(f"Service {service_uuid} Characteristic {char_uuid} first read: {parsed_value}")
            self.last_known_values[char_uuid] = new_value
            updated = True
        return updated

    def compare_and_update_descriptor(self, service_uuid, char_uuid, desc_uuid, new_value):
        updated = False
        parsed_value = self.parse_value(new_value)
        if desc_uuid in self.last_known_values:
            if self.last_known_values[desc_uuid] != new_value:
                self.logger.info(f"Service {service_uuid} Characteristic {char_uuid} Descriptor {desc_uuid} changed from {self.previous_preset} = {self.parse_value(self.last_known_values[desc_uuid])} to {self.current_preset} = {parsed_value}")
                self.last_known_values[desc_uuid] = new_value
                updated = True
        else:
            self.logger.info(f"Service {service_uuid} Characteristic {char_uuid} Descriptor {desc_uuid} first read: {parsed_value}")
            self.last_known_values[desc_uuid] = new_value
            updated = True
        return updated

    def parse_value(self, value):
        try:
            # Attempt to decode as UTF-8 string
            return value.decode('utf-8')
        except UnicodeDecodeError:
            pass

        # Try to interpret as integer (assuming little-endian encoding)
        if len(value) == 1:
            return struct.unpack('B', value)[0]
        elif len(value) == 2:
            return struct.unpack('<H', value)[0]
        elif len(value) == 4:
            return struct.unpack('<I', value)[0]

        # If all else fails, return the raw byte representation
        return value.hex()