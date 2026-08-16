# ADR-007: Bless a wired PoE ONVIF Profile T and RTSP camera

- **Status:** Accepted for V1 camera phase
- **Date:** 2026-08-15

## Context

The initial vision capability needs reliable local streaming, low-light options, vendor independence, and network isolation. Consumer cloud cameras can require vendor services, opaque processing, and Wi-Fi reliability.

## Decision

Use a wired PoE IP camera supporting ONVIF Profile T and a local RTSP stream. Place it on a camera VLAN with no internet access. Pull media only from the perception adapter. Use unique credentials, current firmware, visible/private-space placement, and a local short ring buffer with selected event clips.

## Alternatives considered

- USB camera: simple and private, but cable-length/placement and host dependency can be awkward.
- Raspberry Pi CSI camera: flexible edge build, but more DIY hardware/OS maintenance.
- Wi-Fi/cloud camera: convenient but weaker reliability/privacy/vendor independence.
- WebRTC-native camera: useful for interactive viewing, less universal for stable acquisition.

## Consequences

- PoE switch/injector and cabling are required.
- ONVIF conformance does not guarantee perfect interoperability; test the exact model.
- Camera compromise remains possible, so no analytics output is trusted as fact.
- Visitor/third-party consent and retention are product requirements.

## Revisit when

A different physical environment makes USB/CSI materially simpler, multiple sites require edge nodes, or the selected model’s RTSP/low-light quality fails calibration.
