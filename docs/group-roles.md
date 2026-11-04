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


## Strip names, charger pairing and notifications

- Every strip has a group-wide display name.
- Every strip outlet (1–4) has a group-wide display name.
- A member with the optional `battery_monitoring` capability can be paired with one charger outlet per strip. An outlet can be assigned to only one member's charger automation on that strip.
- Battery automation must use the explicit laptop-to-outlet assignment; it must never guess which charger belongs to which laptop.
- Automation push notifications are routed only to the current Sudo. With no Sudo, or when notifications are disabled by Sudo, no push recipient is returned.
- Notification text includes the laptop/member name, battery percentage, outlet name and strip name.
- An event saying the assistant switched a charger on/off may be emitted only after the physical strip has confirmed the corresponding relay state. A requested command or optimistic UI update is not confirmation.
- The 100% stop rule is a proposed automation policy; hysteresis, thresholds, user enablement, and physical relay confirmation must be implemented and tested before it can operate hardware.


## Persistence

`GroupStore` stores group configuration in a local SQLite database:
- member IDs, display names, platform labels and optional capabilities
- outlet permissions and laptop-to-charger assignments
- strip names and all four outlet names
- notification preference and the last recorded Sudo identity

Secrets such as Wi-Fi passwords, pairing tokens and device credentials are not stored here. Online presence is deliberately reset to offline on load because it must be re-established by a live authenticated connection.

The store is a local persistence primitive. It is not yet a distributed database or a multi-host conflict-resolution system. The connection hub must be the single writer for a group, and changes must be committed transactionally before being broadcast. Multi-controller replication is not implemented.
