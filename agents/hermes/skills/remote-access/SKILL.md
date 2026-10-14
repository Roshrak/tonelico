---
name: remote-access
description: Turn remote mode on or off for the laptop (Sunshine stream for Moonlight over Tailscale, sleep blocked). Use when the user asks to turn remote mode on or off, to check whether the laptop is ready to stream, or to get the laptop's Tailscale address.
category: desktop
tags: [remote, sunshine, moonlight, tailscale, sleep]
---

# Remote access (Sunshine / Moonlight over Tailscale)

Remote mode is controlled by one command on this laptop:

- `remote-mode on` starts Sunshine and blocks sleep and lid-close suspend.
- `remote-mode off` stops Sunshine and releases the sleep block.
- `remote-mode status` reports Sunshine state, the sleep block, and the Tailscale address.

## Rules

1. Run the command with the terminal tool. Report its one-line output as the result. Do not claim success before the output shows it.
2. Turn remote mode on only when the user asks for it. Turn it off when the user says so, or when they ask to stop streaming.
3. Never change firewall, Tailscale, or Sunshine settings from this skill. Those are configuration changes that need the user.
4. Never print pairing PINs, Sunshine passwords, or Tailscale keys in chat.
5. The Moonlight pairing PIN is shown on the phone and entered in Moonlight, so the user has to read it themselves when pairing a new phone.

## Reply format

One short line: the state after the command, and the Tailscale address if the user needs it for Moonlight.
