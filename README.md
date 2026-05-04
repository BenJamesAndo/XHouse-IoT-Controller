# XHouse IoT Controller for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

A Home Assistant custom integration for XHouse / Giigle IoT devices (gate controllers, smart switches, covers, etc.).

## Supported Devices

- **XH-SGC01** — WiFi smart garage controller
- **EGA18, EGA15 & EGB18** — Gate controller
- Other WiFi switch devices discovered on the account

## Installation

### HACS (Recommended)

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BenJamesAndo&repository=XHouse-IoT-Controller&category=integration)

1. Open HACS in Home Assistant
2. Click the three dots in the top right → **Custom repositories**
3. Add this repository URL and select **Integration** as the category
4. Click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/xhouse` folder into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **XHouse IoT Controller**
3. Enter your XHouse account email and password

## Configuration

After setup, click **Configure** on the integration to adjust:

- **Refresh interval** — Polling frequency in seconds (minimum 5s, default 30s)
- **Debug mode** — Enable verbose logging

## Platforms

| Platform | Description |
|----------|-------------|
| `cover` | Gate/barrier controllers (open, close, stop) |
| `switch` | On/off switch devices |
| `button` | Momentary action buttons |

## Links

- [Community thread](https://community.home-assistant.io/t/sgc01-smart-wifi-garage-opener/457208/8)

## Screenshot
<img width="989" height="271" alt="image" src="https://github.com/user-attachments/assets/6e97540f-8d7e-4aaa-ad4b-ceabdecd9298" />

