#!/bin/sh
# A zero saver timeout prevents future blanking. Reset a saver already active
# at the Plymouth/LightDM handoff without sending mouse or keyboard events.
/usr/bin/xset s reset
/usr/bin/xsetroot -solid black
