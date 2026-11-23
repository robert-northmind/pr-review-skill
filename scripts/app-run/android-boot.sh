#!/bin/sh
# Boot the review's Android emulator headless and wait until it is usable.
# app_run.py sets REVIEW_AVD, REVIEW_EMULATOR_PORT and ANDROID_SERIAL; it stops
# the emulator when the journey ends. -read-only leaves the AVD unchanged, so it
# can run next to your own copy of the same AVD.
set -eu
: "${REVIEW_AVD:?run through app_run.py}" "${REVIEW_EMULATOR_PORT:?}" "${ANDROID_SERIAL:?}"
"$ANDROID_HOME/emulator/emulator" -avd "$REVIEW_AVD" -port "$REVIEW_EMULATOR_PORT" \
  -read-only -no-snapshot-save -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect \
  >"${REVIEW_EVIDENCE:-/tmp}/emulator.log" 2>&1 &
adb="$ANDROID_HOME/platform-tools/adb"
"$adb" wait-for-device
i=0
until [ "$("$adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do
  i=$((i + 1))
  [ "$i" -gt 180 ] && { echo "Emulator did not finish booting in 6 minutes" >&2; exit 1; }
  sleep 2
done
"$adb" shell input keyevent 82 >/dev/null 2>&1 || true   # dismiss the lock screen
echo "Booted $REVIEW_AVD as $ANDROID_SERIAL"
