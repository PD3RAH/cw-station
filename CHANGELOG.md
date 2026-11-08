# Changelog

## 2.4.2 – 2026-11-08
- Spectrum scope: automatic level (noise floor) and a Contrast slider, so weak signals are visible
- Audio waterfall range selectable: 1 / 1.5 / 2 / 3 kHz (default 2 kHz); skimmer follows the range
- Scope title shows the number of scope points (diagnostics)

## 2.4.1 – 2026-11-08
- Colour theme is applied immediately when chosen in Settings (the dialog stays open)

## 2.4.0 – 2026-11-08
- Responsive interface: fonts, knob, meters, waterfalls and sliders scale with the window
  (small laptop screens up to 1440p and larger); re-layout after resizing
- Clocks and frequency use fixed-width digits, so they no longer shift

## 2.3.1 – 2026-11-08
- Fix: waterfall crashed ("index out of bounds") when the window width changed by a pixel on wide screens.
  In versions before 2.3.0 this stopped all screen updates, which looked like the audio was not working.

## 2.3.0 – 2026-11-08
- Update notification: checks GitHub releases at start-up (WinHTTP, no OpenSSL needed); can be turned off
- Decoder tools panel: speed, SNR, dit/dah, weight and gaps, live character, Match speed, Reset decoder;
  Morse table; CW abbreviations and Q-codes (NL/EN)
- Audio diagnostics: warns when no sound arrives (Windows microphone privacy), errors logged to error.log
- Mode buttons light up immediately and the mode is polled every second
- GUI loop can no longer stop on an unexpected error

## 2.2.0 – 2026-11-08
- IC-7300MK2 support: automatic radio detection (CI-V 94h / B6h) via transceiver ID
- Digital TX meters: PO (W), SWR, ALC and Id with peak hold; Vd supply voltage
- TX power slider (PWR), ATU on/off and TUNE
- Full user manual in English and Dutch (Markdown + HTML in the installer, Manual button)
- Clocks moved to the header

## 2.1.0 – 2026-11-08
- Survey (Dutch/English): 'Survey' button and a one-time question after the 5th start.
  The survey page (`web/cwstation/enquete.php`) e-mails the answers to the author.

## 2.0.0 – 2026-11-08
- English and Dutch interface, switchable live; 6 colour themes
- Modern look: rounded buttons, filled spectrum, knurled VFO knob
- Skimmer: decodes up to 8 CW signals at once, callsign labels in the waterfall
- Logbook with ADIF export (Ctrl+L), QRZ.com lookup, clickable callsigns
- Settings window with macro editor ({MYCALL} {CALL} {RST} {NAME} {MYNAME} {MYQTH})
- CQ repeat
- Decoder: key-click folding, minimum-statistics noise floor, AUTO bandwidth limited to 120 Hz
- Settings and logbook moved to %APPDATA%\CWStation (old settings are migrated)
- Smaller installer: no Pillow, OpenSSL, SQLite or ASIO PortAudio build

## 1.x – 2026-11-07
- First versions: CW decoder, keyboard keyer, IC-7300 scope, S-meter, IF filter control
