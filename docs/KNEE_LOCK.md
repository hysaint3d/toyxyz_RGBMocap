# Manual kneeling contact lock �X experimental

In Stream, choose VMC or Python Live Link (SaintMocap). Kneel first, then enable
**Lock left knee** and/or **Lock right knee**. Each knee captures its current
world-space joint centre on the next outgoing sample. **Re-anchor knees**
captures the current pose again. Release both switches before standing up.
The controls apply to each selected outgoing person, not just the highlighted row.

This does not estimate whether the actor is kneeling and does not snap the knee
joint to floor height. A joint centre sits above the visible knee surface; its
captured position is the anchor. It cannot repair an initially incorrect kneel,
floor calibration or avatar retarget. No AI model or inference package is added.

The lock runs in the sender worker, after pose conversion. Source motion,
preview, cached results and exports remain unmodified. Source frame bone lengths
are preserved through rigid subtree rotations. A pelvis translation (maximum
35 cm) makes the hip-to-knee lengths compatible with one or two knee anchors.
Shins aim toward the original ankle positions; ankles/toes may move when those
positions are unreachable. Source foot world orientations are retained. Knee
contact has priority over upstream foot lock; feet are not independently fixed.

Conflicting dual-knee constraints, unsupported skeletons or excessive pelvis
correction report an output error rather than stretching bones. Release or
re-anchor to recover. This is a manual contact tool, with no automatic kneeling
detection, entry/release blend or foot/knee/body multi-contact solver. Toggling
it off or changing anchors can move the output pose immediately.

Anchors reset on sender stop, tracking loss, actor/model/take changes, PEAR
generation/alignment/rig revisions, backward seeking and forward jumps over
10 frames. With switches still on, the next valid sample captures new anchors.
The source-key logic also prevents a contact from crossing to another person.

Supported names: VMC UpperLeg/LowerLeg, Mixamo UpLeg/Leg, and SOMA Leg/Shin.
Each leg must be a direct hip-knee-ankle chain. Prepared rigs preserve all bones
including fingers and SOMA helpers. VMC and Live Link use their existing output
axes/units; the solver uses metres internally. Live Link converts cm to metres
and back only within this correction.

## Validation

The 28-test local suite passed, including numerical knee positions, bone lengths,
foot orientations, recapture/reset, unit conversion, conflict handling, installer
rollback and real localhost UDP messages from VMC and Python Live Link.
Real Qt controls passed with fake transports. The installed application passed
the source-version dry run. No full application, physical camera, avatar
retarget or Unreal-rendered kneeling test is claimed.

Validation uses synthetic kneeling poses, single/double knee anchors, root
movement, preserved bone lengths, source immutability, output units, unlock/
re-anchor/source reset, invalid constraints and sender/control integration.
Real camera kneeling and receiver avatar contact accuracy still require testing.
