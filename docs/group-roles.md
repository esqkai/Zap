# Groups, Sudo and Endpoint roles

## Concepts

- A **group** is the user's collection of paired Nxxt Level installations and strips.
- A **member** is one installation, identified independently of its display name.
- An **Endpoint** is the normal group role. It can control only outlets explicitly assigned to that member.
- **Sudo** is a manually claimed, exclusive elevated role. It can control every registered outlet and is intended to perform group-level management.
- Releasing Sudo leaves the role vacant. There is no automatic nomination or election.
- Battery monitoring and charging automation are optional capabilities, not requirements for group membership.

## Shared naming

Each strip has a group-wide display name and four group-wide outlet names. Names are associated with the strip identity and channel, not a particular computer, so every paired installation can display the same labels.

## Important implementation boundary

`GroupRegistry` is currently an in-memory domain model with unit tests. It is not yet connected to persistent storage, authenticated pairing, the WebSocket protocol, the desktop UI, or the physical strip command path. It must not be treated as a security boundary until those integrations are implemented and tested.

The eventual network service must authenticate each member separately, enforce Sudo and outlet permissions on the controller (not merely in the UI), serialize role claims atomically, and publish role/name changes to all clients. A disconnected Sudo must not trigger an automatic nomination. The user must explicitly claim the vacant role.

The MTTL-W01 still requires a reachable device connection hub. Sudo is a user-control role and does not itself move the strip's configured TCP destination.
