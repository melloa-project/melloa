# Camera perception, hardware specification, and setup guide

## Purpose

Deliver useful private-room observations without streaming continuous video to expensive models or treating probabilistic perception as fact. The design must prioritize local processing, visible privacy controls, network isolation, low-light reliability, bounded retention, and replaceability.

## Perception pipeline decision

```text
RTSP camera stream
      ↓ local-only
short encrypted ring buffer
      ↓
motion / scene / region change
      ↓
candidate segment and deduplication
      ↓
local object / pose / occupancy features
      ↓
state machine and temporal aggregation
      ↓
selective frame/clip evidence
      ↓
local semantic interpretation when adequate
      ↓ policy gate
hosted multimodal escalation when permitted and useful
      ↓
interpretation event with confidence, alternatives, evidence, versions
      ↓
current-state update and later reflection
```

Frigate is a pragmatic replaceable adapter because its design uses low-overhead motion detection to decide where object detection is necessary, runs detection locally, and supports retention based on detected objects. [S28](research/primary-sources.md#S28) It should not become Melloa's source of truth. Melloa ingests its detections and media references into its own provenance schema.

## Camera protocol

Bless a wired IP camera supporting:

- ONVIF Profile T;
- RTSP with H.264, preferably H.265 as an option;
- configurable substream for low-cost detection;
- motion/tamper metadata when available;
- HTTPS management;
- local credentials and local streaming without vendor cloud;
- PoE for one-cable power/network.

ONVIF Profile T covers advanced streaming, H.264/H.265, imaging, metadata, motion/tamper events, HTTPS streaming, and bidirectional audio capabilities, making it a suitable interoperability baseline. [S23](research/primary-sources.md#S23) RTSP remains the media-control protocol rather than a trust or authentication boundary.

## Blessed initial hardware

### Core host

A quiet x86-64 mini-PC in the Intel N100/N150 class or equivalent:

- 4+ efficiency cores;
- 16 GB RAM minimum, 32 GB preferred;
- 1 TB NVMe SSD;
- gigabit Ethernet, 2.5 GbE optional;
- hardware video decode supported by Linux/FFmpeg;
- measured idle/average power in the 8–30 W range depending on model and load;
- BIOS power-on-after-outage;
- small UPS if outages are common.

Why not Raspberry Pi as the core: the Pi is excellent as a sensor/edge node, but the core benefits from standard x86 Linux containers, NVMe reliability, more RAM, easier database operation, and room for local inference. A Pi 5 may still run the camera adapter or a remote sensor.

### Camera

One indoor 4–5 MP PoE camera with:

- ONVIF Profile T and documented RTSP URLs;
- 1080p or better main stream and low-resolution substream;
- good low-light sensor and IR illumination;
- configurable privacy mask and physical orientation;
- vendor cloud/P2P disable switch;
- current security-update policy;
- no requirement for a vendor NVR.

Do not bless a specific low-cost consumer SKU for years. Camera firmware/support changes faster than the interface. Validate ONVIF conformance and local-only operation at purchase time.

### Network and power

- managed PoE switch or injector;
- separate camera VLAN;
- UPS protecting core, switch, and camera if reliable event continuity matters;
- visible physical or switched camera power cutoff.

### Approximate initial budget

| Item | Practical range |
|---|---:|
| x86 mini-PC, 16–32 GB / 1 TB | £250–£500 |
| PoE camera | £80–£250 |
| PoE switch/injector and cabling | £30–£120 |
| UPS | £80–£180 |
| Optional external backup drive | £70–£150 |
| **Typical total** | **£510–£1,200** |

A disciplined build can land near £500–£800 when networking/storage already exist. Do not buy a GPU until event traces show a local workload that is both frequent and expensive enough to justify it.

## Alternative builds

### Low-cost edge experiment: Raspberry Pi 5

- Raspberry Pi 5, active cooling, SSD/NVMe storage;
- Camera Module 3 or NoIR variant;
- visible enclosure and privacy shutter/power switch;
- optional AI HAT+ after baseline profiling.

Camera Module 3 provides a 12 MP autofocus/HDR sensor, NoIR variants, and 1080p50; it begins around $25 and is planned for production through at least January 2030. [S30](research/primary-sources.md#S30) The AI HAT+ offers 13 or 26 TOPS and integrates with the Pi camera stack, but its value depends on model compatibility. [S31](research/primary-sources.md#S31)

**Use when:** open hardware, custom optics, or edge experimentation matters more than appliance reliability.  
**Do not use when:** a seven-year always-on camera should require minimal maintenance.

### Existing home server

Use an existing Linux server if it has reliable storage, isolated networking, enough RAM, and a clear trust boundary. Avoid co-locating Melloa with an experimental homelab whose frequent reboots and broad admin access undermine availability/security.

### Local GPU box

A £1,500–£4,000+ GPU system may enable stronger local VLMs and coding models, but adds heat, power, driver, and depreciation cost. Defer until model-routing telemetry demonstrates a sustained privacy or API-cost benefit.

## Network topology and camera hardening

Camera VLAN rules:

```text
camera → perception host: RTSP/ONVIF/NTP only
camera → internet: deny
camera → LAN/database/model providers: deny
management workstation → camera HTTPS: owner-only, temporary
perception host → camera: allow explicit ports
```

Hardening checklist:

- unique random camera password stored in the capability broker;
- disable UPnP, vendor P2P/cloud, unused audio, Wi-Fi, and discovery beyond the VLAN;
- update firmware before installation and quarterly thereafter;
- local NTP/DNS where possible;
- export configuration after setup;
- monitor unexpected outbound attempts and reboots;
- place no trust in camera-supplied timestamps without clock health metadata.

## Stream design

Use at least two streams when available:

- substream around 640×360 or 720p at 5–10 fps for motion/object detection;
- main stream at 1080p/15–25 fps for brief evidence clips and selective semantic interpretation.

Use go2rtc/restreaming to avoid multiple direct camera connections when several local consumers need the stream. [S29](research/primary-sources.md#S29)

## Event segmentation and state

Avoid creating a canonical event per frame or detector hit. Maintain local temporal state:

```text
empty → candidate_presence → occupied → candidate_empty → empty
```

Use hysteresis, zones, object tracks, time windows, and confidence accumulation. Example:

- “person entered” requires a new person track crossing the door zone or a transition from empty to occupied with supporting frames;
- “person left” requires absence for a configured interval, not one missed detection;
- “went to bed” is a higher-level hypothesis requiring bed-zone occupancy, posture/activity, time, and persistence; it should carry alternatives and expire if contradicted.

## Escalation policy

A cloud multimodal model receives evidence only when:

- the data classification permits the provider/account route;
- a local route is insufficient;
- uncertainty affects a goal or action;
- the selected frame/crop is minimized;
- the owner has enabled that class of processing;
- the run budget and daily privacy budget permit it.

Prefer crops, masks, low-resolution frames, or structured features over full-room clips. Record exactly what left the host and the provider policy in force.

## Storage and bandwidth calculations

Continuous video is expensive even before model inference:

- 2 Mbps continuous ≈ 21.6 GB/day ≈ 648 GB/30-day month.
- 4 Mbps continuous ≈ 43.2 GB/day ≈ 1.30 TB/month.
- 100 retained 15-second events/day at 2 Mbps ≈ 0.375 GB/day ≈ 11.25 GB/month, before thumbnails/metadata.

Selective retention can therefore reduce media storage by roughly 50–100× for the stated assumptions.

### Default retention

| Data | Default |
|---|---|
| In-memory/on-disk ring buffer | 30–120 seconds, encrypted/local |
| Unselected motion candidates | minutes to 24 hours |
| Selected evidence frames | 24 hours to 7 days |
| Selected clips | 7–30 days only when justified |
| Canonical event metadata | long-lived according to purpose |
| Owner-confirmed important media | explicit, case-specific retention |

Continuous long-term raw recording is off by default.

## Privacy and placement

- Intended only for the owner's private space with consent from anyone who may be observed.
- Do not point at windows, shared corridors, neighboring property, bathrooms, or areas where visitors cannot reasonably understand the camera.
- Use a visible indicator and a physical shutter or power cutoff.
- Provide scheduled privacy modes and a local status display.
- Treat audio as disabled in V1 even if the camera supports it.
- Prefer a field of view sufficient for occupancy/activity, not facial detail, unless a concrete use case justifies identity recognition.
- Mask computer screens and sensitive areas where practical.

## Low-light design

- Choose a larger/better low-light sensor over chasing resolution.
- Test IR reflections from glass, glossy surfaces, and close walls.
- NoIR Pi cameras require separate IR illumination; confirm that visible privacy expectations are still met.
- Calibrate detection and state transitions separately for day and night.
- Store illumination-state metadata because model confidence changes with lighting.

## Camera installation journey

1. Select placement and write the intended observations/non-observations.
2. Cable PoE and place the camera on the isolated VLAN.
3. Update firmware; set unique credentials; disable cloud/P2P/UPnP/audio.
4. Validate ONVIF/RTSP locally and configure main/substreams.
5. Establish privacy masks, visible indicator, and physical cutoff.
6. Configure Frigate/adapter motion zones and retention with no cloud AI.
7. Run a 48-hour calibration, recording false positives and missed transitions.
8. Map candidate detections into Melloa observations/interpretations.
9. Enable selected semantic interpretation on a small sample.
10. Review every externally transmitted frame and storage volume before broadening.
11. Add quarterly firmware/security and monthly lens/placement checks.

## Reliability and failure modes

- **Camera disconnect:** health event after bounded retries; no invented “owner absent” conclusion.
- **Frozen stream:** detect repeated frame hashes and timestamp stalls.
- **Low-light collapse:** lower confidence and avoid behavior claims.
- **Disk pressure:** delete expired raw evidence first; preserve canonical/audit data; alert owner.
- **Clock drift:** flag timing uncertainty and avoid duration-sensitive inferences.
- **False activity label:** owner correction updates evaluation set and belief, not historical evidence.
- **Compromised camera:** VLAN/egress block limits impact; replace credentials/device; review frames and network logs.

## Build now

- One wired camera, one zone map, local ring buffer and motion/object filtering.
- Observation/interpretation events with confidence and evidence hashes.
- Camera VLAN, no internet, audio disabled, visible privacy control.
- Short retention and storage telemetry.
- Calibration/replay dataset of normal room transitions.

## Design for

- Remote Pi/edge node with signed events.
- Multiple cameras with identity and cross-camera correlation.
- Local accelerator and privacy-preserving crops.
- Speaker output as a separate capability and policy domain.

## Defer

- Face recognition, microphone, emotion detection, continuous recording, cloud-first video, and third-party surveillance.
- Buying a GPU before profiling.
- Treating “went to bed” or “exercising” as ground truth.
