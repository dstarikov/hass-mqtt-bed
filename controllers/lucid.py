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
import binascii

from bluepy.btle import Peripheral


class lucidBLEController:
    def __init__(self, addr):
        self.logger = logging.getLogger(__name__)
        self.charWriteInProgress = threading.Lock()
        self.addr = addr
        self.device = None
        self.manufacturer = "Lucid"
        self.model = "L600"
        
        self.commands = {
            "preset_flat": "e6fe160000000800fd",
            "preset_zerog": "e6fe160010000000f5",
            "preset_tv": "e6fe160040000000c5",
            "preset_lounge": "e6fe160020000000e5",
            "preset_quiet_sleep": "e6fe16008000000085",
            "memory_1": "e6fe16000001000004",
            "memory_2": "e6fe16000004000001",
            "underlight": "e6fe16000002000003",
            "head_up": "e6fe16010000000004",
            "head_down": "e6fe16020000000003",
            "foot_up": "e6fe16040000000001",
            "foot_down": "e6fe160800000000fd",
            "massage_toggle": "e6fe16000100000004",
            # Note: Wave cycles "On High", "On Medium", "On Low", "Off"
            "wave_massage_cycle": "e6fe160000001000f5",
            # Note: Head and Foot cycles "On Low, "On Medium", "On High", "Off"
            "head_massage_cycle": "e6fe160008000000fd",
            "foot_massage_cycle": "e6fe16000400000001",
            "massage_timer": "e6fe16000200000003",
            "keepalive_noop": "e6fe16000000000005",
        }

        self.buttons = [
            ("preset_flat", "Preset Flat"),
            ("preset_zerog", "Preset ZeroG"),
            ("preset_tv", "Preset TV"),
            ("preset_lounge", "Preset Lounge"),
            ("preset_quiet_sleep", "Preset Quiet Sleep"),
            ("memory_1", "Memory 1"),
            ("memory_2", "Memory 2"),
            ("underlight", "Underlight"),
            ("head_up", "Head Up"),
            ("head_down", "Head Down"),
            ("foot_up", "Foot Up"),
            ("foot_down", "Foot Down"),
            ("massage_toggle", "Massage Toggle"),
            ("wave_massage_cycle", "Wave Massage Cycle"),
            ("head_massage_cycle", "Head Massage Cycle"),
            ("foot_massage_cycle", "Foot Massage Cycle"),
            ("massage_timer", "Massage Timer"),
        ]

        # For reading the current position/angle of the bed
        self.status_service_uuid = "0000ffe0-0000-1000-8000-00805f9b34fb"
        self.status_characteristic_uuid = "0000ffe4-0000-1000-8000-00805f9b34fb"
        self.status_characteristic = None

        # State of the bed to track
        self.head_angle = 0
        self.foot_angle = 0
        self.light_status = False

        self.switches = [
            ("light", "Bed Light"),
            # TODO: figure out state for massage features
        ]  # List of Tuples containing the MQTT payloads for the switch and a friendly name

        self.sensors = [
            ("head_angle", "°", "Head Angle"),
            ("foot_angle", "°", "Feet Angle"),
        ]  # List of Tuples containing the MQTT topic for any sensors, the HA unit of measurement, and friendly name

        # Initialize the adapter and connect to the bed before we start waiting for messages.
        self.connectBed()

        # Start the background polling/keepalive/heartbeat function.
        self.start_keepalive_thread()

    def get_state_dict(self):
        return {
            "head_angle": self.head_angle,
            "foot_angle": self.foot_angle,
            "light": "ON" if self.light_status else "OFF"
        }

    def start_keepalive_thread(self):
        thread = threading.Thread(target=self.bluetoothPoller, args=())
        thread.daemon = True
        thread.start()

    def bluetoothPoller(self):
        while True:
            with self.charWriteInProgress:
                try:
                    cmd = self.commands.get("keepalive_noop", None)
                    self.device.writeCharacteristic(
                        0x001A, bytes.fromhex(cmd), withResponse=True
                    )
                    self.refresh_status()
                except Exception:
                    self.logger.error("Keepalive failed! (1/2)")
                    try:
                        time.sleep(0.5)
                        cmd = self.commands.get("keepalive_noop", None)
                        self.device.writeCharacteristic(
                            0x001A, bytes.fromhex(cmd), withResponse=True
                        )
                        self.logger.info("Keepalive success!")
                        self.refresh_status()
                    except Exception:
                        self.logger.error("Keepalive failed! (2/2)")
                        self.connectBed()
            time.sleep(1)

    def connectBed(self):
        while True:
            try:
                self.logger.debug("Attempting to connect to bed.")
                self.device = Peripheral(deviceAddr=self.addr, addrType="random")
                self.logger.info("Connected to bed.")
                self.status_characteristic = self.get_status_characteristic()
                return
            except Exception as e:
                self.logger.error(f"Error connecting to bed: {e}")

            self.logger.error("Error connecting to bed, retrying in one second.")
            time.sleep(1)

    def get_status_characteristic(self):
        try:
            service = self.device.getServiceByUUID(self.status_service_uuid)
            characteristic = service.getCharacteristics(forUUID=self.status_characteristic_uuid)[0]
            self.logger.info(f"Characteristic obtained: {characteristic}")
            return characteristic
        except Exception as e:
            self.logger.error(f"Error retrieving characteristic: {e}")
            return None

    def send_command(self, name):
        cmd = self.commands.get(name, None)
        if cmd is None:
            self.logger.error(f"Unknown Command '{cmd}' -- ignoring.")
            return
        with self.charWriteInProgress:
            try:
                self.charWrite(cmd)
                return self.get_state_dict()
            except Exception:
                self.logger.error("Error sending command, attempting reconnect.")
                start = time.time()
                self.connectBed()
                end = time.time()
                if (end - start) < 5:
                    try:
                        self.charWrite(cmd)
                        return self.get_state_dict()
                    except Exception:
                        self.logger.error(
                            "Command failed to transmit despite second attempt, dropping command."
                        )
                else:
                    self.logger.error(
                        "Bluetooth reconnect took more than five seconds, dropping command."
                    )

    def charWrite(self, cmd):
        self.logger.debug("Attempting to transmit command.")
        response = self.device.writeCharacteristic(0x001A, bytes.fromhex(cmd), withResponse=True)
        self.logger.info(f"Command sent successfully, response: {response}")
        self.refresh_status()
        self.logger.debug(f"Finished refreshing the status")
        return self.get_state_dict()
    
    def refresh_status(self):
        try:
            if self.status_characteristic:
                value = self.status_characteristic.read()
                self.update_status(value)
            else:
                self.logger.error("Characteristic not found, reconnecting.")
                self.connectBed()
        except Exception as e:
            self.logger.error(f"Error scanning characteristics: {e}")

    def update_status(self, raw_value):
        value = binascii.hexlify(raw_value).decode('utf-8')
        new_light_status = self.decode_light_status(value)
        if self.light_status != new_light_status:
            self.logger.info(f"Updated light state, it is now {'ON' if new_light_status else 'OFF'}")
            self.light_status = new_light_status

        head_angle_raw = self.decode_head_angle_raw(value)
        foot_angle_raw = self.decode_foot_angle_raw(value)
        new_head_angle = self.normalize_angle(head_angle_raw, max_raw=16000, max_angle=60)
        new_foot_angle = self.normalize_angle(foot_angle_raw, max_raw=12000, max_angle=45)
        if self.foot_angle != new_foot_angle or self.head_angle != new_head_angle:
            self.logger.info(
                f"Updated angles - Head went from {self.head_angle} to {new_head_angle} degrees,"
                f" Foot went from {self.foot_angle} to {new_foot_angle} degrees")
            self.head_angle = new_head_angle
            self.foot_angle = new_foot_angle
    
    def decode_light_status(self, value) -> bool:
        light_status = value[26]
        return light_status == "4"

    def decode_head_angle_raw(self, value) -> int:
        byte1 = value[6:8]
        byte2 = value[8:10]
        head_angle_hex = byte2 + byte1
        head_angle = int(head_angle_hex, 16)
        return head_angle

    def decode_foot_angle_raw(self, value) -> int:
        byte1 = value[10:12]
        byte2 = value[12:14]
        foot_angle_hex = byte2 + byte1
        foot_angle = int(foot_angle_hex, 16)
        return foot_angle

    def normalize_angle(self, raw_angle, min_raw=0, max_raw=16000, min_angle=0, max_angle=60) -> float:
        normalized_angle = min_angle + (raw_angle - min_raw) * (max_angle - min_angle) / (max_raw - min_raw)
        return normalized_angle
