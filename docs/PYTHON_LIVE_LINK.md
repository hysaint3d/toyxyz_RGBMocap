# Python Live Link (SaintMocap) — experimental

An independent Stream target derived from Hysaint's SaintMocap Operator V5
Python Live Link sender. It implements UE UDP Messaging v17 / Live Link v2
without a C++ compiler, Unreal commandlet or cbor2 package on the sender.
NumPy and PySide6 are already used by RGB MoCap. Existing Blender, VMC and
upstream Unreal Live Link options are not renamed or replaced.

## Use

1. Choose **Stream > Target > Python Live Link (SaintMocap)**.
2. For the same PC, keep **Local IPv4 = 127.0.0.1** and local port **Automatic**.
   For a LAN experiment, select a concrete local interface IPv4. Optionally enter
   the receiver's UDP Messaging unicast endpoint as **UE static endpoint**.
   The local port is the sender's port, not a Live Link Face destination port.
3. For prepared offline motion, check the desired people and click
   **Start Python Live Link**. Play or scrub; pausing repeats the current pose.
4. In Unreal, enable **Live Link** and **UDP Messaging**. Open Live Link and add
   **Message Bus Source > RGB MoCap Python (SaintMocap)**.
5. Use a matching source skeleton and Live Link Animation Blueprint, then set
   up target retargeting. This mode does not configure a MetaHuman or promise
   compatibility with the official RGB MoCap Connect receiver extension.
6. Click **Stop Python Live Link** to stop. Changing targets or closing the
   application stops its owned sender. The local interface/port can be edited
   while stopped. If the sender fails, Stop and Start to retry.

PEAR uses accepted preview body/finger packets through the existing VMC hooks.
Choose this target after entering PEAR, start the output and start live tracking
separately. Tracking loss clears the subject after 0.75 seconds. Stopping
tracking or leaving PEAR stops the sender. The integrated feature branch includes these hooks. A standalone Python-only
patch on an unmodified upstream installation does not add PEAR live hooks. No recording, inference or facial capture is started by streaming.

## Skeleton and transport contract

Prepared motion preserves the complete StreamRig hierarchy (including GEM-X's
Native77), source bind convention and scene placement. Parent-local centimetre
transforms and XYZW quaternions match upstream's Unreal conversion. Subject
labels include a stable person identity derived from project/model/person.
PEAR publishes 52 body/finger joints as RGBMoCap_PEAR. Its names and hierarchy
are distinct from prepared source rigs: prepare an appropriate receiver mapping.
No mesh, weights, images, face coefficients or automatic retarget is transmitted.

One latest snapshot is copied into a worker slot; conversion and all network
I/O happen on that worker. Limits: 128 selected people, 256 bones per prepared
person, 16 receiving clients. Frames repeat at up to 30 Hz. Missing takes,
unchecked people, stale GUI snapshots and live tracking loss withdraw subjects.
Heartbeats continue while the source runs. Client inactivity expires after 10 s.
The optional endpoint and LAN mode are not verified with physical receivers.

The V5 CBOR/envelope/segmentation code is reused with Unicode FString support,
bounded inbound decoding and a separate provider name. Outgoing segments carry
at most 1024 payload bytes. Static hierarchy data are repeated every second;
this prototype uses best-effort UDP rather than claiming UE reliable-message
acknowledgement/retransmission support. Clear/Bye packets can also be lost, and
receivers may retain a last pose. Real UE interoperability, engine-version
compatibility and character animation still require testing. Use trusted networks.

## Local installation without changing inference runtimes

Close RGB MoCap. With this patch folder available locally, run:

```powershell
& 'E:\RGBMoCap\runtime\python.exe' -X utf8 -B 'C:\Users\hysaint\Desktop\Codex\PythonLiveLink\apply_python_livelink.py' --root 'E:\RGBMoCap'
```

Use `--dry-run` to validate without writing. The installer accepts only the
reviewed Stream source baselines, preserves existing target indices, takes a
source backup under local_patches, holds the app session lock and rolls back
file writes on failure. It does not update packages, models or projects.
A Git checkout of this feature branch already includes the modules and PEAR hooks.
The guarded patch installer is only for the separately reviewed Stream baselines.
This integration was tested in an isolated source checkout; the E: installation,
models, projects and inference runtimes were not modified.

## Validation

Numerical tests cover parent-local FK reconstruction for 52/77-bone fixtures,
scene transforms, aligned PEAR equivalence, Unicode names, both V5 CBOR formats,
discovery/connect replies and segmented skeleton/frame/clear messages. Packet
replay is not proof of Unreal interoperability. Real localhost UDP tests are
included and skip explicitly when an independent loopback probe fails.

On 2026-11-25 the integrated source passed 32 tests: six PEAR/VMC, five VMC
rig, seven Python sender, three installer, seven official Unreal stream and four
reference-export checks. Localhost UDP tests ran successfully without skips.
The real Qt lifecycle harness passed with fake transports: offline selection,
playhead/project identity, live PEAR routing, all target modes and sender cleanup.
Full MainWindow import and mixin resolution passed using the existing GUI runtime.
Untouched upstream Stream methods (including face sampling, reference export,
Blender port rollback and baking) match the reviewed main source AST exactly.
These are source/transport checks; physical cameras, GPU inference, actual UE
receivers, character rendering and Blender baking were not tested in this merge.

## Integrated Stream targets

The feature branch merges official main `cdf4d98a` and keeps its target indices:
None (0), Blender (1), official Unreal Live Link (2), then VMC (3) and
Python Live Link (SaintMocap) (4). Official Unreal keeps prepared body/face
streaming and reference FBX export. Live PEAR uses VMC or the Python sender.
The streaming knee-lock experiment remains reverted.

Original RGB MoCap conversion code retains its MIT license. Existing third-party
notices and model terms continue to apply. Protocol API references:
- https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/LiveLinkMessageBusFramework
- https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/LiveLinkMessageBusFramework/FLiveLinkClearSubject
