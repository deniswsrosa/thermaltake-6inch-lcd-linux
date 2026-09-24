# Panel protocol

How the 6" LCD Panel Kit (USB `264a:2347`) is driven. The protocol was recovered from TT RGB Plus 3.0.9; `tt600.py` implements it.

## The hardware

| | |
|---|---|
| USB ID | `264a:2347` |
| Interfaces | 1 (HID), interrupt IN and OUT, 1024 bytes each, no report IDs |
| Panel | 6" TFT, 1480×720 physical; frames are sent at **1110×540** |
| Controller | embedded Linux (app V1.0.7, firmware V1.2.7, hardware V2.0) |

## Protocol

The protocol was recovered from TT RGB Plus 3.0.9 (its `Device_LCD_BY_6inch`
class and `BYProtocol.dll`). Every report is 1024 bytes, written to hidraw as
`0x00` + 1024 bytes.

### Commands

HTTP-like text, one per report, and the panel answers on the IN endpoint:

```
POST conn 1\r\n
SeqNumber=112\r\n
ContentType=json\r\n
ContentLength=<n>\r\n
\r\n
<json body>
```

Each message is framed:

```
5A | len_be16 | payload | sum8 | 5A
```

- `len` is the whole unescaped frame length (payload + 5).
- `sum8` is the sum of the length bytes and payload, mod 256.
- Between the two `5A`s, `5A` is escaped to `5B 01` and `5B` to `5B 02`.

Replies use the same framing, with status `1 200`, `AckNumber=113` and an
optional JSON body.

| Command | Body | Notes |
|---|---|---|
| `POST conn 1` | none | handshake; replies with versions, `brightness`, `degree`, `timeout`, … |
| `POST realtimeDisplay 1` | `{"enable":true}` | switch to live frames |
| `POST brightness 1` | `{"value":0-100}` | |
| `POST rotate 1` | `{"degree":N}` | |
| `POST transport 1` / `POST transported 1` | file name, size, md5 | standby/boot media and firmware upload (not implemented) |

### Frames

A frame is a JPEG of exactly 1110×540 (or 540×1110), at most `0xC7FFF` bytes,
sent in 1000-byte slices, one per report:

```
[0] 5C [1] 03 [2] FD [3] counter (0-59, +1 per frame)
[4..5] total slices, big-endian   [6..7] slice index, big-endian   [8] 01
[9..23] zero
[24..1023] JPEG data, zero-padded
```

The panel returns to its own screen when frames stop for `timeout` seconds
(5 by default), so the daemon keeps sending at least every few seconds.

## Why not the existing Thermaltake Linux tools?

The open-source drivers for the sibling panels target 480×128 and 480×480
screens with MCU controllers and the "ultra" and "rcpro" protocols:

| Project | Device |
|---|---|
| [pcmx1/thermaltake-lcd-linux](https://github.com/pcmx1/thermaltake-lcd-linux) | RC Pro 3.9" `264a:232a`, AIO LCD `264a:2328`, Tower 500 bar `264a:233d` |
| [bekindpleaserewind/ttlcd](https://github.com/bekindpleaserewind/ttlcd) | Tower 200 LCD Panel Kit |
| [GregDuhamel/thermaltaked](https://github.com/GregDuhamel/thermaltaked) | Tower 500 3.9" bar `264a:233d` |
| [messiahlap/th420-display](https://github.com/messiahlap/th420-display) | TH420 round `264a:233c` |

This panel ignores those protocols and stalls their feature reports. It is a
different controller that runs embedded Linux and speaks the BY protocol
above. If you have one of those screens, use the matching project.
